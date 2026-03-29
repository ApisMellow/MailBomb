# MailBomb

Prune massive Gmail mailboxes by scanning oldest-first, building a local metadata index, identifying patterns, and executing batch deletions via the Gmail API.

Built for mailboxes too large for Gmail's web UI or MCP connectors to handle.

## How It Works

1. **Scan** — queries Gmail API with date windows (e.g., `before:2006/01/01`), pulls only message metadata (sender, subject, date, size — no bodies), stores in a local SQLite database
2. **Analyze** — runs queries over the local index to surface patterns: top senders, mailing lists, size hogs, year-by-year breakdown
3. **Delete** — takes filter criteria, resolves to message IDs, batch-deletes via Gmail API (up to 1000 per call), marks deleted locally

Scanning is resumable — if interrupted, it skips messages already in the database.

## Prerequisites

- Python 3.10+
- A Google account with Gmail

## Installation

```bash
cd /path/to/MailBomb
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Google Cloud Setup (One-Time)

Before MailBomb can access your Gmail, you need OAuth2 credentials:

### 1. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown (top bar) and select **New Project**
3. Name it something like "MailBomb" and click **Create**
4. Make sure the new project is selected in the dropdown

### 2. Enable the Gmail API

1. Go to [Gmail API Library page](https://console.cloud.google.com/apis/library/gmail.googleapis.com)
2. Click **Enable**

### 3. Configure OAuth Consent Screen

1. Go to [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent)
2. Select **External** (unless you have a Workspace org) and click **Create**
3. Fill in:
   - App name: `MailBomb`
   - User support email: your email
   - Developer contact: your email
4. Click **Save and Continue**
5. On the **Scopes** page, click **Add or Remove Scopes**
6. Find and check `https://mail.google.com/` (full Gmail access)
7. Click **Update**, then **Save and Continue**
8. On the **Test users** page, click **Add Users** and add your Gmail address
9. Click **Save and Continue**, then **Back to Dashboard**

### 4. Create OAuth Credentials

1. Go to [Credentials](https://console.cloud.google.com/apis/credentials)
2. Click **Create Credentials** > **OAuth client ID**
3. Application type: **Desktop app**
4. Name: `MailBomb` (or anything)
5. Click **Create**
6. Click **Download JSON** on the confirmation dialog
7. Save the file as:
   ```
   ~/.mailbomb/credentials.json
   ```
   Create the directory if needed: `mkdir -p ~/.mailbomb`

### 5. Authenticate

```bash
mailbomb setup
```

This opens a browser for you to authorize MailBomb. After authorization, a token is cached at `~/.mailbomb/token.json` so you won't need to re-authorize.

You'll see output like:
```
Authenticated as you@gmail.com
Total messages: 487,293
Database initialized
```

## Usage

### Scan messages by date range

Start from the oldest and work forward:

```bash
# Scan everything before 2006
mailbomb scan --before 2006-01-01

# Scan a specific year
mailbomb scan --before 2007-01-01 --after 2006-01-01

# Larger batches (up to 500) for faster scanning
mailbomb scan --before 2006-01-01 --batch-size 500
```

Scanning pulls **metadata only** (sender, subject, date, size) — no message bodies are downloaded. It's resumable: re-running the same command skips already-indexed messages.

### Analyze what you've scanned

```bash
mailbomb analyze
```

Shows:
- **Top senders by message count** — who sent you the most mail
- **Top senders by total size** — who's eating the most space
- **Mailing lists** — detected via List-Id header
- **Year breakdown** — messages and size per year
- **Total indexed size**

### Delete messages

Always use `--dry-run` first to preview:

```bash
# Preview deleting all messages from a sender
mailbomb delete --sender "notifications@facebook.com" --dry-run

# Preview deleting a mailing list
mailbomb delete --list-id "<updates.linkedin.com>" --dry-run

# Preview deleting old large messages
mailbomb delete --before 2008-01-01 --min-size 10MB --dry-run

# When satisfied, remove --dry-run to execute (you'll get a confirmation prompt)
mailbomb delete --sender "notifications@facebook.com"
```

Deletions are **permanent** (bypasses trash). The tool always asks for confirmation before executing.

### Check progress

```bash
mailbomb stats
```

Shows how many messages you've scanned, kept, and deleted, with sizes.

## Typical Workflow

```bash
# 1. Set up (one time)
mailbomb setup

# 2. Scan your oldest mail
mailbomb scan --before 2006-01-01

# 3. See what's there
mailbomb analyze

# 4. Kill the obvious junk (dry-run first!)
mailbomb delete --sender "deals@groupon.com" --dry-run
mailbomb delete --sender "deals@groupon.com"

# 5. Scan the next chunk
mailbomb scan --before 2008-01-01 --after 2006-01-01

# 6. Repeat analyze → delete → scan forward
mailbomb analyze
mailbomb stats
```

## Data Storage

All local data lives in `~/.mailbomb/`:

| File | Purpose |
|------|---------|
| `credentials.json` | Your OAuth2 client credentials (you download this) |
| `token.json` | Cached auth token (auto-generated on first auth) |
| `mailbomb.db` | SQLite database with message metadata index |

The database stores only metadata — no message bodies. It tracks which messages have been deleted so you don't re-scan them.

## Running Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

## Future Plans

- **Voice review mode** (`mailbomb review`) — displays messages one at a time with voice-driven keep/delete decisions for hands-free triage
