# MailBomb Core Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Build a Python CLI tool that prunes massive Gmail mailboxes by scanning oldest-first via the Gmail API, building a local SQLite metadata index, analyzing patterns, and executing batch deletions.

**Architecture:** Modular Python package with separate modules for auth, scanning, analysis, deletion, and database. Gmail API accessed via `google-api-python-client` with OAuth2 desktop flow. All message metadata stored in SQLite for offline analysis. CLI built with Click, output formatted with Rich.

**Tech Stack:** Python 3.14, google-api-python-client, google-auth-oauthlib, Click, Rich, SQLite3

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `mailbomb/__init__.py`
- Create: `mailbomb/cli.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "mailbomb"
version = "0.1.0"
description = "Prune massive Gmail mailboxes"
requires-python = ">=3.10"
dependencies = [
    "google-api-python-client>=2.100.0",
    "google-auth-oauthlib>=1.0.0",
    "click>=8.1.0",
    "rich>=13.0.0",
]

[project.scripts]
mailbomb = "mailbomb.cli:cli"

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"
```

**Step 2: Create mailbomb/__init__.py**

```python
"""MailBomb — prune massive Gmail mailboxes."""
```

**Step 3: Create minimal cli.py**

```python
import click

@click.group()
def cli():
    """MailBomb — prune massive Gmail mailboxes."""
    pass

if __name__ == "__main__":
    cli()
```

**Step 4: Install in editable mode and verify**

Run: `cd /Users/david/dev/MailBomb && pip install -e .`
Then: `mailbomb --help`
Expected: Shows help text with "MailBomb — prune massive Gmail mailboxes."

**Step 5: Commit**

```bash
git init
git add pyproject.toml mailbomb/__init__.py mailbomb/cli.py
git commit -m "feat: project scaffolding with Click CLI entry point"
```

---

### Task 2: Database Module

**Files:**
- Create: `mailbomb/db.py`
- Create: `tests/test_db.py`

**Step 1: Write the failing tests**

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_db.py -v`
Expected: FAIL with "ModuleNotFoundError" or "ImportError"

**Step 3: Write the implementation**

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_db.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add mailbomb/db.py tests/test_db.py
git commit -m "feat: SQLite database module with schema, upsert, and query helpers"
```

---

### Task 3: Auth Module

**Files:**
- Create: `mailbomb/auth.py`
- Create: `tests/test_auth.py`

**Step 1: Write the failing tests**

```python
import json
import os
import pytest
from unittest.mock import patch, MagicMock
from mailbomb.auth import (
    get_credentials_path,
    get_token_path,
    get_gmail_service,
    SCOPES,
)


def test_scopes_include_modify():
    assert "https://mail.google.com/" in SCOPES


def test_credentials_path_default():
    path = get_credentials_path()
    assert path.name == "credentials.json"
    assert ".mailbomb" in str(path)


def test_token_path_default():
    path = get_token_path()
    assert path.name == "token.json"
    assert ".mailbomb" in str(path)


@patch("mailbomb.auth.build")
@patch("mailbomb.auth.Credentials")
def test_get_gmail_service_with_valid_token(mock_creds_class, mock_build, tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text("{}")

    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds_class.from_authorized_user_file.return_value = mock_creds

    mock_service = MagicMock()
    mock_build.return_value = mock_service

    service = get_gmail_service(token_path=token_path, credentials_path=tmp_path / "creds.json")
    assert service == mock_service
    mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_auth.py -v`
Expected: FAIL with ImportError

**Step 3: Write the implementation**

```python
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://mail.google.com/"]

CONFIG_DIR = Path.home() / ".mailbomb"


def get_credentials_path():
    return CONFIG_DIR / "credentials.json"


def get_token_path():
    return CONFIG_DIR / "token.json"


def get_gmail_service(token_path=None, credentials_path=None):
    """Build and return an authenticated Gmail API service."""
    token_path = Path(token_path) if token_path else get_token_path()
    credentials_path = Path(credentials_path) if credentials_path else get_credentials_path()

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"No credentials.json found at {credentials_path}. "
                    "Run 'mailbomb setup' first."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_auth.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add mailbomb/auth.py tests/test_auth.py
git commit -m "feat: OAuth2 auth module with token caching and Gmail service builder"
```

---

