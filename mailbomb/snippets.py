import base64
import re


def save_snippet(conn, gmail_id, body_preview):
    """Save a body preview snippet for a message."""
    conn.execute(
        "INSERT OR REPLACE INTO snippets (gmail_id, body_preview) VALUES (?, ?)",
        (gmail_id, body_preview),
    )
    conn.commit()


def get_snippet(conn, gmail_id):
    """Get a cached body preview snippet. Returns None if not cached."""
    row = conn.execute(
        "SELECT body_preview FROM snippets WHERE gmail_id = ?", (gmail_id,)
    ).fetchone()
    return row[0] if row else None


def extract_plaintext(parts):
    """Extract plaintext from Gmail message payload parts.

    Prefers text/plain, falls back to stripping HTML tags from text/html.
    """
    text_part = None
    html_part = None

    for part in parts:
        mime = part.get("mimeType", "")

        # Recurse into nested multipart structures
        sub_parts = part.get("parts")
        if sub_parts:
            nested = extract_plaintext(sub_parts)
            if nested and text_part is None:
                text_part = nested
            continue

        data = part.get("body", {}).get("data", "")
        if not data:
            continue
        if mime == "text/plain" and text_part is None:
            text_part = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif mime == "text/html" and html_part is None:
            html_part = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    if text_part:
        return text_part
    if html_part:
        # Strip HTML tags
        text = re.sub(r"<style[^>]*>.*?</style>", "", html_part, flags=re.DOTALL)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    return ""


def fetch_and_cache_snippet(service, conn, gmail_id, max_chars=800):
    """Fetch message body from Gmail API, extract plaintext, cache it.

    Returns the snippet string (truncated to max_chars).
    """
    cached = get_snippet(conn, gmail_id)
    if cached is not None:
        return cached

    msg = service.users().messages().get(
        userId="me", id=gmail_id, format="full"
    ).execute()

    payload = msg.get("payload", {})
    parts = payload.get("parts", [])
    if not parts:
        # Single-part message — body is directly on payload
        parts = [payload]

    text = extract_plaintext(parts)
    snippet = text[:max_chars]
    save_snippet(conn, gmail_id, snippet)
    return snippet
