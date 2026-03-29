import os
import sqlite3
import pytest
from mailbomb.db import init_db, get_connection, upsert_message, get_message, count_messages

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")

def test_init_db_creates_tables(db_path):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert "messages" in tables

def test_init_db_creates_indexes(db_path):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert "idx_sender_email" in indexes
    assert "idx_date" in indexes
    assert "idx_size" in indexes

def test_upsert_and_get_message(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    msg = {
        "gmail_id": "abc123",
        "thread_id": "thread1",
        "sender": "John Doe <john@example.com>",
        "sender_email": "john@example.com",
        "subject": "Hello",
        "date": "2005-03-15T10:30:00Z",
        "size_bytes": 4096,
        "labels": "INBOX,UNREAD",
        "list_id": None,
    }
    upsert_message(conn, msg)
    result = get_message(conn, "abc123")
    assert result["sender_email"] == "john@example.com"
    assert result["size_bytes"] == 4096
    conn.close()

def test_upsert_is_idempotent(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    msg = {
        "gmail_id": "abc123",
        "thread_id": "thread1",
        "sender": "John <john@example.com>",
        "sender_email": "john@example.com",
        "subject": "Hello",
        "date": "2005-03-15T10:30:00Z",
        "size_bytes": 4096,
        "labels": "INBOX",
        "list_id": None,
    }
    upsert_message(conn, msg)
    upsert_message(conn, msg)
    assert count_messages(conn) == 1
    conn.close()

def test_count_messages(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    assert count_messages(conn) == 0
    for i in range(3):
        upsert_message(conn, {
            "gmail_id": f"id{i}",
            "thread_id": f"t{i}",
            "sender": f"user{i}@example.com",
            "sender_email": f"user{i}@example.com",
            "subject": "Test",
            "date": "2005-01-01",
            "size_bytes": 1000,
            "labels": "",
            "list_id": None,
        })
    assert count_messages(conn) == 3
    conn.close()
