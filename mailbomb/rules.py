def add_rule(conn, sender_email=None, list_id=None):
    """Add a trash rule. Messages matching this rule get auto-flagged."""
    if sender_email:
        conn.execute(
            "INSERT OR IGNORE INTO rules (sender_email) VALUES (?)",
            (sender_email,),
        )
    elif list_id:
        conn.execute(
            "INSERT OR IGNORE INTO rules (list_id) VALUES (?)",
            (list_id,),
        )
    conn.commit()


def get_rules(conn):
    """Return all rules as a list of dicts."""
    rows = conn.execute("SELECT * FROM rules ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def matches_rule(conn, sender_email=None, list_id=None):
    """Check if a sender or list matches an existing rule."""
    if sender_email:
        row = conn.execute(
            "SELECT 1 FROM rules WHERE sender_email = ?", (sender_email,)
        ).fetchone()
        if row:
            return True
    if list_id:
        row = conn.execute(
            "SELECT 1 FROM rules WHERE list_id = ?", (list_id,)
        ).fetchone()
        if row:
            return True
    return False


def remove_rule(conn, sender_email=None, list_id=None):
    """Remove a rule by sender or list."""
    if sender_email:
        conn.execute("DELETE FROM rules WHERE sender_email = ?", (sender_email,))
    elif list_id:
        conn.execute("DELETE FROM rules WHERE list_id = ?", (list_id,))
    conn.commit()
