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
