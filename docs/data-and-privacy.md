# Data & Privacy

MailBomb is a local tool that talks to Gmail on your behalf. This document
explains, concretely, what it reads, what it stores, and what it sends
anywhere. No marketing — just the facts, with file references.

## TL;DR

- MailBomb runs entirely on your machine. There is no MailBomb server.
- It talks to exactly one external service: **Google's Gmail API**, over HTTPS.
- It stores **message metadata only** in a local SQLite database. It never
  downloads or stores full message bodies — with one narrow exception noted
  below (on-demand snippets in the review UI).
- Your OAuth token is stored locally at `~/.mailbomb/token.json`.

## OAuth scope — what you grant Google's consent screen

MailBomb requests a single scope:

```
https://mail.google.com/
```

Source: `mailbomb/auth.py` — `SCOPES`.

This is **full Gmail access** — read, modify, and delete. MailBomb needs
modify/delete because its job is to trash mail. It does not need, and does not
request, any additional Google scopes (Drive, Contacts, Calendar, profile,
etc.).

You can review and revoke this grant at any time at
[myaccount.google.com/permissions](https://myaccount.google.com/permissions).

## What MailBomb reads from Gmail

### During `scan`

For each message in the date range, MailBomb calls
`users.messages.get(format="metadata", metadataHeaders=[...])` with an explicit
allowlist of headers:

- `From`
- `Subject`
- `Date`
- `List-Id`

Source: `mailbomb/scanner.py` — `scan_messages`.

`format=metadata` means **no message body is retrieved**. Gmail returns the
headers listed above plus standard metadata (`id`, `threadId`, `sizeEstimate`,
`labelIds`). Nothing else.

### During `analyze`

Nothing. `analyze` runs SQL over the local database only. No network calls.

### During `delete`

The filter is resolved against the **local database** (no Gmail search
involved). Then one of:

- Trash: `users.messages.batchModify` to add the `TRASH` label.
- Permanent: `users.messages.batchDelete`.

Both operations send only the list of Gmail IDs. No bodies, no headers.

Source: `mailbomb/executor.py` — `trash_messages`, `delete_messages`.

### During `review` (the web UI)

The web UI fetches message bodies **on demand** when you explicitly interact
with a card:

- `/api/snippet/<gmail_id>` — pulls a short plaintext preview for the visible
  card and caches it locally in the `snippets` table.
- `/api/diverse-samples/<sender_email>` — when you drill into a sender, fetches
  up to 5 representative bodies so you can eyeball what they look like.
- `/api/fullmessage/<gmail_id>` — fetches a full body only if you hit the
  "show full" action.

Source: `mailbomb/web.py`, `mailbomb/snippets.py`.

Bodies touched this way are cached locally in SQLite (`snippets` table, see
`mailbomb/db.py`). They stay on your machine.

## Local files

All state lives in `~/.mailbomb/`:

| File | What it is | Sensitive? |
|---|---|---|
| `credentials.json` | OAuth **client** credentials you downloaded from Google Cloud Console | Low — these identify the app, not a session |
| `token.json` | OAuth **user** token. Anyone with this file can act as you on Gmail | **High** — treat like a password |
| `mailbomb.db` | SQLite index of scanned metadata, deletion state, snippet cache, and rules | Medium — contains subjects, senders, previews |

Source: `mailbomb/auth.py` (`CONFIG_DIR`), `mailbomb/db.py` (`DEFAULT_DB_PATH`).

### What's in `mailbomb.db`

Schema (from `mailbomb/db.py`):

- `messages` — one row per scanned message: `gmail_id`, `thread_id`,
  `sender`, `sender_email`, `subject`, `date`, `size_bytes`, `labels`,
  `list_id`, `deleted`.
- `snippets` — cached plaintext preview per message, populated only for
  messages you looked at in the review UI.
- `rules` — saved sender / list-id rules you created via the "Rule" action.

No passwords, no auth tokens, no arbitrary body content beyond what you
previewed.

## What MailBomb does **not** do

- It does not upload anything to a MailBomb server. There is no such server.
- It does not phone home for analytics.
- It does not use any AI model, cloud service, or third-party API other than
  Gmail.
- It does not request scopes beyond `https://mail.google.com/`.
- It does not store your Google password. OAuth handles auth; MailBomb only
  ever sees the issued token.

## Hardening

If you are worried about `~/.mailbomb/token.json`:

- It sits under your home directory with default OS permissions. Tighten with
  `chmod 600 ~/.mailbomb/token.json` if you want belt-and-suspenders.
- Revoke the token any time at
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
  Re-running `mailbomb setup` will re-issue one.
- Delete `~/.mailbomb/token.json` to force re-authentication on next run.

## When in doubt, verify

Every claim here is pinned to a source file. If a future change drifts from
this document, the source is the source of truth — open an issue and the docs
will be corrected.
