import json

import pytest
from conftest import MARKET, SMA_CODE

from workbench import db, insights


def _run(conn, vid, ticker, ret, sharpe):
    return db.save_run(conn, vid, {**MARKET, "ticker": ticker}, {},
                       {"Return [%]": ret, "Sharpe Ratio": sharpe, "Max. Drawdown [%]": -10.0}, [], [])


def test_summary_empty(conn):
    sid = db.create_strategy(conn, "S", "description")
    assert insights.summary(conn, sid) == {"n_runs": 0, "stability": None}


def test_summary_best_worst_and_per_market(conn):
    sid = db.create_strategy(conn, "S", "description")
    vid = db.latest_version(conn, sid)["id"]
    _run(conn, vid, "A", 10.0, 1.0)
    best = _run(conn, vid, "A", 30.0, 0.5)
    worst = _run(conn, vid, "B", -5.0, None)
    sm = insights.summary(conn, sid)
    assert sm["n_runs"] == 3
    assert (sm["best_by_return"], sm["worst_by_return"]) == (best, worst)
    assert sm["mean"]["Return [%]"] == 35.0 / 3 and sm["mean"]["Sharpe Ratio"] == 0.75
    by = {r["ticker"]: r for r in sm["by_market"]}
    assert by["A"]["runs"] == 2 and by["A"]["pct_profitable"] == 100.0 and by["B"]["pct_profitable"] == 0.0


def test_stability_flags_a_lone_spike():
    spike = {"id": 1, "maximize": "Sharpe Ratio",
             "results": [{"n": i, "Sharpe Ratio": 2.0 if i == 5 else 0.1} for i in range(20)]}
    st = insights.stability(spike)
    assert st["share_within_80pct"] == 0.05 and st["likely_overfit"] is True
    plateau = {"id": 2, "maximize": "Sharpe Ratio", "results": [{"n": i, "Sharpe Ratio": 1.0} for i in range(5)]}
    assert insights.stability(plateau)["likely_overfit"] is False
    assert insights.stability({"id": 3, "maximize": "Sharpe Ratio", "results": []}) is None


def test_analyze_saves_insight(conn, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "1")
    sid = db.create_strategy(conn, "S", "description", python_code=SMA_CODE)
    vid = db.latest_version(conn, sid)["id"]
    rid = _run(conn, vid, "A", 10.0, 1.0)
    iid = insights.analyze(conn, sid)
    ins = db.list_insights(conn, sid)[0]
    assert ins["id"] == iid and ins["run_ids"] == [rid] and ins["content"].startswith("## ")


def test_analyze_without_runs_raises_before_calling_claude(conn, monkeypatch):
    monkeypatch.setattr(insights.generate, "_call", lambda *a, **k: pytest.fail("Claude was called"))
    sid = db.create_strategy(conn, "S", "description", python_code=SMA_CODE)
    with pytest.raises(ValueError, match="No runs"):
        insights.analyze(conn, sid)


def test_summary_is_json_safe_with_missing_stats(conn):
    sid = db.create_strategy(conn, "S", "description")
    vid = db.latest_version(conn, sid)["id"]
    db.save_run(conn, vid, MARKET, {}, {"Return [%]": None, "Sharpe Ratio": None, "Max. Drawdown [%]": None}, [], [])
    sm = insights.summary(conn, sid)
    json.dumps(sm, allow_nan=False)
    assert sm["by_market"][0]["pct_profitable"] is None
