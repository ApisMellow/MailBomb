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


def test_api_trash_requires_sender(client):
    response = client.post(
        "/api/trash",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_api_rule_requires_sender(client):
    response = client.post(
        "/api/rule",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 400


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
