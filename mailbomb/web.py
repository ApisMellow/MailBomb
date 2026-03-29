import json
from flask import Flask, render_template, request, jsonify
from mailbomb.auth import get_gmail_service
from mailbomb.db import get_connection, init_db
from mailbomb.executor import resolve_message_ids, trash_messages, untrash_messages
from mailbomb.reviewer import rank_patterns
from mailbomb.snippets import get_snippet, fetch_and_cache_snippet, extract_plaintext
from mailbomb.rules import add_rule


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    # Track session state
    _session = {"kept": set(), "skipped": set(), "trashed_ids": []}

    def _get_conn():
        return get_connection(app.config["DB_PATH"])

    @app.route("/")
    def index():
        return render_template("review.html")

    @app.route("/api/patterns")
    def api_patterns():
        conn = _get_conn()
        patterns = rank_patterns(conn)
        # Filter out already-kept senders this session
        patterns = [p for p in patterns if p["sender_email"] not in _session["kept"]]
        conn.close()
        return jsonify(patterns)

    @app.route("/api/snippet/<gmail_id>")
    def api_snippet(gmail_id):
        conn = _get_conn()
        snippet = get_snippet(conn, gmail_id)
        conn.close()
        if snippet is None:
            # Try fetching from Gmail (requires auth)
            try:
                service = get_gmail_service()
                conn = _get_conn()
                snippet = fetch_and_cache_snippet(service, conn, gmail_id)
                conn.close()
            except Exception as e:
                return jsonify({"snippet": f"[Could not fetch: {e}]"})
        return jsonify({"snippet": snippet or ""})

    @app.route("/api/fullmessage/<gmail_id>")
    def api_fullmessage(gmail_id):
        """Fetch the full message body (no truncation) for the overlay view."""
        try:
            service = get_gmail_service()
            msg = service.users().messages().get(
                userId="me", id=gmail_id, format="full"
            ).execute()
            payload = msg.get("payload", {})
            parts = payload.get("parts", [])
            if not parts:
                parts = [payload]
            text = extract_plaintext(parts)
            return jsonify({"body": text})
        except Exception as e:
            return jsonify({"body": f"[Could not fetch full message: {e}]"})

    @app.route("/api/trash", methods=["POST"])
    def api_trash():
        data = request.get_json()
        sender_email = data.get("sender_email")
        list_id = data.get("list_id")

        if not sender_email and not list_id:
            return jsonify({"error": "sender_email or list_id required"}), 400

        conn = _get_conn()
        ids = resolve_message_ids(conn, sender_email=sender_email, list_id=list_id)
        conn.close()

        if ids:
            count = trash_messages(ids, db_path=app.config["DB_PATH"])
            _session["trashed_ids"].extend(ids)
        else:
            count = 0

        return jsonify({"trashed": count})

    @app.route("/api/keep", methods=["POST"])
    def api_keep():
        data = request.get_json()
        sender_email = data.get("sender_email")
        _session["kept"].add(sender_email)
        return jsonify({"kept": True})

    @app.route("/api/skip", methods=["POST"])
    def api_skip():
        data = request.get_json()
        sender_email = data.get("sender_email")
        _session["skipped"].add(sender_email)
        return jsonify({"skipped": True})

    @app.route("/api/rule", methods=["POST"])
    def api_rule():
        data = request.get_json()
        sender_email = data.get("sender_email")
        list_id = data.get("list_id")

        if not sender_email and not list_id:
            return jsonify({"error": "sender_email or list_id required"}), 400

        # Trash messages
        conn = _get_conn()
        ids = resolve_message_ids(conn, sender_email=sender_email, list_id=list_id)
        conn.close()

        if ids:
            trash_messages(ids, db_path=app.config["DB_PATH"])
            _session["trashed_ids"].extend(ids)

        # Save rule
        conn = _get_conn()
        add_rule(conn, sender_email=sender_email, list_id=list_id)
        conn.close()

        return jsonify({"rule_created": True, "trashed": len(ids)})

    @app.route("/api/stats")
    def api_stats():
        conn = _get_conn()
        active = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM messages WHERE deleted = 0"
        ).fetchone()
        deleted = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM messages WHERE deleted = 1"
        ).fetchone()
        conn.close()
        return jsonify({
            "active_count": active[0],
            "active_size": active[1],
            "deleted_count": deleted[0],
            "deleted_size": deleted[1],
        })

    @app.route("/api/session-trashed")
    def api_session_trashed():
        """Return all individual messages trashed this session with metadata."""
        ids = _session["trashed_ids"]
        if not ids:
            return jsonify([])
        conn = _get_conn()
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT gmail_id, sender_email, subject, date, size_bytes "
            f"FROM messages WHERE gmail_id IN ({placeholders}) "
            f"ORDER BY sender_email, date",
            ids,
        ).fetchall()
        conn.close()
        return jsonify([
            {
                "gmail_id": r[0],
                "sender_email": r[1],
                "subject": r[2],
                "date": r[3],
                "size_bytes": r[4],
            }
            for r in rows
        ])

    @app.route("/api/untrash", methods=["POST"])
    def api_untrash():
        """Restore individual messages from trash."""
        data = request.get_json()
        gmail_ids = data.get("gmail_ids", [])
        if not gmail_ids:
            return jsonify({"error": "gmail_ids required"}), 400
        count = untrash_messages(gmail_ids, db_path=app.config["DB_PATH"])
        # Remove from session tracking
        restored = set(gmail_ids)
        _session["trashed_ids"] = [i for i in _session["trashed_ids"] if i not in restored]
        return jsonify({"restored": count})

    @app.route("/api/prefetch", methods=["POST"])
    def api_prefetch():
        """Prefetch one snippet per pattern group for fast card display."""
        try:
            service = get_gmail_service()
        except Exception as e:
            return jsonify({"prefetched": 0, "error": str(e)})

        conn = _get_conn()
        patterns = rank_patterns(conn)
        count = 0
        for p in patterns[:30]:
            gmail_id = p.get("sample_gmail_id")
            if gmail_id:
                try:
                    fetch_and_cache_snippet(service, conn, gmail_id)
                    count += 1
                except Exception:
                    continue
        conn.close()
        return jsonify({"prefetched": count})

    return app