### Task 4: Setup CLI Command

**Files:**
- Modify: `mailbomb/cli.py`
- Create: `tests/test_cli_setup.py`

**Step 1: Write the failing test**

```python
import os
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from mailbomb.cli import cli


def test_setup_no_credentials_file(tmp_path):
    runner = CliRunner()
    with patch("mailbomb.cli.get_credentials_path", return_value=tmp_path / "credentials.json"):
        with patch("mailbomb.cli.webbrowser") as mock_wb:
            result = runner.invoke(cli, ["setup"], input="n\n")
            assert "credentials.json" in result.output


def test_setup_with_credentials_file(tmp_path):
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text('{"installed": {}}')
    token_path = tmp_path / "token.json"

    runner = CliRunner()
    with patch("mailbomb.cli.get_credentials_path", return_value=creds_path):
        with patch("mailbomb.cli.get_token_path", return_value=token_path):
            with patch("mailbomb.cli.get_gmail_service") as mock_service:
                mock_svc = MagicMock()
                mock_svc.users().getProfile().execute.return_value = {
                    "emailAddress": "test@gmail.com",
                    "messagesTotal": 500000,
                }
                mock_service.return_value = mock_svc
                result = runner.invoke(cli, ["setup"])
                assert "test@gmail.com" in result.output or result.exit_code == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_cli_setup.py -v`
Expected: FAIL

**Step 3: Update cli.py with setup command**

```python
import webbrowser
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from mailbomb.auth import get_credentials_path, get_token_path, get_gmail_service
from mailbomb.db import init_db

console = Console()


@click.group()
def cli():
    """MailBomb — prune massive Gmail mailboxes."""
    pass


@cli.command()
def setup():
    """Set up Gmail API credentials and authenticate."""
    console.print(Panel("MailBomb Setup", style="bold blue"))

    credentials_path = get_credentials_path()
    token_path = get_token_path()

    if not credentials_path.exists():
        console.print("\n[bold]Step 1:[/bold] Create Google Cloud OAuth credentials\n")
        console.print("1. Go to [link]https://console.cloud.google.com/apis/credentials[/link]")
        console.print("2. Create a project (or select existing)")
        console.print("3. Enable the Gmail API at [link]https://console.cloud.google.com/apis/library/gmail.googleapis.com[/link]")
        console.print("4. Go to Credentials → Create Credentials → OAuth client ID")
        console.print("5. Application type: Desktop app")
        console.print("6. Download the JSON file")
        console.print(f"7. Save it as: [bold]{credentials_path}[/bold]\n")

        if click.confirm("Open Google Cloud Console in your browser?"):
            webbrowser.open("https://console.cloud.google.com/apis/credentials")

        click.pause("Press any key once you've saved credentials.json...")

        if not credentials_path.exists():
            console.print(f"\n[red]credentials.json not found at {credentials_path}[/red]")
            console.print("Please save the file and run 'mailbomb setup' again.")
            raise SystemExit(1)

    console.print("\n[bold]Authenticating with Gmail...[/bold]")
    service = get_gmail_service(token_path=token_path, credentials_path=credentials_path)

    profile = service.users().getProfile(userId="me").execute()
    email = profile.get("emailAddress", "unknown")
    total = profile.get("messagesTotal", 0)

    console.print(f"\n[green]✓ Authenticated as {email}[/green]")
    console.print(f"  Total messages: {total:,}")

    init_db()
    console.print("[green]✓ Database initialized[/green]")
    console.print("\n[bold]Setup complete![/bold] Run [bold]mailbomb scan --help[/bold] to get started.")


if __name__ == "__main__":
    cli()
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_cli_setup.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add mailbomb/cli.py tests/test_cli_setup.py
git commit -m "feat: setup command with OAuth walkthrough and profile check"
```

---

### Task 5: Scanner Module

**Files:**
- Create: `mailbomb/scanner.py`
- Create: `tests/test_scanner.py`

**Step 1: Write the failing tests**

```python
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
    mock_list.return_value.list_next.return_value = None

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
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_scanner.py -v`
Expected: FAIL with ImportError

**Step 3: Write the implementation**

