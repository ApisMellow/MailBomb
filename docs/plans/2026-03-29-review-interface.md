# Review Interface Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Build a local web-based triage interface (`mailbomb review`) that surfaces likely-junk email patterns, shows representative snippets, and lets the user confirm/deny bulk actions via voice or keyboard.

**Architecture:** Flask dev server on localhost serves a single-page triage UI. A pattern ranker groups messages by sender/list, scores them by junk likelihood, and sorts highest-first. Each pattern card shows metadata, stats, and one pre-fetched body snippet. The browser's Web Speech API handles voice input. Keyboard shortcuts (t/k/s/r/m) work as fallback. Actions execute against Gmail API in real-time via fetch() calls to Flask endpoints. Persistent rules stored in a new SQLite table.

**Tech Stack:** Flask, Jinja2, vanilla JavaScript, Web Speech API, existing Gmail API auth, SQLite

---

### Task 1: Add Flask Dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add flask to dependencies**

In `pyproject.toml`, add `"flask>=3.0.0"` to the dependencies list:

```toml
dependencies = [
    "google-api-python-client>=2.100.0",
    "google-auth-oauthlib>=1.0.0",
    "click>=8.1.0",
    "rich>=13.0.0",
    "flask>=3.0.0",
]
```

**Step 2: Install updated dependencies**

Run: `pip install -e .`
Expected: Flask installed successfully

**Step 3: Verify import**

Run: `.venv/bin/python -c "import flask; print(flask.__version__)"`
Expected: Prints version 3.x

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add Flask dependency for review interface"
```

---

### Task 2: Snippets Table and Fetch Logic

**Files:**
- Modify: `mailbomb/db.py`
- Create: `mailbomb/snippets.py`
- Create: `tests/test_snippets.py`

**Step 1: Write the failing tests**

Create `tests/test_snippets.py`:

```python
import pytest
from mailbomb.db import init_db, get_connection, upsert_message
from mailbomb.snippets import get_snippet, save_snippet, extract_plaintext


