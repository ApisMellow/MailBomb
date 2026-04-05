# MailBomb - Claude Instructions

## Safety: Email Operations

- The `delete` command defaults to trash (safe, recoverable for 30 days). NEVER pass `--permanent` unless the user explicitly requests permanent deletion.
- When constructing shell commands, write all flags on a single line. Never split flags across line breaks — a broken flag can silently change destructive behavior.
- Before executing any `mailbomb delete` command, visually confirm the full command string and verify no unintended flags are present or missing.
