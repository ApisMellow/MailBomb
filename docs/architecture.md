# Architecture

A short tour of how MailBomb is put together, for anyone who wants to extend
it or audit how it handles mail.

## The pipeline

```
        Gmail API
           │
           ▼                       Local only
  ┌─────────────────┐        ┌────────────────┐
  │   scan          │───────▶│ ~/.mailbomb/   │
  │  (metadata GET) │        │  mailbomb.db   │
  └─────────────────┘        └────────┬───────┘
                                      │
                             ┌────────┴────────┐
                             ▼                 ▼
                      ┌────────────┐    ┌────────────┐
                      │  analyze   │    │   review   │
                      │ (SQL only) │    │ (Flask UI) │
                      └────────────┘    └──────┬─────┘
                                               │
                                               ▼
                                      ┌────────────────┐
                                      │     delete     │
                                      │ (batchModify / │
                                      │  batchDelete)  │
                                      └────────┬───────┘
                                               ▼
                                           Gmail API
```

Only two stages talk to Gmail: `scan` (reads metadata) and `delete` (trashes
or permanently deletes). `analyze` and most of `review` operate on the local
index.

## Module map

| File | Responsibility |
|---|---|
| `mailbomb/cli.py` | Click commands: `setup`, `scan`, `analyze`, `delete`, `stats`, `review`. Thin wiring layer. |
| `mailbomb/auth.py` | OAuth desktop flow. Builds `google-api-python-client` service with scope `https://mail.google.com/`. Caches token at `~/.mailbomb/token.json`. |
| `mailbomb/db.py` | SQLite schema and connection helpers. Tables: `messages`, `snippets`, `rules`. |
| `mailbomb/scanner.py` | Iterates Gmail `messages.list` + `messages.get(format="metadata")`, parses headers, upserts into DB. Resumable. |
| `mailbomb/analyzer.py` | Read-only SQL: top senders, mailing lists, year breakdown, totals. |
| `mailbomb/executor.py` | `resolve_message_ids`, `trash_messages`, `untrash_messages`, `delete_messages`. |
| `mailbomb/reviewer.py` | Scores sender groups by "bulk likelihood" for the review UI. |
| `mailbomb/snippets.py` | Plaintext snippet extraction from multipart bodies. On-demand only. |
| `mailbomb/rules.py` | Saved sender / list-id rules created from the "Rule" action. |
| `mailbomb/web.py` | Flask app backing the review UI. JSON API + one template. |
| `mailbomb/templates/review.html` | The entire review UI — HTML, CSS, JS — single file by design. |

## Data model

`mailbomb.db` (see `mailbomb/db.py`):

```sql
messages(
  gmail_id PRIMARY KEY,
  thread_id, sender, sender_email, subject, date,
  size_bytes, labels, list_id,
  deleted BOOLEAN DEFAULT 0
)

snippets(
  gmail_id PRIMARY KEY,
  body_preview TEXT
)

rules(
  id AUTOINCREMENT,
  sender_email, list_id, created_at
)
```

Indexes on `sender_email`, `date`, and `size_bytes` keep the analyzer fast on
multi-hundred-thousand-row mailboxes.

## The scan loop

`scan_messages` (in `mailbomb/scanner.py`) runs an idempotent loop:

1. Build a Gmail query from `--before` / `--after` (e.g. `before:2006/01/01`).
2. Page through `users.messages.list`.
3. For each message ID, check if it already exists in the local DB. If yes,
   increment `skipped` and continue — this is what makes scans resumable.
4. Otherwise, `users.messages.get(format="metadata", metadataHeaders=["From",
   "Subject", "Date", "List-Id"])`.
5. Parse headers, upsert into `messages`.

`format=metadata` with an explicit header allowlist is a deliberate choice:
it guarantees bodies never come across the wire during scanning.

## The review loop

`mailbomb review` starts a Flask server on `localhost:5050` and opens a
Chromium-based browser pointed at it.

1. `GET /api/patterns` → `reviewer.rank_patterns(conn)` groups messages by
   `sender_email`, scores each group (volume, list-id presence, subject
   uniformity, noreply-ish sender, whether you ever replied), sorts by score.
2. For the current card, `GET /api/snippet/<id>` pulls a cached or fresh
   body preview. `GET /api/diverse-samples/<sender>` pulls up to 5 distinct
   subjects with full bodies for deeper inspection.
3. When you hit T/K/S/R (or speak), the corresponding `POST /api/trash |
   keep | skip | rule` fires. Trash and rule both go through
   `executor.trash_messages` — never `delete_messages`.
4. The server keeps an in-memory session so you can undo trashes via
   `POST /api/untrash` from the session summary screen.

Voice control is a pure client-side feature: `review.html` uses the Web
Speech API and calls the same JSON endpoints. See
[voice-control.md](voice-control.md).

## The delete pipeline

`mailbomb delete` is a thin wrapper around three helpers in
`mailbomb/executor.py`:

- `resolve_message_ids(conn, sender_email, list_id, before, after, min_size)`
  — pure SQL against the local index.
- `trash_messages(ids)` — batchModify with `TRASH` label, 1,000 IDs per call.
- `delete_messages(ids)` — batchDelete, 1,000 IDs per call. Only reached when
  the user passed `--permanent`.

Both write `deleted = 1` into the local DB inside the same loop, so the
index stays consistent with Gmail.

## Invariants worth preserving

If you extend MailBomb, keep these invariants:

1. **Scan fetches metadata only.** Any body-reading code belongs on the
   review side and must be on-demand, triggered by user action.
2. **Delete defaults to trash.** `--permanent` is the only path to
   `batchDelete`. Adding shortcuts here breaks the safety model; don't.
3. **Resolve filters locally.** `delete` must never use Gmail search to
   determine its target set — the set comes from the local index so it can
   be dry-run and audited.
4. **Resumability.** The scanner's "already in DB → skip" check is what
   makes long scans tractable. Don't short-circuit it.
5. **One OAuth scope.** `https://mail.google.com/` is enough and is the
   only scope requested. Do not broaden it.

## Testing

`tests/` contains coverage for each module:

- `test_scanner.py`, `test_executor.py`, `test_db.py` — core data path.
- `test_analyzer.py`, `test_reviewer.py`, `test_rules.py`, `test_snippets.py`
  — analysis and triage helpers.
- `test_web.py`, `test_review_integration.py` — review API end-to-end.
- `test_cli_*.py` — CLI surface.
- `test_integration.py` — top-level happy path.

Run them with:

```bash
pytest tests/ -v
```
