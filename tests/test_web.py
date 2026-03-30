import json
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from mailbomb.cli import cli
from mailbomb.db import init_db, get_connection, upsert_message
from mailbomb.snippets import save_snippet
from mailbomb.web import create_app


def test_review_command_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["review", "--help"])
    assert result.exit_code == 0
    assert "review" in result.output.lower()


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


def test_api_session_trashed_empty(client):
    response = client.get("/api/session-trashed")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data == []


def test_api_session_trashed_after_trash(client):
    with patch("mailbomb.web.trash_messages", return_value=10):
        client.post(
            "/api/trash",
            data=json.dumps({"sender_email": "deals@spam.com"}),
            content_type="application/json",
        )
    response = client.get("/api/session-trashed")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) == 10
    assert all(m["sender_email"] == "deals@spam.com" for m in data)


def test_api_untrash(client):
    with patch("mailbomb.web.untrash_messages", return_value=1) as mock_untrash:
        response = client.post(
            "/api/untrash",
            data=json.dumps({"gmail_ids": ["spam_0"]}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["restored"] == 1


def test_api_untrash_requires_ids(client):
    response = client.post(
        "/api/untrash",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_api_diverse_samples(client):
    """Diverse samples returns messages with distinct subjects."""
    with patch("mailbomb.web.get_gmail_service") as mock_svc:
        mock_gmail = MagicMock()
        mock_svc.return_value = mock_gmail
        mock_gmail.users().messages().get().execute.return_value = {
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": "SGVsbG8gV29ybGQ="},
            }
        }
        response = client.get("/api/diverse-samples/deals@spam.com")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data) >= 1
        assert "body" in data[0]
        assert "subject" in data[0]


def test_api_fullmessage(client):
    """Full message endpoint returns full body text."""
    with patch("mailbomb.web.get_gmail_service") as mock_svc:
        mock_gmail = MagicMock()
        mock_svc.return_value = mock_gmail
        mock_gmail.users().messages().get().execute.return_value = {
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": "SGVsbG8gV29ybGQ="},
            }
        }
        response = client.get("/api/fullmessage/spam_0")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "Hello World" in data["body"]


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
