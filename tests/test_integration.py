"""Integration test: scan → analyze → delete workflow with mocked Gmail API."""
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from mailbomb.cli import cli
from mailbomb.db import init_db, get_connection, count_messages


def make_gmail_message(msg_id, sender, subject, date, size=1024, list_id=None):
    headers = [
        {"name": "From", "value": sender},
        {"name": "Subject", "value": subject},
        {"name": "Date", "value": date},
    ]
    if list_id:
        headers.append({"name": "List-Id", "value": list_id})
    return {
        "id": msg_id,
        "threadId": f"t_{msg_id}",
        "sizeEstimate": size,
        "labelIds": ["INBOX"],
        "payload": {"headers": headers},
    }


FAKE_MESSAGES = [
    make_gmail_message("m1", "spam@deals.com", "Buy now!", "2005-01-01", 5000),
    make_gmail_message("m2", "spam@deals.com", "Sale!", "2005-02-01", 5000),
    make_gmail_message("m3", "spam@deals.com", "Offer!", "2005-03-01", 5000),
    make_gmail_message("m4", "friend@gmail.com", "Hey!", "2005-04-01", 1000),
    make_gmail_message("m5", "list@dev.org", "Digest", "2005-05-01", 2000, "<dev.org>"),
]


@patch("mailbomb.scanner.get_gmail_service")
@patch("mailbomb.executor.get_gmail_service")
def test_full_workflow(mock_exec_service, mock_scan_service, tmp_path):
    db_path = str(tmp_path / "test.db")

    # Mock scanner's Gmail service
    mock_svc = MagicMock()
    mock_scan_service.return_value = mock_svc

    mock_list = mock_svc.users().messages().list
    mock_list.return_value.execute.return_value = {
        "messages": [{"id": m["id"]} for m in FAKE_MESSAGES],
    }
    # list_next is called on service.users().messages(), not on list's return value
    mock_svc.users().messages().list_next.return_value = None

    def mock_get(**kwargs):
        msg = next(m for m in FAKE_MESSAGES if m["id"] == kwargs["id"])
        resp = MagicMock()
        resp.execute.return_value = msg
        return resp

    mock_svc.users().messages().get.side_effect = mock_get

    # Run scan
    from mailbomb.scanner import scan_messages
    result = scan_messages(query="before:2006/01/01", db_path=db_path, show_progress=False)
    assert result["fetched"] == 5

    # Verify analysis
    conn = get_connection(db_path)
    from mailbomb.analyzer import top_senders_by_count
    top = top_senders_by_count(conn, limit=1)
    assert top[0]["sender_email"] == "spam@deals.com"
    assert top[0]["count"] == 3

    # Delete spam sender
    from mailbomb.executor import resolve_message_ids, delete_messages
    ids = resolve_message_ids(conn, sender_email="spam@deals.com")
    assert len(ids) == 3
    conn.close()

    # Mock executor's Gmail service
    mock_exec = MagicMock()
    mock_exec_service.return_value = mock_exec
    mock_exec.users().messages().batchDelete.return_value.execute.return_value = {}

    deleted = delete_messages(ids, db_path=db_path)
    assert deleted == 3

    # Verify state
    conn = get_connection(db_path)
    assert count_messages(conn, include_deleted=False) == 2
    assert count_messages(conn, include_deleted=True) == 5
    conn.close()