```python
import re
from email.utils import parsedate_to_datetime

from mailbomb.auth import get_gmail_service
from mailbomb.db import get_connection, upsert_message, init_db


def extract_email(from_header):
    """Extract email address from a From header value."""
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).lower()
    # Bare email address
    match = re.search(r"[\w.\-+]+@[\w.\-]+", from_header)
    if match:
        return match.group(0).lower()
    return from_header.lower()


def parse_message_headers(raw):
    """Parse a Gmail API message resource (format=metadata) into a flat dict."""
    headers = {h["name"].lower(): h["value"] for h in raw["payload"]["headers"]}

    return {
        "gmail_id": raw["id"],
        "thread_id": raw.get("threadId", ""),
        "sender": headers.get("from", ""),
        "sender_email": extract_email(headers.get("from", "")),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "size_bytes": raw.get("sizeEstimate", 0),
        "labels": ",".join(raw.get("labelIds", [])),
        "list_id": headers.get("list-id"),
    }


def scan_messages(query, db_path=None, batch_size=100, show_progress=True):
    """Scan Gmail messages matching query and store metadata in SQLite.

    Args:
        query: Gmail search query (e.g., "before:2006/01/01")
        db_path: Path to SQLite database
        batch_size: Number of message IDs to fetch per page
        show_progress: Whether to show a Rich progress bar
    """
    service = get_gmail_service()
    init_db(db_path)
    conn = get_connection(db_path)

    progress = None
    if show_progress:
        from rich.progress import Progress
        progress = Progress()
        progress.start()
        task = progress.add_task("Scanning...", total=None)

    try:
        fetched = 0
        skipped = 0
        request = service.users().messages().list(
            userId="me", q=query, maxResults=batch_size
        )

        while request is not None:
            response = request.execute()
            messages = response.get("messages", [])

            if not messages:
                break

            for msg_stub in messages:
                msg_id = msg_stub["id"]

                # Skip if already in DB (resumable)
                existing = conn.execute(
                    "SELECT gmail_id FROM messages WHERE gmail_id = ?", (msg_id,)
                ).fetchone()
                if existing:
                    skipped += 1
                    continue

                # Fetch metadata
                msg = service.users().messages().get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["From", "Subject", "Date", "List-Id"],
                ).execute()

                parsed = parse_message_headers(msg)
                upsert_message(conn, parsed)
                fetched += 1

                if progress:
                    progress.update(task, advance=1, description=f"Scanned {fetched} (skipped {skipped})")

            request = service.users().messages().list_next(request, response)

    finally:
        if progress:
            progress.stop()
        conn.close()

    return {"fetched": fetched, "skipped": skipped}
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_scanner.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add mailbomb/scanner.py tests/test_scanner.py
git commit -m "feat: scanner module — date-windowed metadata fetch into SQLite"
```

---

### Task 6: Scan CLI Command

**Files:**
- Modify: `mailbomb/cli.py`
- Create: `tests/test_cli_scan.py`

**Step 1: Write the failing test**

```python
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from mailbomb.cli import cli


@patch("mailbomb.cli.scan_messages")
def test_scan_command_builds_query(mock_scan):
    mock_scan.return_value = {"fetched": 42, "skipped": 3}
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", "--before", "2006-01-01", "--after", "2004-01-01"])
    assert result.exit_code == 0
    call_args = mock_scan.call_args
    query = call_args[1].get("query") or call_args[0][0]
    assert "before:2006/01/01" in query
    assert "after:2004/01/01" in query


@patch("mailbomb.cli.scan_messages")
def test_scan_command_before_only(mock_scan):
    mock_scan.return_value = {"fetched": 10, "skipped": 0}
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", "--before", "2006-01-01"])
    assert result.exit_code == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_cli_scan.py -v`
Expected: FAIL

**Step 3: Add scan command to cli.py**

Add these imports at the top of cli.py:
```python
from mailbomb.scanner import scan_messages
```

Add this command after the `setup` command:
```python
@cli.command()
@click.option("--before", required=True, help="Scan messages before this date (YYYY-MM-DD)")
@click.option("--after", default=None, help="Scan messages after this date (YYYY-MM-DD)")
@click.option("--batch-size", default=100, help="Messages per API page (max 500)")
def scan(before, after, batch_size):
    """Scan Gmail and index message metadata locally."""
    query_parts = []
    if before:
        query_parts.append(f"before:{before.replace('-', '/')}")
    if after:
        query_parts.append(f"after:{after.replace('-', '/')}")

    query = " ".join(query_parts)
    console.print(f"[bold]Scanning:[/bold] {query}")

    result = scan_messages(query=query, batch_size=batch_size)

    console.print(f"\n[green]✓ Done![/green] Fetched {result['fetched']:,} new, skipped {result['skipped']:,} existing")
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_cli_scan.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add mailbomb/cli.py tests/test_cli_scan.py
git commit -m "feat: scan CLI command with date range options"
```

