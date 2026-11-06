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


from conftest import MARKET


def _run(conn, vid, ret=5.0):
    return db.save_run(conn, vid, MARKET, {"n1": 5}, {"Return [%]": ret, "Sharpe Ratio": 1.2},
                       [{"PnL": 1.0}], [["2020-01-01T00:00:00", 100000.0]])


def test_runs_roundtrip_and_library_summary(conn):
    sid = db.create_strategy(conn, "S", "description")
    vid = db.latest_version(conn, sid)["id"]
    _run(conn, vid, 1.0)
    rid = _run(conn, vid, 5.0)
    run = db.get_run(conn, rid)
    assert run["trades"] == [{"PnL": 1.0}] and run["params"] == {"n1": 5}
    assert (run["strategy_id"], run["version"], run["ticker"], run["start_date"]) == (sid, 1, "GOOG", "2004-08-19")
    db.set_note(conn, "runs", rid, "good on GOOG")
    runs = db.list_runs(conn, sid)
    assert [r["id"] for r in runs][0] == rid and runs[0]["note"] == "good on GOOG"
    assert "trades" not in runs[0]
    row = db.list_strategies(conn)[0]
    assert row["n_runs"] == 2 and row["latest_stats"]["Return [%]"] == 5.0


def test_optimizations_and_insights(conn):
    sid = db.create_strategy(conn, "S", "description")
    vid = db.latest_version(conn, sid)["id"]
    oid = db.save_optimization(conn, vid, MARKET, {"n1": [5, 15, 5]}, "Sharpe Ratio",
                               [{"n1": 10, "Sharpe Ratio": 1.5}], {"n1": 10}, 1.5)
    o = db.get_optimization(conn, oid)
    assert o["results"] == [{"n1": 10, "Sharpe Ratio": 1.5}] and o["best_params"] == {"n1": 10}
    assert db.list_optimizations(conn, sid)[0]["best_value"] == 1.5
    assert (db.list_strategies(conn)[0]["opt_maximize"], db.list_strategies(conn)[0]["opt_best"]) == ("Sharpe Ratio", 1.5)
    db.set_note(conn, "optimizations", oid, "sharp peak")
    assert db.get_optimization(conn, oid)["note"] == "sharp peak"
    iid = db.save_insight(conn, sid, "## Where it works", [1], [oid], "claude-opus-5-5")
    assert db.list_insights(conn, sid)[0]["id"] == iid
    assert db.list_insights(conn, sid)[0]["optimization_ids"] == [oid]


def test_set_note_rejects_other_tables(conn):
    try:
        db.set_note(conn, "strategies", 1, "x")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_delete_cascades(conn):
    sid = db.create_strategy(conn, "S", "description")
    vid = db.latest_version(conn, sid)["id"]
    _run(conn, vid)
    db.save_optimization(conn, vid, MARKET, {}, "Sharpe Ratio", [], {}, None)
    db.save_insight(conn, sid, "x", [], [], "m")
    db.delete_strategy(conn, sid)
    for table in ("strategies", "strategy_versions", "runs", "optimizations", "insights"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