@pytest.fixture
def db_with_messages(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    upsert_message(conn, {
        "gmail_id": "abc123",
        "thread_id": "t1",
        "sender": "spam@deals.com",
        "sender_email": "spam@deals.com",
        "subject": "Big Sale!",
        "date": "Mon, 10 Jan 2005 08:00:00 -0800",
        "size_bytes": 5000,
        "labels": "INBOX",
        "list_id": None,
    })
    yield conn, db_path
    conn.close()


def test_save_and_get_snippet(db_with_messages):
    conn, db_path = db_with_messages
    save_snippet(conn, "abc123", "Hey check out these deals today...")
    result = get_snippet(conn, "abc123")
    assert result == "Hey check out these deals today..."


def test_get_snippet_not_found(db_with_messages):
    conn, db_path = db_with_messages
    result = get_snippet(conn, "nonexistent")
    assert result is None


def test_extract_plaintext_from_text():
    parts = [{"mimeType": "text/plain", "body": {"data": "SGVsbG8gV29ybGQ="}}]
    result = extract_plaintext(parts)
    assert result == "Hello World"


def test_extract_plaintext_from_html():
    import base64
    html = "<html><body><p>Hello <b>World</b></p></body></html>"
    encoded = base64.urlsafe_b64encode(html.encode()).decode()
    parts = [{"mimeType": "text/html", "body": {"data": encoded}}]
    result = extract_plaintext(parts)
    assert "Hello" in result
    assert "<b>" not in result


def test_extract_plaintext_multipart():
    import base64
    text = "Plain version"
    encoded = base64.urlsafe_b64encode(text.encode()).decode()
    parts = [
        {"mimeType": "text/plain", "body": {"data": encoded}},
        {"mimeType": "text/html", "body": {"data": "SFRNTA=="}},
    ]
    result = extract_plaintext(parts)
    assert result == "Plain version"


def test_extract_plaintext_empty():
    result = extract_plaintext([])
    assert result == ""
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_snippets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mailbomb.snippets'`

**Step 3: Add snippets table to db.py**

In `mailbomb/db.py`, inside the `init_db` function, after the existing CREATE TABLE and CREATE INDEX statements, add:

```python
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS snippets (
            gmail_id    TEXT PRIMARY KEY,
            body_preview TEXT,
            FOREIGN KEY (gmail_id) REFERENCES messages(gmail_id)
        )
    """)
```

**Step 4: Write snippets.py**

Create `mailbomb/snippets.py`:

```python
import base64
import re


def save_snippet(conn, gmail_id, body_preview):
    """Save a body preview snippet for a message."""
    conn.execute(
        "INSERT OR REPLACE INTO snippets (gmail_id, body_preview) VALUES (?, ?)",
        (gmail_id, body_preview),
    )
    conn.commit()


def get_snippet(conn, gmail_id):
    """Get a cached body preview snippet. Returns None if not cached."""
    row = conn.execute(
        "SELECT body_preview FROM snippets WHERE gmail_id = ?", (gmail_id,)
    ).fetchone()
    return row[0] if row else None


def extract_plaintext(parts):
    """Extract plaintext from Gmail message payload parts.

    Prefers text/plain, falls back to stripping HTML tags from text/html.
    """
    text_part = None
    html_part = None

    for part in parts:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        if not data:
            continue
        if mime == "text/plain" and text_part is None:
            text_part = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif mime == "text/html" and html_part is None:
            html_part = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    if text_part:
        return text_part
    if html_part:
        # Strip HTML tags
        text = re.sub(r"<style[^>]*>.*?</style>", "", html_part, flags=re.DOTALL)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    return ""


def fetch_and_cache_snippet(service, conn, gmail_id, max_chars=300):
    """Fetch message body from Gmail API, extract plaintext, cache it.

    Returns the snippet string (truncated to max_chars).
    """
    cached = get_snippet(conn, gmail_id)
    if cached is not None:
        return cached

    msg = service.users().messages().get(
        userId="me", id=gmail_id, format="full"
    ).execute()

    payload = msg.get("payload", {})
    parts = payload.get("parts", [])
    if not parts:
        # Single-part message — body is directly on payload
        parts = [payload]

    text = extract_plaintext(parts)
    snippet = text[:max_chars]
    save_snippet(conn, gmail_id, snippet)
    return snippet
```

**Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_snippets.py -v`
Expected: All 6 tests PASS

**Step 6: Commit**

```bash
git add mailbomb/db.py mailbomb/snippets.py tests/test_snippets.py
git commit -m "feat: snippet storage and plaintext extraction for message previews"
```

---

### Task 3: Rules Table and Logic

**Files:**
- Modify: `mailbomb/db.py`
- Create: `mailbomb/rules.py`
- Create: `tests/test_rules.py`

**Step 1: Write the failing tests**

Create `tests/test_rules.py`:

```python
import pytest
from mailbomb.db import init_db, get_connection
from mailbomb.rules import add_rule, get_rules, matches_rule, remove_rule


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()


def test_add_and_get_rules(db):
    add_rule(db, sender_email="spam@deals.com")
    rules = get_rules(db)
    assert len(rules) == 1
    assert rules[0]["sender_email"] == "spam@deals.com"


def test_add_rule_with_list_id(db):
    add_rule(db, list_id="<dev.example.com>")
    rules = get_rules(db)
    assert len(rules) == 1
    assert rules[0]["list_id"] == "<dev.example.com>"


def test_matches_rule_by_sender(db):
    add_rule(db, sender_email="spam@deals.com")
    assert matches_rule(db, sender_email="spam@deals.com") is True
    assert matches_rule(db, sender_email="friend@gmail.com") is False


def test_matches_rule_by_list_id(db):
    add_rule(db, list_id="<dev.example.com>")
    assert matches_rule(db, list_id="<dev.example.com>") is True
    assert matches_rule(db, list_id="<other.list>") is False


def test_remove_rule(db):
    add_rule(db, sender_email="spam@deals.com")
    remove_rule(db, sender_email="spam@deals.com")
    rules = get_rules(db)
    assert len(rules) == 0


def test_no_duplicate_rules(db):
    add_rule(db, sender_email="spam@deals.com")
    add_rule(db, sender_email="spam@deals.com")
    rules = get_rules(db)
    assert len(rules) == 1
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mailbomb.rules'`

**Step 3: Add rules table to db.py**

In `mailbomb/db.py`, inside the `init_db` function, after the snippets table creation, add:

```python
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_email TEXT,
            list_id      TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_rule_sender
        ON rules(sender_email) WHERE sender_email IS NOT NULL
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_rule_list
        ON rules(list_id) WHERE list_id IS NOT NULL
    """)
```

**Step 4: Write rules.py**

Create `mailbomb/rules.py`:

```python
def add_rule(conn, sender_email=None, list_id=None):
    """Add a trash rule. Messages matching this rule get auto-flagged."""
    if sender_email:
        conn.execute(
            "INSERT OR IGNORE INTO rules (sender_email) VALUES (?)",
            (sender_email,),
        )
    elif list_id:
        conn.execute(
            "INSERT OR IGNORE INTO rules (list_id) VALUES (?)",
            (list_id,),
        )
    conn.commit()


def get_rules(conn):
    """Return all rules as a list of dicts."""
    rows = conn.execute("SELECT * FROM rules ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def matches_rule(conn, sender_email=None, list_id=None):
    """Check if a sender or list matches an existing rule."""
    if sender_email:
        row = conn.execute(
            "SELECT 1 FROM rules WHERE sender_email = ?", (sender_email,)
        ).fetchone()
        if row:
            return True
    if list_id:
        row = conn.execute(
            "SELECT 1 FROM rules WHERE list_id = ?", (list_id,)
        ).fetchone()
        if row:
            return True
    return False


def remove_rule(conn, sender_email=None, list_id=None):
    """Remove a rule by sender or list."""
    if sender_email:
        conn.execute("DELETE FROM rules WHERE sender_email = ?", (sender_email,))
    elif list_id:
        conn.execute("DELETE FROM rules WHERE list_id = ?", (list_id,))
    conn.commit()
```

**Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_rules.py -v`
Expected: All 6 tests PASS

**Step 6: Commit**

```bash
git add mailbomb/db.py mailbomb/rules.py tests/test_rules.py
git commit -m "feat: rules table and logic for persistent trash rules"
```

---

### Task 4: Pattern Ranker

**Files:**
- Create: `mailbomb/reviewer.py`
- Create: `tests/test_reviewer.py`

**Step 1: Write the failing tests**

Create `tests/test_reviewer.py`:

```python
import pytest
from mailbomb.db import init_db, get_connection, upsert_message
from mailbomb.reviewer import rank_patterns


@pytest.fixture
def populated_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)

    # Bulk sender: newsletter, 50 messages, has list-id
    for i in range(50):
        upsert_message(conn, {
            "gmail_id": f"news_{i}",
            "thread_id": f"t_news_{i}",
            "sender": "updates@newsletter.com",
            "sender_email": "updates@newsletter.com",
            "subject": f"Weekly Digest #{i}",
            "date": f"Mon, {10 + (i % 20)} Jan 2007 08:00:00 -0800",
            "size_bytes": 3000,
            "labels": "INBOX",
            "list_id": "<digest.newsletter.com>",
        })

    # Automated sender: notifications, 30 messages, no list-id
    for i in range(30):
        upsert_message(conn, {
            "gmail_id": f"notif_{i}",
            "thread_id": f"t_notif_{i}",
            "sender": "noreply@social.com",
            "sender_email": "noreply@social.com",
            "subject": "Someone liked your post",
            "date": f"Tue, {10 + (i % 20)} Mar 2007 12:00:00 -0800",
            "size_bytes": 1500,
            "labels": "INBOX",
            "list_id": None,
        })

    # Personal sender: friend, 5 messages, varied subjects
    subjects = ["Dinner Friday?", "Re: Dinner Friday?", "Photos from trip",
                "Check this out", "Happy birthday!"]
    for i, subj in enumerate(subjects):
        upsert_message(conn, {
            "gmail_id": f"friend_{i}",
            "thread_id": f"t_friend_{i}",
            "sender": "alice@gmail.com",
            "sender_email": "alice@gmail.com",
            "subject": subj,
            "date": f"Wed, {10 + i} Feb 2007 09:00:00 -0800",
            "size_bytes": 8000,
            "labels": "INBOX,SENT",
            "list_id": None,
        })

    yield conn
    conn.close()