---

### Task 7: Analyzer Module

**Files:**
- Create: `mailbomb/analyzer.py`
- Create: `tests/test_analyzer.py`

**Step 1: Write the failing tests**

```python
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
    assert years["2005"] == 4
    assert years["2006"] == 2


def test_total_size(populated_db):
    result = total_size(populated_db)
    assert result == 5196000
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_analyzer.py -v`
Expected: FAIL with ImportError

**Step 3: Write the implementation**

```python
def top_senders_by_count(conn, limit=20):
    """Return top senders ranked by message count."""
    rows = conn.execute(
        """SELECT sender_email, COUNT(*) as count
           FROM messages WHERE deleted = 0
           GROUP BY sender_email
           ORDER BY count DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def top_senders_by_size(conn, limit=20):
    """Return top senders ranked by total message size."""
    rows = conn.execute(
        """SELECT sender_email, SUM(size_bytes) as total_size, COUNT(*) as count
           FROM messages WHERE deleted = 0
           GROUP BY sender_email
           ORDER BY total_size DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def mailing_lists(conn):
    """Return detected mailing lists with message counts."""
    rows = conn.execute(
        """SELECT list_id, COUNT(*) as count, SUM(size_bytes) as total_size
           FROM messages
           WHERE deleted = 0 AND list_id IS NOT NULL
           GROUP BY list_id
           ORDER BY count DESC""",
    ).fetchall()
    return [dict(r) for r in rows]


def breakdown_by_year(conn):
    """Return message count and size by year."""
    rows = conn.execute(
        """SELECT SUBSTR(date, 1, 4) as year, COUNT(*) as count, SUM(size_bytes) as total_size
           FROM messages WHERE deleted = 0
           GROUP BY year
           ORDER BY year""",
    ).fetchall()
    return [dict(r) for r in rows]


def total_size(conn):
    """Return total size of all non-deleted messages in bytes."""
    row = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) FROM messages WHERE deleted = 0"
    ).fetchone()
    return row[0]
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_analyzer.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add mailbomb/analyzer.py tests/test_analyzer.py
git commit -m "feat: analyzer module — top senders, mailing lists, year breakdown"
```

---

### Task 8: Analyze CLI Command

**Files:**
- Modify: `mailbomb/cli.py`

**Step 1: Add the analyze command**

Add import at top of cli.py:
```python
from mailbomb.analyzer import top_senders_by_count, top_senders_by_size, mailing_lists, breakdown_by_year, total_size
```

Add command:
```python
@cli.command()
@click.option("--before", default=None, help="Filter messages before this date")
@click.option("--after", default=None, help="Filter messages after this date")
@click.option("--top", default=20, help="Number of top entries to show")
def analyze(before, after, top):
    """Analyze scanned message metadata for patterns."""
    from rich.table import Table
    from mailbomb.db import get_connection

    conn = get_connection()

    # Top senders by count
    console.print("\n[bold]Top Senders by Message Count:[/bold]")
    table = Table()
    table.add_column("Sender", style="cyan")
    table.add_column("Count", justify="right")
    for row in top_senders_by_count(conn, limit=top):
        table.add_row(row["sender_email"], f"{row['count']:,}")
    console.print(table)

    # Top senders by size
    console.print("\n[bold]Top Senders by Total Size:[/bold]")
    table = Table()
    table.add_column("Sender", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Count", justify="right")
    for row in top_senders_by_size(conn, limit=top):
        size_mb = row["total_size"] / (1024 * 1024)
        table.add_row(row["sender_email"], f"{size_mb:.1f} MB", f"{row['count']:,}")
    console.print(table)

    # Mailing lists
    lists = mailing_lists(conn)
    if lists:
        console.print("\n[bold]Mailing Lists:[/bold]")
        table = Table()
        table.add_column("List-Id", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Size", justify="right")
        for row in lists:
            size_mb = row["total_size"] / (1024 * 1024)
            table.add_row(row["list_id"], f"{row['count']:,}", f"{size_mb:.1f} MB")
        console.print(table)

    # Year breakdown
    console.print("\n[bold]Messages by Year:[/bold]")
    table = Table()
    table.add_column("Year", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Size", justify="right")
    for row in breakdown_by_year(conn):
        size_mb = (row["total_size"] or 0) / (1024 * 1024)
        table.add_row(row["year"], f"{row['count']:,}", f"{size_mb:.1f} MB")
    console.print(table)

    # Total
    total = total_size(conn)
    console.print(f"\n[bold]Total indexed:[/bold] {total / (1024*1024):.1f} MB")
    conn.close()
```

