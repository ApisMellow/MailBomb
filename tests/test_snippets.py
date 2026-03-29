import base64
from unittest.mock import MagicMock

import pytest
from mailbomb.db import init_db, get_connection, upsert_message
from mailbomb.snippets import get_snippet, save_snippet, extract_plaintext, fetch_and_cache_snippet


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
    html = "<html><body><p>Hello <b>World</b></p></body></html>"
    encoded = base64.urlsafe_b64encode(html.encode()).decode()
    parts = [{"mimeType": "text/html", "body": {"data": encoded}}]
    result = extract_plaintext(parts)
    assert "Hello" in result
    assert "<b>" not in result


def test_extract_plaintext_multipart():
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


def test_extract_plaintext_nested_multipart():
    """multipart/mixed -> [multipart/alternative -> [text/plain, text/html], application/pdf]"""
    plain_data = base64.urlsafe_b64encode(b"Nested plain text").decode()
    html_data = base64.urlsafe_b64encode(b"<p>Nested html</p>").decode()
    parts = [
        {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": plain_data}},
                {"mimeType": "text/html", "body": {"data": html_data}},
            ],
        },
        {
            "mimeType": "application/pdf",
            "body": {"data": ""},
        },
    ]
    result = extract_plaintext(parts)
    assert result == "Nested plain text"


def test_fetch_and_cache_snippet_cache_hit(db_with_messages):
    """Cache hit returns stored value without making an API call."""
    conn, db_path = db_with_messages
    save_snippet(conn, "abc123", "cached body")

    service = MagicMock()
    result = fetch_and_cache_snippet(service, conn, "abc123")

    assert result == "cached body"
    service.users.assert_not_called()


def test_fetch_and_cache_snippet_cache_miss(db_with_messages):
    """Cache miss fetches from API, truncates, and stores."""
    conn, db_path = db_with_messages
    long_text = "A" * 500
    encoded = base64.urlsafe_b64encode(long_text.encode()).decode()

    service = MagicMock()
    service.users().messages().get().execute.return_value = {
        "payload": {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": encoded}},
            ],
        }
    }

    result = fetch_and_cache_snippet(service, conn, "msg_new", max_chars=300)

    assert result == "A" * 300
    assert get_snippet(conn, "msg_new") == "A" * 300


def test_fetch_and_cache_snippet_single_part(db_with_messages):
    """Single-part message with body directly on payload."""
    conn, db_path = db_with_messages
    encoded = base64.urlsafe_b64encode(b"Single part body").decode()

    service = MagicMock()
    service.users().messages().get().execute.return_value = {
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": encoded},
        }
    }

    result = fetch_and_cache_snippet(service, conn, "msg_single")

    assert result == "Single part body"
    assert get_snippet(conn, "msg_single") == "Single part body"
