import pytest
from unittest.mock import MagicMock, patch, call
from mailbomb.scanner import parse_message_headers, scan_messages


def make_header(name, value):
    return {"name": name, "value": value}


def test_parse_message_headers():
    raw = {
        "id": "msg123",
        "threadId": "thread456",
        "sizeEstimate": 8192,
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "headers": [
                make_header("From", "Jane Doe <jane@example.com>"),
                make_header("Subject", "Re: Meeting notes"),
                make_header("Date", "Tue, 15 Mar 2005 10:30:00 -0500"),
                make_header("List-Id", "<dev.lists.example.com>"),
            ]
        },
    }
    result = parse_message_headers(raw)
    assert result["gmail_id"] == "msg123"
    assert result["thread_id"] == "thread456"
    assert result["sender"] == "Jane Doe <jane@example.com>"
    assert result["sender_email"] == "jane@example.com"
    assert result["subject"] == "Re: Meeting notes"
    assert result["size_bytes"] == 8192
    assert result["list_id"] == "<dev.lists.example.com>"
    assert "INBOX" in result["labels"]


def test_parse_message_headers_no_list_id():
    raw = {
        "id": "msg789",
        "threadId": "thread789",
        "sizeEstimate": 1024,
        "labelIds": [],
        "payload": {
            "headers": [
                make_header("From", "bob@example.com"),
                make_header("Subject", "Hi"),
                make_header("Date", "Mon, 1 Jan 2004 00:00:00 +0000"),
            ]
        },
    }
    result = parse_message_headers(raw)
    assert result["sender_email"] == "bob@example.com"
    assert result["list_id"] is None


def test_parse_email_from_angle_brackets():
    raw = {
        "id": "x",
        "threadId": "t",
        "sizeEstimate": 0,
        "labelIds": [],
        "payload": {
            "headers": [
                make_header("From", "\"Smith, John\" <john.smith@corp.com>"),
                make_header("Subject", ""),
                make_header("Date", ""),
            ]
        },
    }
    result = parse_message_headers(raw)
    assert result["sender_email"] == "john.smith@corp.com"


@patch("mailbomb.scanner.get_gmail_service")
def test_scan_messages_basic(mock_get_service, tmp_path):
    from mailbomb.db import init_db, get_connection, count_messages

    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    mock_service = MagicMock()
    mock_get_service.return_value = mock_service

    # messages.list returns one page with 2 messages
    mock_list = mock_service.users().messages().list
    mock_list.return_value.execute.return_value = {
        "messages": [{"id": "m1"}, {"id": "m2"}],
    }

    # list_next returns None (single page)
    mock_service.users().messages().list_next.return_value = None

    # messages.get returns metadata for each
    def mock_get_side_effect(**kwargs):
        msg_id = kwargs["id"]
        mock_resp = MagicMock()
        mock_resp.execute.return_value = {
            "id": msg_id,
            "threadId": "t1",
            "sizeEstimate": 2048,
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    make_header("From", f"user@example.com"),
                    make_header("Subject", f"Message {msg_id}"),
                    make_header("Date", "Wed, 1 Jun 2005 12:00:00 +0000"),
                ]
            },
        }
        return mock_resp

    mock_service.users().messages().get.side_effect = mock_get_side_effect

    scan_messages(
        query="before:2006/01/01",
        db_path=db_path,
        batch_size=10,
        show_progress=False,
    )

    conn = get_connection(db_path)
    assert count_messages(conn) == 2
    conn.close()
