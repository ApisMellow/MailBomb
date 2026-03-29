import pytest
from mailbomb.db import init_db, get_connection, upsert_message
from mailbomb.analyzer import (
    top_senders_by_count,
    top_senders_by_size,
    mailing_lists,
    breakdown_by_year,
    total_size,
)


@pytest.fixture
def populated_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)

    messages = [
        {"gmail_id": "1", "thread_id": "t1", "sender": "spam@deals.com", "sender_email": "spam@deals.com", "subject": "Deal!", "date": "2005-01-10", "size_bytes": 50000, "labels": "INBOX", "list_id": None},
        {"gmail_id": "2", "thread_id": "t2", "sender": "spam@deals.com", "sender_email": "spam@deals.com", "subject": "Deal 2!", "date": "2005-03-15", "size_bytes": 50000, "labels": "INBOX", "list_id": None},
        {"gmail_id": "3", "thread_id": "t3", "sender": "spam@deals.com", "sender_email": "spam@deals.com", "subject": "Deal 3!", "date": "2006-06-01", "size_bytes": 50000, "labels": "INBOX", "list_id": None},
        {"gmail_id": "4", "thread_id": "t4", "sender": "friend@gmail.com", "sender_email": "friend@gmail.com", "subject": "Hey", "date": "2005-07-20", "size_bytes": 1000, "labels": "INBOX", "list_id": None},
        {"gmail_id": "5", "thread_id": "t5", "sender": "list@dev.example.com", "sender_email": "list@dev.example.com", "subject": "Digest", "date": "2005-11-01", "size_bytes": 20000, "labels": "INBOX", "list_id": "<dev.example.com>"},
        {"gmail_id": "6", "thread_id": "t6", "sender": "list@dev.example.com", "sender_email": "list@dev.example.com", "subject": "Digest 2", "date": "2005-12-01", "size_bytes": 25000, "labels": "INBOX", "list_id": "<dev.example.com>"},
        {"gmail_id": "7", "thread_id": "t7", "sender": "bigfile@corp.com", "sender_email": "bigfile@corp.com", "subject": "Attachment", "date": "2006-02-01", "size_bytes": 5000000, "labels": "INBOX", "list_id": None},
    ]
    for msg in messages:
        upsert_message(conn, msg)

    yield conn
    conn.close()


def test_top_senders_by_count(populated_db):
    result = top_senders_by_count(populated_db, limit=3)
    assert result[0]["sender_email"] == "spam@deals.com"
    assert result[0]["count"] == 3


def test_top_senders_by_size(populated_db):
    result = top_senders_by_size(populated_db, limit=3)
    assert result[0]["sender_email"] == "bigfile@corp.com"
    assert result[0]["total_size"] == 5000000


def test_mailing_lists(populated_db):
    result = mailing_lists(populated_db)
    assert len(result) == 1
    assert result[0]["list_id"] == "<dev.example.com>"
    assert result[0]["count"] == 2


def test_breakdown_by_year(populated_db):
    result = breakdown_by_year(populated_db)
    years = {r["year"]: r["count"] for r in result}
    assert years["2005"] == 5
    assert years["2006"] == 2


def test_total_size(populated_db):
    result = total_size(populated_db)
    assert result == 5196000
