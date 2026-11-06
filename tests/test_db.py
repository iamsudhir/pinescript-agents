from workbench import db


def test_create_strategy_with_unique_slug_and_first_version(conn):
    sid = db.create_strategy(conn, "RSI Revert!", "description", source="buy rsi<30",
                             notes=["n1"], pine_code="//@version=6", python_code="code")
    s = db.get_strategy(conn, sid)
    assert s["slug"] == "rsi-revert"
    assert s["notes"] == ["n1"] and s["status"] == "idea" and s["rating"] is None
    v = db.latest_version(conn, sid)
    assert (v["version"], v["pine_code"], v["python_code"], v["change_note"]) == (1, "//@version=6", "code", "generated")

    sid2 = db.create_strategy(conn, "RSI Revert", "description")
    assert db.get_strategy(conn, sid2)["slug"] == "rsi-revert-2"
    assert db.get_strategy(conn, slug="rsi-revert-2")["id"] == sid2


def test_add_version_increments_and_lists_newest_first(conn):
    sid = db.create_strategy(conn, "S", "description", pine_code="p1", python_code="c1")
    v2 = db.add_version(conn, sid, "p2", "c2", "manual edit")
    assert db.latest_version(conn, sid)["id"] == v2
    assert [v["version"] for v in db.list_versions(conn, sid)] == [2, 1]
    assert db.get_version(conn, v2)["python_code"] == "c2"


def test_update_and_filter_strategies(conn):
    a = db.create_strategy(conn, "Alpha", "description")
    db.create_strategy(conn, "Beta", "youtube")
    db.update_strategy(conn, a, status="promising", rating=4, user_notes="works on banks", notes=["x"])
    s = db.get_strategy(conn, a)
    assert (s["status"], s["rating"], s["user_notes"], s["notes"]) == ("promising", 4, "works on banks", ["x"])
    assert [r["name"] for r in db.list_strategies(conn, status="promising")] == ["Alpha"]
    assert [r["name"] for r in db.list_strategies(conn, min_rating=3)] == ["Alpha"]
    assert [r["name"] for r in db.list_strategies(conn, search="bet")] == ["Beta"]
    assert db.sources(conn, "youtube") == {None}


def test_update_rejects_unknown_fields(conn):
    sid = db.create_strategy(conn, "S", "description")
    try:
        db.update_strategy(conn, sid, slug="hack")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
