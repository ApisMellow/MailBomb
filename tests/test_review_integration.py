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