def test_rank_patterns_returns_groups(populated_db):
    patterns = rank_patterns(populated_db)
    assert len(patterns) == 3
    # Each pattern has required keys
    for p in patterns:
        assert "sender_email" in p
        assert "count" in p
        assert "total_size" in p
        assert "score" in p
        assert "sample_subjects" in p
        assert "sample_gmail_id" in p


def test_rank_patterns_bulk_scores_higher(populated_db):
    patterns = rank_patterns(populated_db)
    scores = {p["sender_email"]: p["score"] for p in patterns}
    # Newsletter and notifications should score higher than personal
    assert scores["updates@newsletter.com"] > scores["alice@gmail.com"]
    assert scores["noreply@social.com"] > scores["alice@gmail.com"]


def test_rank_patterns_sorted_by_score(populated_db):
    patterns = rank_patterns(populated_db)
    scores = [p["score"] for p in patterns]
    assert scores == sorted(scores, reverse=True)


def test_rank_patterns_has_sample_subjects(populated_db):
    patterns = rank_patterns(populated_db)
    for p in patterns:
        assert len(p["sample_subjects"]) > 0
        assert len(p["sample_subjects"]) <= 5


def test_rank_patterns_has_date_range(populated_db):
    patterns = rank_patterns(populated_db)
    for p in patterns:
        assert "earliest" in p
        assert "latest" in p


def test_rank_patterns_has_sample_gmail_id(populated_db):
    patterns = rank_patterns(populated_db)
    for p in patterns:
        assert p["sample_gmail_id"] is not None
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_reviewer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mailbomb.reviewer'`

**Step 3: Write reviewer.py**

Create `mailbomb/reviewer.py`:

