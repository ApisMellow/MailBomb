import pytest
from unittest.mock import MagicMock, patch, call
from mailbomb.db import init_db, get_connection, upsert_message, get_message
from mailbomb.executor import delete_messages, resolve_message_ids


@pytest.fixture
def populated_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    for i in range(5):
        upsert_message(conn, {
            "gmail_id": f"msg{i}",
            "thread_id": f"t{i}",
            "sender": "spam@example.com",
            "sender_email": "spam@example.com",
            "subject": f"Spam {i}",
            "date": "2005-01-01",
            "size_bytes": 1000,
            "labels": "INBOX",
            "list_id": None,
        })
    yield db_path
    conn.close()


def test_resolve_by_sender(populated_db):
    conn = get_connection(populated_db)
    ids = resolve_message_ids(conn, sender_email="spam@example.com")
    assert len(ids) == 5
    conn.close()


def test_resolve_no_match(populated_db):
    conn = get_connection(populated_db)
    ids = resolve_message_ids(conn, sender_email="nobody@example.com")
    assert len(ids) == 0
    conn.close()


@patch("mailbomb.executor.get_gmail_service")
def test_delete_messages_calls_api(mock_get_service, populated_db):
    mock_service = MagicMock()
    mock_get_service.return_value = mock_service
    mock_service.users().messages().batchDelete.return_value.execute.return_value = {}

    conn = get_connection(populated_db)
    ids = [f"msg{i}" for i in range(5)]
    deleted = delete_messages(ids, db_path=populated_db)

    mock_service.users().messages().batchDelete.assert_called_once_with(
        userId="me", body={"ids": ids}
    )
    assert deleted == 5

    # Check marked as deleted in DB
    msg = get_message(conn, "msg0")
    assert msg["deleted"] == 1
    conn.close()
