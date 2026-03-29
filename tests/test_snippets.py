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