```python
def rank_patterns(conn, limit=50):
    """Group messages by sender, score by junk likelihood, return sorted list.

    Scoring heuristic (higher = more likely junk):
    - message_count: more messages = more bulk-like
    - has_list_id: mailing list header present
    - subject_uniformity: low subject diversity = templated
    - noreply_sender: sender contains noreply/notify/no-reply
    - no_sent_label: you never replied (one-way communication)

    Returns list of dicts sorted by score descending:
    {
        sender_email, list_id, count, total_size, score,
        sample_subjects (up to 5), sample_gmail_id,
        earliest, latest
    }
    """
    rows = conn.execute("""
        SELECT sender_email,
               list_id,
               COUNT(*) as count,
               SUM(size_bytes) as total_size,
               MIN(date) as earliest,
               MAX(date) as latest
        FROM messages
        WHERE deleted = 0
        GROUP BY sender_email
        HAVING count >= 2
        ORDER BY count DESC
        LIMIT ?
    """, (limit,)).fetchall()

    patterns = []
    for row in rows:
        sender = row[0]
        list_id = row[1]
        count = row[2]
        total_size = row[3]
        earliest = row[4]
        latest = row[5]

        # Fetch sample subjects (up to 5 distinct)
        subjects = conn.execute("""
            SELECT DISTINCT subject FROM messages
            WHERE sender_email = ? AND deleted = 0
            LIMIT 5
        """, (sender,)).fetchall()
        sample_subjects = [s[0] for s in subjects if s[0]]

        # Fetch one representative gmail_id for snippet
        sample_row = conn.execute("""
            SELECT gmail_id FROM messages
            WHERE sender_email = ? AND deleted = 0
            LIMIT 1
        """, (sender,)).fetchone()
        sample_gmail_id = sample_row[0] if sample_row else None

        # Count distinct subjects for uniformity check
        distinct_count = conn.execute("""
            SELECT COUNT(DISTINCT subject) FROM messages
            WHERE sender_email = ? AND deleted = 0
        """, (sender,)).fetchone()[0]

        # Check if any messages have SENT label (indicates two-way)
        sent_count = conn.execute("""
            SELECT COUNT(*) FROM messages
            WHERE sender_email = ? AND deleted = 0 AND labels LIKE '%SENT%'
        """, (sender,)).fetchone()[0]

        # --- Scoring ---
        score = 0.0

        # Volume: log-scale, caps at ~40 points
        import math
        score += min(40, math.log2(max(count, 1)) * 6)

        # Has List-Id: strong bulk signal
        if list_id:
            score += 15

        # Subject uniformity: few unique subjects relative to count = templated
        if count > 5:
            uniformity = 1.0 - (distinct_count / count)
            score += uniformity * 20

        # Noreply/automated sender
        sender_lower = sender.lower()
        if any(kw in sender_lower for kw in ["noreply", "no-reply", "notify", "notification", "mailer-daemon", "postmaster"]):
            score += 15

        # No replies from user (one-way)
        if sent_count == 0:
            score += 10

        patterns.append({
            "sender_email": sender,
            "list_id": list_id,
            "count": count,
            "total_size": total_size,
            "score": round(score, 1),
            "sample_subjects": sample_subjects,
            "sample_gmail_id": sample_gmail_id,
            "earliest": earliest,
            "latest": latest,
        })

    patterns.sort(key=lambda p: p["score"], reverse=True)
    return patterns
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_reviewer.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add mailbomb/reviewer.py tests/test_reviewer.py
git commit -m "feat: pattern ranker scoring sender groups by junk likelihood"
```

---

### Task 5: Flask Web App and API Endpoints

**Files:**
- Create: `mailbomb/web.py`
- Create: `tests/test_web.py`

**Step 1: Write the failing tests**

Create `tests/test_web.py`:

```python
import json
import pytest
from unittest.mock import patch, MagicMock
from mailbomb.db import init_db, get_connection, upsert_message
from mailbomb.snippets import save_snippet
from mailbomb.web import create_app


@pytest.fixture
def app_with_data(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)

    for i in range(10):
        upsert_message(conn, {
            "gmail_id": f"spam_{i}",
            "thread_id": f"t_{i}",
            "sender": "deals@spam.com",
            "sender_email": "deals@spam.com",
            "subject": f"Deal #{i}",
            "date": f"Mon, {10 + i} Jan 2007 08:00:00 -0800",
            "size_bytes": 2000,
            "labels": "INBOX",
            "list_id": None,
        })
    save_snippet(conn, "spam_0", "Check out these amazing deals...")
    conn.close()

    app = create_app(db_path=db_path)
    app.config["TESTING"] = True
    yield app, db_path


@pytest.fixture
def client(app_with_data):
    app, db_path = app_with_data
    return app.test_client()


def test_index_returns_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"MailBomb" in response.data


def test_api_patterns(client):
    response = client.get("/api/patterns")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) >= 1
    assert data[0]["sender_email"] == "deals@spam.com"
    assert data[0]["count"] == 10


def test_api_snippet_cached(client):
    response = client.get("/api/snippet/spam_0")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "amazing deals" in data["snippet"]


def test_api_trash(client):
    with patch("mailbomb.web.trash_messages", return_value=10) as mock_trash:
        response = client.post(
            "/api/trash",
            data=json.dumps({"sender_email": "deals@spam.com"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["trashed"] == 10
        mock_trash.assert_called_once()


def test_api_keep(client):
    response = client.post(
        "/api/keep",
        data=json.dumps({"sender_email": "deals@spam.com"}),
        content_type="application/json",
    )
    assert response.status_code == 200


def test_api_rule(client):
    with patch("mailbomb.web.trash_messages", return_value=10):
        response = client.post(
            "/api/rule",
            data=json.dumps({"sender_email": "deals@spam.com"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["rule_created"] is True
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_web.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mailbomb.web'`

**Step 3: Write web.py**

Create `mailbomb/web.py`:

