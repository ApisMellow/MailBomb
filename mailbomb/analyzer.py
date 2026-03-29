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


def _extract_year(date_str):
    """Extract 4-digit year from a date string (RFC 2822 or ISO 8601)."""
    import re
    match = re.search(r'\b((?:19|20)\d{2})\b', date_str or "")
    return match.group(1) if match else None


def breakdown_by_year(conn):
    """Return message count and size by year."""
    rows = conn.execute(
        "SELECT date, size_bytes FROM messages WHERE deleted = 0",
    ).fetchall()

    buckets = {}
    for row in rows:
        year = _extract_year(row[0])
        if year is None:
            continue
        if year not in buckets:
            buckets[year] = {"year": year, "count": 0, "total_size": 0}
        buckets[year]["count"] += 1
        buckets[year]["total_size"] += row[1] or 0

    return sorted(buckets.values(), key=lambda r: r["year"])


def total_size(conn):
    """Return total size of all non-deleted messages in bytes."""
    row = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) FROM messages WHERE deleted = 0"
    ).fetchone()
    return row[0]
