import pytest
from mailbomb.db import init_db, get_connection
from mailbomb.rules import add_rule, get_rules, matches_rule, remove_rule


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()


def test_add_and_get_rules(db):
    add_rule(db, sender_email="spam@deals.com")
    rules = get_rules(db)
    assert len(rules) == 1
    assert rules[0]["sender_email"] == "spam@deals.com"


def test_add_rule_with_list_id(db):
    add_rule(db, list_id="<dev.example.com>")
    rules = get_rules(db)
    assert len(rules) == 1
    assert rules[0]["list_id"] == "<dev.example.com>"


def test_matches_rule_by_sender(db):
    add_rule(db, sender_email="spam@deals.com")
    assert matches_rule(db, sender_email="spam@deals.com") is True
    assert matches_rule(db, sender_email="friend@gmail.com") is False


def test_matches_rule_by_list_id(db):
    add_rule(db, list_id="<dev.example.com>")
    assert matches_rule(db, list_id="<dev.example.com>") is True
    assert matches_rule(db, list_id="<other.list>") is False


def test_remove_rule(db):
    add_rule(db, sender_email="spam@deals.com")
    remove_rule(db, sender_email="spam@deals.com")
    rules = get_rules(db)
    assert len(rules) == 0


def test_no_duplicate_rules(db):
    add_rule(db, sender_email="spam@deals.com")
    add_rule(db, sender_email="spam@deals.com")
    rules = get_rules(db)
    assert len(rules) == 1
