import math


def rank_patterns(conn, limit=50):
    """Group messages by sender, score by junk likelihood, return sorted list.

    Scoring heuristic (higher = more likely junk):
    - message_count: more messages = more bulk-like
    - has_list_id: mailing list header present
    - subject_uniformity: low subject diversity = templated
    - noreply_sender: sender contains noreply/notify/no-reply
    - no_sent_label: you never replied (one-way communication)

    Returns list of dicts sorted by score descending:
    {
        sender_email, list_id, count, total_size, score,
        sample_subjects (up to 5), sample_gmail_id,
        earliest, latest
    }
    """
    rows = conn.execute("""
        SELECT sender_email,
               list_id,
               COUNT(*) as count,
               SUM(size_bytes) as total_size,
               MIN(date) as earliest,
               MAX(date) as latest
        FROM messages
        WHERE deleted = 0
        GROUP BY sender_email
        HAVING count >= 2
        ORDER BY count DESC
        LIMIT ?
    """, (limit,)).fetchall()

    patterns = []
    for row in rows:
        sender = row[0]
        list_id = row[1]
        count = row[2]
        total_size = row[3]
        earliest = row[4]
        latest = row[5]

        # Fetch sample subjects (up to 5 distinct)
        subjects = conn.execute("""
            SELECT DISTINCT subject FROM messages
            WHERE sender_email = ? AND deleted = 0
            LIMIT 5
        """, (sender,)).fetchall()
        sample_subjects = [s[0] for s in subjects if s[0]]

        # Fetch one representative gmail_id for snippet
        sample_row = conn.execute("""
            SELECT gmail_id FROM messages
            WHERE sender_email = ? AND deleted = 0
            LIMIT 1
        """, (sender,)).fetchone()
        sample_gmail_id = sample_row[0] if sample_row else None

        # Count distinct subjects for uniformity check
        distinct_count = conn.execute("""
            SELECT COUNT(DISTINCT subject) FROM messages
            WHERE sender_email = ? AND deleted = 0
        """, (sender,)).fetchone()[0]

        # Check if any messages have SENT label (indicates two-way)
        sent_count = conn.execute("""
            SELECT COUNT(*) FROM messages
            WHERE sender_email = ? AND deleted = 0 AND labels LIKE '%SENT%'
        """, (sender,)).fetchone()[0]

        # --- Scoring ---
        score = 0.0

        # Volume: log-scale, caps at ~40 points
        score += min(40, math.log2(max(count, 1)) * 6)

        # Has List-Id: strong bulk signal
        if list_id:
            score += 15

        # Subject uniformity: few unique subjects relative to count = templated
        if count > 5:
            uniformity = 1.0 - (distinct_count / count)
            score += uniformity * 20

        # Noreply/automated sender
        sender_lower = sender.lower()
        if any(kw in sender_lower for kw in ["noreply", "no-reply", "notify", "notification", "mailer-daemon", "postmaster"]):
            score += 15

        # No replies from user (one-way)
        if sent_count == 0:
            score += 10

        patterns.append({
            "sender_email": sender,
            "list_id": list_id,
            "count": count,
            "total_size": total_size,
            "score": round(score, 1),
            "sample_subjects": sample_subjects,
            "sample_gmail_id": sample_gmail_id,
            "earliest": earliest,
            "latest": latest,
        })

    patterns.sort(key=lambda p: p["score"], reverse=True)
    return patterns
