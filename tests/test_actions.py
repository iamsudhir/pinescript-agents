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


def test_create_from_keeps_generated_interval(conn):
    gen = generate.Generated(name="ORB", pine="", python="", interval="5m")
    assert db.get_strategy(conn, actions.create_from(conn, gen, "description"))["default_interval"] == "5m"


def test_strategy_with_index_ticker_gets_index_bars(conn, goog, monkeypatch):
    seen = []

    def fake_load(conn, ticker, interval, start, end):
        seen.append(ticker)
        return goog if ticker == "GOOG" else goog.iloc[::2] * 2  # the index misses every other bar

    monkeypatch.setattr(actions.data, "load_data", fake_load)
    code = SMA_CODE.replace("    n1 = 10\n", '    index_ticker = "^NSEI"\n    n1 = 10\n')
    df = actions._load(conn, MARKET, code)
    assert seen == ["GOOG", "^NSEI"] and list(df.columns[-2:]) == ["IndexOpen", "IndexClose"]
    assert df.IndexClose.iloc[0] == goog.Close.iloc[0] * 2 and df.IndexClose.isna().sum() == len(goog) // 2
    assert "index_ticker" not in actions.engine.load_strategy(code)[1]  # not a tunable parameter
    assert list(actions._load(conn, MARKET, SMA_CODE).columns) == list(goog.columns)
