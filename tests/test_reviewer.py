import pytest
from mailbomb.db import init_db, get_connection, upsert_message
from mailbomb.reviewer import rank_patterns


@pytest.fixture
def populated_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)

    # Bulk sender: newsletter, 50 messages, has list-id
    for i in range(50):
        upsert_message(conn, {
            "gmail_id": f"news_{i}",
            "thread_id": f"t_news_{i}",
            "sender": "updates@newsletter.com",
            "sender_email": "updates@newsletter.com",
            "subject": f"Weekly Digest #{i}",
            "date": f"Mon, {10 + (i % 20)} Jan 2007 08:00:00 -0800",
            "size_bytes": 3000,
            "labels": "INBOX",
            "list_id": "<digest.newsletter.com>",
        })

    # Automated sender: notifications, 30 messages, no list-id
    for i in range(30):
        upsert_message(conn, {
            "gmail_id": f"notif_{i}",
            "thread_id": f"t_notif_{i}",
            "sender": "noreply@social.com",
            "sender_email": "noreply@social.com",
            "subject": "Someone liked your post",
            "date": f"Tue, {10 + (i % 20)} Mar 2007 12:00:00 -0800",
            "size_bytes": 1500,
            "labels": "INBOX",
            "list_id": None,
        })

    # Personal sender: friend, 5 messages, varied subjects
    subjects = ["Dinner Friday?", "Re: Dinner Friday?", "Photos from trip",
                "Check this out", "Happy birthday!"]
    for i, subj in enumerate(subjects):
        upsert_message(conn, {
            "gmail_id": f"friend_{i}",
            "thread_id": f"t_friend_{i}",
            "sender": "alice@gmail.com",
            "sender_email": "alice@gmail.com",
            "subject": subj,
            "date": f"Wed, {10 + i} Feb 2007 09:00:00 -0800",
            "size_bytes": 8000,
            "labels": "INBOX,SENT",
            "list_id": None,
        })

    yield conn
    conn.close()


def test_rank_patterns_returns_groups(populated_db):
    patterns = rank_patterns(populated_db)
    assert len(patterns) == 3
    # Each pattern has required keys
    for p in patterns:
        assert "sender_email" in p
        assert "count" in p
        assert "total_size" in p
        assert "score" in p
        assert "sample_subjects" in p
        assert "sample_gmail_id" in p


def test_rank_patterns_bulk_scores_higher(populated_db):
    patterns = rank_patterns(populated_db)
    scores = {p["sender_email"]: p["score"] for p in patterns}
    # Newsletter and notifications should score higher than personal
    assert scores["updates@newsletter.com"] > scores["alice@gmail.com"]
    assert scores["noreply@social.com"] > scores["alice@gmail.com"]


def test_rank_patterns_sorted_by_score(populated_db):
    patterns = rank_patterns(populated_db)
    scores = [p["score"] for p in patterns]
    assert scores == sorted(scores, reverse=True)


def test_rank_patterns_has_sample_subjects(populated_db):
    patterns = rank_patterns(populated_db)
    for p in patterns:
        assert len(p["sample_subjects"]) > 0
        assert len(p["sample_subjects"]) <= 5


def test_rank_patterns_has_date_range(populated_db):
    patterns = rank_patterns(populated_db)
    for p in patterns:
        assert "earliest" in p
        assert "latest" in p


def test_rank_patterns_has_sample_gmail_id(populated_db):
    patterns = rank_patterns(populated_db)
    for p in patterns:
        assert p["sample_gmail_id"] is not None
