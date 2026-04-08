# Deletion Safety Model

MailBomb is designed to make destructive operations **visible, reversible, and
auditable**. This document explains exactly what happens when you delete mail,
so you can decide for yourself how much trust to extend.

## The one rule

> **`mailbomb delete` moves messages to Gmail Trash by default.**
>
> Trash is recoverable from the Gmail web UI for 30 days. Permanent deletion
> requires the explicit `--permanent` flag. There is no default code path in
> MailBomb that bypasses Trash.

If you ever see a command or suggestion that passes `--permanent` without your
knowledge, stop and investigate. The project's `CLAUDE.md` explicitly forbids
AI assistants from adding `--permanent` unless you ask for it.

## Layered protections

Every deletion passes through four gates before Gmail is touched:

### 1. Filter required

`delete` refuses to run without at least one filter (`--sender`, `--list-id`,
`--before`, or `--min-size`). A bare `mailbomb delete` exits with an error
rather than asking "delete what?". See `mailbomb/cli.py` — `delete()`.

### 2. Local resolution before any network call

Filters are resolved against the local SQLite index (`resolve_message_ids` in
`mailbomb/executor.py`), **not** against Gmail's search. This means:

- You can preview exactly which Gmail IDs would be affected without hitting
  the Gmail API.
- A badly-formed query cannot accidentally match more than what you scanned.
- Messages already marked `deleted = 1` in the local DB are excluded from
  further delete calls.

### 3. Dry-run

`--dry-run` prints the count and reclaimable size, then exits without calling
Gmail. Always run a dry-run first:

```bash
mailbomb delete --sender "notifications@facebook.com" --dry-run
```

Expected output:

```
Messages to delete: 1,247
Space to reclaim: 38.4 MB

Dry run — no messages deleted.
```

### 4. Interactive confirmation

Without `--yes`/`-y`, the CLI prints the target count and size and prompts
`Trash 1,247 messages?` before touching Gmail. The prompt uses the word
**Trash** or **Permanently delete** depending on which operation is queued, so
you can't confuse the two.

## Trash vs. permanent — what each one does

| | `mailbomb delete` (default) | `mailbomb delete --permanent` |
|---|---|---|
| Gmail API call | `users.messages.batchModify` adding `TRASH` label, removing `INBOX` | `users.messages.batchDelete` |
| Recoverable via Gmail web UI? | Yes, 30 days | **No.** Immediate and irreversible. |
| Recoverable via `mailbomb` | Yes — `/api/untrash` in the review UI | No |
| Local DB effect | `deleted = 1` | `deleted = 1` |

Both paths batch up to 1,000 message IDs per Gmail API request (see
`trash_messages` and `delete_messages` in `mailbomb/executor.py`).

## Undo: restoring trashed messages

The review UI tracks every message it trashes during a session. The
`/api/session-trashed` endpoint lists them, and `/api/untrash` restores them by
calling `batchModify` with `INBOX` added and `TRASH` removed (see
`untrash_messages` in `mailbomb/executor.py`). The local DB is updated to
`deleted = 0`.

For CLI-initiated trashes, restoration happens through the Gmail web UI's own
Trash folder within the 30-day window.

## Command hygiene (for humans and AI assistants)

`CLAUDE.md` in the project root encodes these rules for any AI assistant
operating the tool:

1. `delete` defaults to trash. **Never** add `--permanent` unless the user
   explicitly asked for it.
2. All flags on a single line. A broken `\` continuation can silently strip a
   flag (for example, turning a dry-run into a live run).
3. Read the full command string before executing it.

If you run MailBomb through a shell script or wrapper, apply the same rules.
It takes one line break in the wrong place to turn a preview into a deletion.

## What MailBomb does *not* protect against

Be honest about the edges:

- **Scope.** The OAuth token grants full Gmail access (see
  [data-and-privacy.md](data-and-privacy.md)). Any process with that token can
  delete mail. Protect `~/.mailbomb/token.json`.
- **Permanent flag.** `--permanent` bypasses Gmail Trash. Once that call
  returns, the messages are gone.
- **Local DB drift.** If you delete mail through another client, the local
  index may still list those messages as active until you re-scan.
- **Filter mistakes on the right matches.** Dry-run shows counts; confirm the
  senders/subjects look right before confirming.

## Recommended workflow

```bash
# 1. Preview
mailbomb delete --sender "deals@groupon.com" --dry-run

# 2. If the count and size look right, execute (to trash)
mailbomb delete --sender "deals@groupon.com"

# 3. If you realize within 30 days that you want it back, recover from
#    Gmail's Trash folder in the web UI.
```

For anything you might regret, stop at step 2 and leave `--permanent` off.