```python
import json
from flask import Flask, render_template, request, jsonify
from mailbomb.db import get_connection, init_db
from mailbomb.executor import resolve_message_ids, trash_messages
from mailbomb.reviewer import rank_patterns
from mailbomb.snippets import get_snippet, fetch_and_cache_snippet
from mailbomb.rules import add_rule


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    # Track session state: skipped and kept senders
    _session = {"kept": set(), "skipped": set()}

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
                from mailbomb.auth import get_gmail_service
                service = get_gmail_service()
                conn = _get_conn()
                snippet = fetch_and_cache_snippet(service, conn, gmail_id)
                conn.close()
            except Exception as e:
                return jsonify({"snippet": f"[Could not fetch: {e}]"})
        return jsonify({"snippet": snippet or ""})

    @app.route("/api/trash", methods=["POST"])
    def api_trash():
        data = request.get_json()
        sender_email = data.get("sender_email")
        list_id = data.get("list_id")

        conn = _get_conn()
        ids = resolve_message_ids(conn, sender_email=sender_email, list_id=list_id)
        conn.close()

        if ids:
            count = trash_messages(ids, db_path=app.config["DB_PATH"])
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

        # Trash messages
        conn = _get_conn()
        ids = resolve_message_ids(conn, sender_email=sender_email, list_id=list_id)
        conn.close()

        if ids:
            trash_messages(ids, db_path=app.config["DB_PATH"])

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

    return app
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_web.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add mailbomb/web.py tests/test_web.py
git commit -m "feat: Flask web app with API endpoints for triage actions"
```

---

### Task 6: Review HTML Template with Voice and Keyboard

**Files:**
- Create: `mailbomb/templates/review.html`

**Step 1: Create the templates directory**

Run: `mkdir -p mailbomb/templates`

**Step 2: Write the template**

