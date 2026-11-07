from conftest import MARKET, SMA_CODE

from workbench import actions, db, generate


def test_backtest_and_optimize_are_saved(conn, goog, monkeypatch):
    monkeypatch.setattr(actions.data, "load_data", lambda conn, ticker, interval, start, end: goog)
    sid = db.create_strategy(conn, "S", "description", python_code=SMA_CODE)
    vid = db.latest_version(conn, sid)["id"]

    rid, res = actions.backtest(conn, vid, MARKET, {"n1": 5})
    run = db.get_run(conn, rid)
    assert run["params"] == {"n1": 5, "n2": 20, "use_exit": True, "stop_pct": 0.0}
    assert run["stats"] == res.stats and len(run["trades"]) == len(res.trades)

    oid, opt = actions.optimize(conn, vid, MARKET, {"n1": (5, 10, 5)}, "Sharpe Ratio")
    saved = db.get_optimization(conn, oid)
    assert saved["best_params"] == opt.best_params and len(saved["results"]) == len(opt.results)

    assert "<html" in actions.chart_for_run(conn, rid).lower()


def test_create_from_and_import_pine(conn, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "1")
    sid = actions.create_from(conn, generate.from_description("ema"), "description")
    assert db.latest_version(conn, sid)["python_code"] == generate.REFERENCE_PY

    pine = tmp_path / "my-strat.pine"
    pine.write_text('//@version=6\nstrategy("My Strat")\n', encoding="utf-8")
    sid = actions.import_pine(conn, pine)
    s = db.get_strategy(conn, sid)
    assert s["source_type"] == "pine_import" and s["source"] == actions.rel(pine)
    assert db.latest_version(conn, sid)["pine_code"] == '//@version=6\nstrategy("My Strat")\n'
    assert actions.rel(pine) in db.sources(conn, "pine_import")


def test_rel_is_repo_relative_inside_repo():
    from workbench import ROOT
    assert actions.rel(ROOT / "projects" / "blank.pine") == "projects/blank.pine"
