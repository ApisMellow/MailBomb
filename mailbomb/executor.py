from mailbomb.auth import get_gmail_service
from mailbomb.db import get_connection, init_db


def resolve_message_ids(conn, sender_email=None, list_id=None, before=None, after=None, min_size=None):
    """Resolve filter criteria to a list of Gmail message IDs."""
    conditions = ["deleted = 0"]
    params = []

    if sender_email:
        conditions.append("sender_email = ?")
        params.append(sender_email)
    if list_id:
        conditions.append("list_id = ?")
        params.append(list_id)
    if before:
        conditions.append("date < ?")
        params.append(before)
    if after:
        conditions.append("date > ?")
        params.append(after)
    if min_size:
        conditions.append("size_bytes >= ?")
        params.append(min_size)

    where = " AND ".join(conditions)
    rows = conn.execute(f"SELECT gmail_id FROM messages WHERE {where}", params).fetchall()
    return [row[0] for row in rows]


def delete_messages(gmail_ids, db_path=None, batch_size=1000):
    """Delete messages from Gmail and mark them deleted in the local DB.

    Gmail's batchDelete accepts up to 1000 IDs per call.
    """
    if not gmail_ids:
        return 0

    service = get_gmail_service()
    conn = get_connection(db_path)
    total_deleted = 0

    for i in range(0, len(gmail_ids), batch_size):
        batch = gmail_ids[i : i + batch_size]
        service.users().messages().batchDelete(
            userId="me", body={"ids": batch}
        ).execute()

        # Mark as deleted in local DB
        placeholders = ",".join("?" for _ in batch)
        conn.execute(
            f"UPDATE messages SET deleted = 1 WHERE gmail_id IN ({placeholders})",
            batch,
        )
        conn.commit()
        total_deleted += len(batch)

    conn.close()
    return total_deleted