**Step 2: Verify it loads**

Run: `cd /Users/david/dev/MailBomb && mailbomb analyze --help`
Expected: Shows help with options

**Step 3: Commit**

```bash
git add mailbomb/cli.py
git commit -m "feat: analyze command with Rich table output"
```

---

### Task 9: Executor Module

**Files:**
- Create: `mailbomb/executor.py`
- Create: `tests/test_executor.py`

**Step 1: Write the failing tests**

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_executor.py -v`
Expected: FAIL

**Step 3: Write the implementation**

```python
from mailbomb.auth import get_gmail_service
from mailbomb.db import get_connection, init_db


def resolve_message_ids(conn, sender_email=None, list_id=None, before=None, after=None, min_size=None):
    """Resolve filter criteria to a list of Gmail message IDs."""
    conditions = ["deleted = 0"]
    params = []

    if sender_email:
        conditions.append("sender_email = ?")
        params.append(sender_email)
    if list_id:
        conditions.append("list_id = ?")
        params.append(list_id)
    if before:
        conditions.append("date < ?")
        params.append(before)
    if after:
        conditions.append("date > ?")
        params.append(after)
    if min_size:
        conditions.append("size_bytes >= ?")
        params.append(min_size)

    where = " AND ".join(conditions)
    rows = conn.execute(f"SELECT gmail_id FROM messages WHERE {where}", params).fetchall()
    return [row[0] for row in rows]


def delete_messages(gmail_ids, db_path=None, batch_size=1000):
    """Delete messages from Gmail and mark them deleted in the local DB.

    Gmail's batchDelete accepts up to 1000 IDs per call.
    """
    if not gmail_ids:
        return 0

    service = get_gmail_service()
    conn = get_connection(db_path)
    total_deleted = 0

    for i in range(0, len(gmail_ids), batch_size):
        batch = gmail_ids[i : i + batch_size]
        service.users().messages().batchDelete(
            userId="me", body={"ids": batch}
        ).execute()

        # Mark as deleted in local DB
        placeholders = ",".join("?" for _ in batch)
        conn.execute(
            f"UPDATE messages SET deleted = 1 WHERE gmail_id IN ({placeholders})",
            batch,
        )
        conn.commit()
        total_deleted += len(batch)

    conn.close()
    return total_deleted
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/test_executor.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add mailbomb/executor.py tests/test_executor.py
git commit -m "feat: executor module — batch delete via Gmail API with local tracking"
```

---

### Task 10: Delete CLI Command

**Files:**
- Modify: `mailbomb/cli.py`

**Step 1: Add delete command**

Add import:
```python
from mailbomb.executor import delete_messages, resolve_message_ids
```

Add command:
```python
@cli.command()
@click.option("--sender", default=None, help="Delete all messages from this sender email")
@click.option("--list-id", default=None, help="Delete all messages with this List-Id")
@click.option("--before", default=None, help="Delete messages before this date")
@click.option("--after", default=None, help="Delete messages after this date")
@click.option("--min-size", default=None, help="Delete messages larger than this (e.g., 5MB)")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without deleting")
def delete(sender, list_id, before, after, min_size, dry_run):
    """Delete messages matching the given filters."""
    from rich.table import Table
    from mailbomb.db import get_connection

    if not any([sender, list_id, before, min_size]):
        console.print("[red]Specify at least one filter (--sender, --list-id, --before, --min-size)[/red]")
        raise SystemExit(1)

    # Parse min_size like "5MB" to bytes
    size_bytes = None
    if min_size:
        min_size = min_size.upper()
        if min_size.endswith("MB"):
            size_bytes = int(float(min_size[:-2]) * 1024 * 1024)
        elif min_size.endswith("KB"):
            size_bytes = int(float(min_size[:-2]) * 1024)
        elif min_size.endswith("GB"):
            size_bytes = int(float(min_size[:-2]) * 1024 * 1024 * 1024)
        else:
            size_bytes = int(min_size)

    conn = get_connection()
    ids = resolve_message_ids(
        conn,
        sender_email=sender,
        list_id=list_id,
        before=before,
        after=after,
        min_size=size_bytes,
    )

    if not ids:
        console.print("[yellow]No matching messages found.[/yellow]")
        conn.close()
        return

    # Show summary
    total_size_bytes = conn.execute(
        f"SELECT COALESCE(SUM(size_bytes), 0) FROM messages WHERE gmail_id IN ({','.join('?' for _ in ids)})",
        ids,
    ).fetchone()[0]

    console.print(f"\n[bold]Messages to delete:[/bold] {len(ids):,}")
    console.print(f"[bold]Space to reclaim:[/bold] {total_size_bytes / (1024*1024):.1f} MB")

    if dry_run:
        console.print("\n[yellow]Dry run — no messages deleted.[/yellow]")
        conn.close()
        return

    if not click.confirm(f"\nPermanently delete {len(ids):,} messages?"):
        console.print("Cancelled.")
        conn.close()
        return

    conn.close()
    deleted = delete_messages(ids)
    console.print(f"\n[green]✓ Deleted {deleted:,} messages[/green]")
