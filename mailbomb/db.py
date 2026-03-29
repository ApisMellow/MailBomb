import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".mailbomb" / "mailbomb.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    gmail_id    TEXT PRIMARY KEY,
    thread_id   TEXT,
    sender      TEXT,
    sender_email TEXT,
    subject     TEXT,
    date        TEXT,
    size_bytes  INTEGER,
    labels      TEXT,
    list_id     TEXT,
    deleted     BOOLEAN DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sender_email ON messages(sender_email);
CREATE INDEX IF NOT EXISTS idx_date ON messages(date);
CREATE INDEX IF NOT EXISTS idx_size ON messages(size_bytes);

CREATE TABLE IF NOT EXISTS snippets (
    gmail_id    TEXT PRIMARY KEY,
    body_preview TEXT,
    FOREIGN KEY (gmail_id) REFERENCES messages(gmail_id)
);

CREATE TABLE IF NOT EXISTS rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_email TEXT,
    list_id      TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rule_sender
ON rules(sender_email) WHERE sender_email IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_rule_list
ON rules(list_id) WHERE list_id IS NOT NULL;
"""


def init_db(db_path=None):
    """Initialize the database, creating tables and indexes."""
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def get_connection(db_path=None):
    """Get a connection to the database."""
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def upsert_message(conn, msg):
    """Insert or replace a message in the database."""
    conn.execute(
        """INSERT OR REPLACE INTO messages
           (gmail_id, thread_id, sender, sender_email, subject, date, size_bytes, labels, list_id)
           VALUES (:gmail_id, :thread_id, :sender, :sender_email, :subject, :date, :size_bytes, :labels, :list_id)""",
        msg,
    )
    conn.commit()


def get_message(conn, gmail_id):
    """Get a single message by Gmail ID."""
    row = conn.execute("SELECT * FROM messages WHERE gmail_id = ?", (gmail_id,)).fetchone()
    return dict(row) if row else None


def count_messages(conn, include_deleted=False):
    """Count messages in the database."""
    if include_deleted:
        row = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM messages WHERE deleted = 0").fetchone()
    return row[0]