Create `mailbomb/templates/review.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MailBomb Review</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: #16213e;
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #0f3460;
        }
        .header h1 { font-size: 20px; color: #e94560; }
        .progress {
            font-size: 14px;
            color: #a0a0a0;
        }
        .progress strong { color: #e94560; }
        .mic-status {
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
            padding: 8px 12px;
            border-radius: 6px;
            background: #0f3460;
        }
        .mic-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #666;
        }
        .mic-dot.active { background: #4ecca3; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .container { max-width: 700px; margin: 40px auto; padding: 0 24px; }
        .card {
            background: #16213e;
            border-radius: 12px;
            padding: 28px;
            border: 1px solid #0f3460;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 16px;
        }
        .sender { font-size: 18px; font-weight: 600; color: #fff; }
        .sender-email { font-size: 14px; color: #a0a0a0; margin-top: 4px; }
        .score-badge {
            background: #e94560;
            color: #fff;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 13px;
            font-weight: 600;
            white-space: nowrap;
        }
        .stats {
            display: flex;
            gap: 24px;
            margin-bottom: 16px;
            font-size: 14px;
            color: #a0a0a0;
        }
        .stats strong { color: #4ecca3; }
        .subjects {
            margin-bottom: 16px;
        }
        .subjects h3 {
            font-size: 13px;
            text-transform: uppercase;
            color: #666;
            margin-bottom: 8px;
        }
        .subject-line {
            font-size: 14px;
            color: #c0c0c0;
            padding: 4px 0;
            border-bottom: 1px solid #0f3460;
        }
        .snippet-box {
            background: #1a1a2e;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 20px;
            font-size: 14px;
            line-height: 1.6;
            color: #b0b0b0;
            max-height: 200px;
            overflow-y: auto;
        }
        .snippet-box h3 {
            font-size: 13px;
            text-transform: uppercase;
            color: #666;
            margin-bottom: 8px;
        }
        .actions {
            display: flex;
            gap: 12px;
        }
        .btn {
            flex: 1;
            padding: 12px;
            border: none;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.1s;
        }
        .btn:hover { transform: scale(1.02); }
        .btn:active { transform: scale(0.98); }
        .btn-trash { background: #e94560; color: #fff; }
        .btn-keep { background: #4ecca3; color: #1a1a2e; }
        .btn-skip { background: #0f3460; color: #a0a0a0; }
        .btn-rule { background: #533483; color: #fff; }
        .btn kbd {
            display: inline-block;
            background: rgba(0,0,0,0.2);
            padding: 1px 6px;
            border-radius: 3px;
            font-size: 12px;
            margin-left: 6px;
        }
        .voice-heard {
            text-align: center;
            padding: 8px;
            margin-top: 12px;
            font-size: 13px;
            color: #4ecca3;
            opacity: 0;
            transition: opacity 0.3s;
        }
        .voice-heard.show { opacity: 1; }
        .loading {
            text-align: center;
            padding: 60px;
            color: #a0a0a0;
            font-size: 18px;
        }
        .done {
            text-align: center;
            padding: 60px;
        }
        .done h2 { color: #4ecca3; margin-bottom: 12px; }
        .shortcuts {
            text-align: center;
            margin-top: 16px;
            font-size: 13px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>MailBomb Review</h1>
        <div class="progress" id="progress">Loading...</div>
        <div class="mic-status" id="micToggle" onclick="toggleMic()">
            <div class="mic-dot" id="micDot"></div>
            <span id="micLabel">Mic off</span>
        </div>
    </div>
    <div class="container">
        <div id="content">
            <div class="loading">Loading patterns...</div>
        </div>
        <div class="shortcuts">
            Keyboard: <kbd>T</kbd> Toss &nbsp; <kbd>K</kbd> Keep &nbsp; <kbd>S</kbd> Skip &nbsp; <kbd>R</kbd> Rule &nbsp; <kbd>M</kbd> More snippets
        </div>
    </div>

    <script>
        let patterns = [];
        let currentIndex = 0;
        let stats = { trashed: 0, trashedSize: 0, reviewed: 0 };
        let micActive = false;
        let recognition = null;

        // --- Data ---
        async function loadPatterns() {
            const resp = await fetch("/api/patterns");
            patterns = await resp.json();
            if (patterns.length > 0) {
                showCard(0);
            } else {
                document.getElementById("content").innerHTML =
                    '<div class="done"><h2>All clear!</h2><p>No patterns to review.</p></div>';
            }
            updateProgress();
        }

        async function loadSnippet(gmailId) {
            const resp = await fetch(`/api/snippet/${gmailId}`);
            const data = await resp.json();
            return data.snippet || "[No preview available]";
        }

        // --- Rendering ---
        function showCard(index) {
            if (index >= patterns.length) {
                document.getElementById("content").innerHTML =
                    '<div class="done"><h2>All done!</h2><p>No more patterns to review this session.</p></div>';
                return;
            }
            currentIndex = index;
            const p = patterns[index];
            const sizeMB = (p.total_size / (1024 * 1024)).toFixed(1);
            const scorePercent = Math.min(100, Math.round(p.score));
            const subjects = (p.sample_subjects || [])
                .map(s => `<div class="subject-line">${escHtml(s)}</div>`)
                .join("");

            document.getElementById("content").innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <div>
                            <div class="sender">${escHtml(p.sender_email)}</div>
                            ${p.list_id ? `<div class="sender-email">List: ${escHtml(p.list_id)}</div>` : ""}
                        </div>
                        <div class="score-badge">${scorePercent}% bulk</div>
                    </div>
                    <div class="stats">
                        <span><strong>${p.count.toLocaleString()}</strong> messages</span>
                        <span><strong>${sizeMB}</strong> MB</span>
                    </div>
                    <div class="subjects"><h3>Sample Subjects</h3>${subjects || "<em>No subjects</em>"}</div>
                    <div class="snippet-box" id="snippetBox">
                        <h3>Preview</h3>
                        <div id="snippetText">Loading...</div>
                    </div>
                    <div class="actions">
                        <button class="btn btn-trash" onclick="doAction('trash')">Toss <kbd>T</kbd></button>
                        <button class="btn btn-keep" onclick="doAction('keep')">Keep <kbd>K</kbd></button>
                        <button class="btn btn-skip" onclick="doAction('skip')">Skip <kbd>S</kbd></button>
                        <button class="btn btn-rule" onclick="doAction('rule')">Rule <kbd>R</kbd></button>
                    </div>
                    <div class="voice-heard" id="voiceHeard"></div>
                </div>
            `;

            // Load snippet
            if (p.sample_gmail_id) {
                loadSnippet(p.sample_gmail_id).then(text => {
                    const el = document.getElementById("snippetText");
                    if (el) el.textContent = text;
                });
            }
        }

        // --- Actions ---
        async function doAction(action) {
            const p = patterns[currentIndex];
            const body = JSON.stringify({
                sender_email: p.sender_email,
                list_id: p.list_id,
            });
            const opts = { method: "POST", headers: {"Content-Type": "application/json"}, body };

            if (action === "trash") {
                const resp = await fetch("/api/trash", opts);
                const data = await resp.json();
                stats.trashed += data.trashed;
                stats.trashedSize += p.total_size;
            } else if (action === "keep") {
                await fetch("/api/keep", opts);
            } else if (action === "skip") {
                await fetch("/api/skip", opts);
            } else if (action === "rule") {
                const resp = await fetch("/api/rule", opts);
                const data = await resp.json();
                stats.trashed += data.trashed;
                stats.trashedSize += p.total_size;
            }

            stats.reviewed++;
            updateProgress();
            showCard(currentIndex + 1);
        }

        function updateProgress() {
            const sizeMB = (stats.trashedSize / (1024 * 1024)).toFixed(1);
            document.getElementById("progress").innerHTML =
                `Reviewed <strong>${stats.reviewed}</strong>/${patterns.length} — ` +
                `<strong>${stats.trashed.toLocaleString()}</strong> trashed (${sizeMB} MB)`;
        }

        // --- Keyboard ---
        document.addEventListener("keydown", (e) => {
            if (e.target.tagName === "INPUT") return;
            switch (e.key.toLowerCase()) {
                case "t": doAction("trash"); break;
                case "k": doAction("keep"); break;
                case "s": doAction("skip"); break;
                case "r": doAction("rule"); break;
                case "m": loadMoreSnippets(); break;
            }
        });

        async function loadMoreSnippets() {
            const p = patterns[currentIndex];
            const conn_ids = await fetch(
                `/api/patterns`
            ).then(r => r.json());
            // Just show a note for now — could expand to fetch more samples
            const el = document.getElementById("snippetText");
            if (el) el.textContent += "\n\n[Use Gmail to inspect more messages from this sender]";
        }

        // --- Voice ---
        function setupVoice() {
            if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
                document.getElementById("micLabel").textContent = "No mic support";
                return;
            }
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            recognition = new SR();
            recognition.continuous = true;
            recognition.interimResults = false;

            recognition.onresult = (event) => {
                const last = event.results[event.results.length - 1];
                if (!last.isFinal) return;
                const text = last[0].transcript.trim().toLowerCase();
                showVoiceHeard(text);

                if (text.includes("toss") || text.includes("trash")) doAction("trash");
                else if (text.includes("keep")) doAction("keep");
                else if (text.includes("skip") || text.includes("next")) doAction("skip");
                else if (text.includes("rule")) doAction("rule");
                else if (text.includes("show") || text.includes("more")) loadMoreSnippets();
            };

            recognition.onend = () => {
                if (micActive) recognition.start();
            };
        }

        function toggleMic() {
            if (!recognition) return;
            micActive = !micActive;
            if (micActive) {
                recognition.start();
                document.getElementById("micDot").classList.add("active");
                document.getElementById("micLabel").textContent = "Listening";
            } else {
                recognition.stop();
                document.getElementById("micDot").classList.remove("active");
                document.getElementById("micLabel").textContent = "Mic off";
            }
        }

        function showVoiceHeard(text) {
            const el = document.getElementById("voiceHeard");
            if (!el) return;
            el.textContent = `Heard: "${text}"`;
            el.classList.add("show");
            setTimeout(() => el.classList.remove("show"), 2000);
        }

        function escHtml(s) {
            const d = document.createElement("div");
            d.textContent = s || "";
            return d.innerHTML;
        }

        // --- Init ---
        setupVoice();
        loadPatterns();
    </script>