```

**Step 2: Verify it loads**

Run: `cd /Users/david/dev/MailBomb && mailbomb delete --help`
Expected: Shows help with all filter options

**Step 3: Commit**

```bash
git add mailbomb/cli.py
git commit -m "feat: delete command with filters, dry-run, and confirmation prompt"
```

---

### Task 11: Stats CLI Command

**Files:**
- Modify: `mailbomb/cli.py`

**Step 1: Add stats command**

```python
@cli.command()
def stats():
    """Show scanning and deletion progress."""
    from mailbomb.db import get_connection, count_messages

    conn = get_connection()

    total = count_messages(conn, include_deleted=True)
    active = count_messages(conn, include_deleted=False)
    deleted = total - active

    active_size = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) FROM messages WHERE deleted = 0"
    ).fetchone()[0]
    deleted_size = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) FROM messages WHERE deleted = 1"
    ).fetchone()[0]

    console.print(f"\n[bold]MailBomb Stats[/bold]")
    console.print(f"  Messages scanned:  {total:,}")
    console.print(f"  Active (kept):     {active:,} ({active_size / (1024*1024):.1f} MB)")
    console.print(f"  Deleted:           {deleted:,} ({deleted_size / (1024*1024):.1f} MB reclaimed)")
    conn.close()
```

**Step 2: Verify it loads**

Run: `cd /Users/david/dev/MailBomb && mailbomb stats --help`
Expected: Shows help

**Step 3: Commit**

```bash
git add mailbomb/cli.py
git commit -m "feat: stats command showing scan and deletion progress"
```

---

### Task 12: Integration Test — Full Workflow

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write the integration test**

```python
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
    mock_list.return_value.list_next.return_value = None

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
```

**Step 2: Run all tests**

Run: `cd /Users/david/dev/MailBomb && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: integration test covering full scan → analyze → delete workflow"
```

---

## Summary

| Task | Module | What it does |
|------|--------|-------------|
| 1 | Scaffolding | pyproject.toml, package, CLI entry point |
| 2 | db.py | SQLite schema, upsert, query helpers |
| 3 | auth.py | OAuth2 credential management |
| 4 | cli: setup | Guided OAuth walkthrough |
| 5 | scanner.py | Date-windowed Gmail metadata fetcher |
| 6 | cli: scan | Scan command with date options |
| 7 | analyzer.py | Pattern detection queries |
| 8 | cli: analyze | Rich table output for analysis |
| 9 | executor.py | Batch deletion via Gmail API |
| 10 | cli: delete | Delete command with filters + confirmation |
| 11 | cli: stats | Progress tracking |
| 12 | Integration | End-to-end workflow test |
