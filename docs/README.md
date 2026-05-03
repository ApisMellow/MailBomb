# MailBomb Documentation

MailBomb touches live mail — a high-stakes surface area. These docs exist so
you can verify, not just trust, what the tool does on your behalf.

## User docs (candidates)

- [safety.md](safety.md) — Deletion safety model: trash vs. permanent, dry-run,
  confirmations, undo, batch semantics. Read this before running `delete`.
- [data-and-privacy.md](data-and-privacy.md) — What MailBomb reads from Gmail,
  what it stores locally, what it never sends anywhere, and the OAuth scope it
  requests.
- [voice-control.md](voice-control.md) — Hands-free triage in the review UI.
  A significant workflow assist for working through thousands of senders.
- [architecture.md](architecture.md) — How `scan → analyze → review → delete`
  fits together, module by module.

## Implementation plans (historical)

- [plans/2026-03-29-mailbomb-core.md](plans/2026-03-29-mailbomb-core.md) — The
  original build plan for the CLI and database layer.
- [plans/2026-03-29-review-interface.md](plans/2026-03-29-review-interface.md)
  — The build plan for the web review interface.

## Where to start

| If you want to… | Read |
|---|---|
| Understand whether deleting will lose mail | [safety.md](safety.md) |
| Audit what data leaves your machine | [data-and-privacy.md](data-and-privacy.md) |
| Triage a giant mailbox without RSI | [voice-control.md](voice-control.md) |
| Contribute or extend the code | [architecture.md](architecture.md) |