</body>
</html>
```

**Step 3: Verify template renders**

Run: `.venv/bin/pytest tests/test_web.py::test_index_returns_html -v`
Expected: PASS (the test from Task 5 already checks this)

**Step 4: Commit**

```bash
git add mailbomb/templates/review.html
git commit -m "feat: triage UI with voice recognition and keyboard shortcuts"
```

---

### Task 7: CLI Review Command

**Files:**
- Modify: `mailbomb/cli.py`

**Step 1: Write the failing test**

Add to `tests/test_web.py`:

```python
from click.testing import CliRunner
from mailbomb.cli import cli


def test_review_command_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["review", "--help"])
    assert result.exit_code == 0
    assert "review" in result.output.lower()
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_web.py::test_review_command_exists -v`
Expected: FAIL — `No such command 'review'`

**Step 3: Add review command to cli.py**

At the top of `mailbomb/cli.py`, no new imports needed (Flask imports happen inside the function). Add this command after the `stats` command:

```python
@cli.command()
@click.option("--port", default=5000, help="Port for the review server")
def review(port):
    """Launch the web-based triage interface."""
    import webbrowser
    from mailbomb.web import create_app

    console.print(f"\n[bold]Starting MailBomb Review on port {port}...[/bold]")
    console.print(f"  Open [link]http://localhost:{port}[/link] if it doesn't open automatically\n")
    console.print("  [dim]Press Ctrl+C to stop[/dim]\n")

    app = create_app()
    webbrowser.open(f"http://localhost:{port}")
    app.run(port=port, debug=False)
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_web.py::test_review_command_exists -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add mailbomb/cli.py tests/test_web.py
git commit -m "feat: 'mailbomb review' command launches web triage interface"
```

---

### Task 8: Snippet Prefetch on Startup

**Files:**
- Modify: `mailbomb/web.py`

**Step 1: Write the failing test**

Add to `tests/test_web.py`:

```python
def test_api_prefetch(client):
    """Prefetch endpoint triggers snippet loading."""
    with patch("mailbomb.web.get_gmail_service") as mock_svc:
        mock_gmail = MagicMock()
        mock_svc.return_value = mock_gmail
        mock_gmail.users().messages().get().execute.return_value = {
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": "SGVsbG8gV29ybGQ="},
            }
        }
        response = client.post("/api/prefetch")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "prefetched" in data
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_web.py::test_api_prefetch -v`
Expected: FAIL — 404

**Step 3: Add prefetch endpoint to web.py**

Inside the `create_app` function in `mailbomb/web.py`, add this route:

```python
    @app.route("/api/prefetch", methods=["POST"])
    def api_prefetch():
        """Prefetch one snippet per pattern group for fast card display."""
        from mailbomb.auth import get_gmail_service
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
```

Then in the `review.html` template, add a prefetch call in the init section, after `loadPatterns()`:

```javascript
        // --- Init ---
        setupVoice();
        loadPatterns();
        // Prefetch snippets in background
        fetch("/api/prefetch", { method: "POST" });
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_web.py::test_api_prefetch -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mailbomb/web.py mailbomb/templates/review.html
git commit -m "feat: prefetch snippets on startup for instant card display"
```

---

### Task 9: Full Integration Test

**Files:**
- Create: `tests/test_review_integration.py`

**Step 1: Write the integration test**

Create `tests/test_review_integration.py`:

```python
"""Integration test: load patterns → view card → trash → verify state."""
import json
import pytest
from unittest.mock import patch
from mailbomb.db import init_db, get_connection, upsert_message, count_messages
from mailbomb.snippets import save_snippet
from mailbomb.web import create_app


@pytest.fixture
def full_app(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)

    # Add a bulk sender
    for i in range(20):
        upsert_message(conn, {
            "gmail_id": f"bulk_{i}",
            "thread_id": f"t_{i}",
            "sender": "newsletter@spam.com",
            "sender_email": "newsletter@spam.com",
            "subject": f"Newsletter #{i}",
            "date": f"Mon, {10 + (i % 20)} Jan 2007 08:00:00 -0800",
            "size_bytes": 3000,
            "labels": "INBOX",
            "list_id": "<spam.newsletter.com>",
        })
    save_snippet(conn, "bulk_0", "Subscribe to our newsletter...")

    # Add a personal sender
    upsert_message(conn, {
        "gmail_id": "personal_1",
        "thread_id": "tp_1",
        "sender": "friend@gmail.com",
        "sender_email": "friend@gmail.com",
        "subject": "Lunch tomorrow?",
        "date": "Tue, 15 Mar 2007 12:00:00 -0800",
        "size_bytes": 2000,
        "labels": "INBOX,SENT",
        "list_id": None,
    })
    save_snippet(conn, "personal_1", "Hey want to grab lunch?")
    conn.close()

    app = create_app(db_path=db_path)
    app.config["TESTING"] = True
    yield app, db_path


def test_full_review_workflow(full_app):
    app, db_path = full_app
    client = app.test_client()

    # 1. Load patterns — bulk sender should appear
    resp = client.get("/api/patterns")
    patterns = json.loads(resp.data)
    assert len(patterns) >= 1
    bulk = next(p for p in patterns if p["sender_email"] == "newsletter@spam.com")
    assert bulk["count"] == 20

    # 2. Get snippet for bulk sender
    resp = client.get(f"/api/snippet/{bulk['sample_gmail_id']}")
    data = json.loads(resp.data)
    assert "newsletter" in data["snippet"].lower()

    # 3. Trash the bulk sender
    with patch("mailbomb.web.trash_messages", return_value=20) as mock_trash:
        resp = client.post("/api/trash", data=json.dumps({
            "sender_email": "newsletter@spam.com"
        }), content_type="application/json")
        data = json.loads(resp.data)
        assert data["trashed"] == 20

    # 4. Keep the personal sender
    resp = client.post("/api/keep", data=json.dumps({
        "sender_email": "friend@gmail.com"
    }), content_type="application/json")
    assert resp.status_code == 200

    # 5. Patterns should no longer include kept sender
    resp = client.get("/api/patterns")
    patterns = json.loads(resp.data)
    kept_senders = [p["sender_email"] for p in patterns]
    assert "friend@gmail.com" not in kept_senders
```

**Step 2: Run the test**

Run: `.venv/bin/pytest tests/test_review_integration.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/test_review_integration.py
git commit -m "test: integration test for full review triage workflow"
```

---

### Task 10: Update README and Commit All Changes

**Files:**
- Modify: `README.md`

**Step 1: Add review section to README**

In `README.md`, add after the "Check progress" section and before "Typical Workflow":

```markdown
### Review and triage

```bash
mailbomb review
```

Opens a local web interface for smart triage. The tool analyzes your indexed messages, groups them by sender/list, and ranks them by how likely they are to be bulk mail. Each pattern card shows:

- Sender, message count, and total size
- Sample subject lines
- A preview snippet from a representative message
- A bulk likelihood score

**Actions** (voice or keyboard):
- **Toss** (`T`) — move all messages from this sender to trash
- **Keep** (`K`) — mark as reviewed, skip this sender
- **Skip** (`S`) — come back to this later
- **Rule** (`R`) — trash all messages AND create a permanent rule

**Voice:** Click the mic icon to enable voice commands. Say "toss", "keep", "skip", or "rule".

The review server runs on `http://localhost:5000` by default. Use `--port` to change it.
```

**Step 2: Update Future Plans section**

Replace the existing Future Plans section with:

```markdown
## Future Plans

- **Rule auto-apply** — automatically apply saved rules when scanning new messages
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add review command documentation to README"
```

---

Plan complete and saved to `docs/plans/2026-03-29-review-interface.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** — Open a new session with the executing-plans skill, batch execution with checkpoints

Which approach?