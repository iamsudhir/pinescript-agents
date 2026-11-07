"""Use cases shared by the Streamlit pages and the CLI."""
import json
from pathlib import Path

from . import ROOT, data, db, engine, generate


def rel(path):
    """Repo-relative posix path when inside the repo (how imports are recorded), else absolute."""
    p = Path(path).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def create_from(conn, gen, source_type):
    return db.create_strategy(conn, gen.name, source_type, source=gen.source, transcript=gen.transcript,
                              notes=gen.notes, pine_code=gen.pine, python_code=gen.python)


def import_pine(conn, path):
    path = Path(path)
    gen = generate.from_pine(path.read_text(encoding="utf-8"), path.stem)
    gen.source = rel(path)
    return create_from(conn, gen, "pine_import")


def _load(conn, market):
    return data.load_data(conn, market["ticker"], market["interval"], market["start"], market["end"])


def backtest(conn, version_id, market, params):
    """Run a saved code version on market data and store the run. Returns (run_id, RunResult)."""
    code = db.get_version(conn, version_id)["python_code"]
    res = engine.run(code, _load(conn, market), params, market["cash"], market["commission"])
    rid = db.save_run(conn, version_id, market, res.params, res.stats, res.trades, res.equity)
    return rid, res


def optimize(conn, version_id, market, ranges, maximize):
    """Grid-search a saved code version and store the result. Returns (optimization_id, OptResult)."""
    code = db.get_version(conn, version_id)["python_code"]
    res = engine.optimize(code, _load(conn, market), ranges, maximize, market["cash"], market["commission"])
    oid = db.save_optimization(conn, version_id, market, ranges, maximize,
                               json.loads(res.results.to_json(orient="records")), res.best_params, res.best_value)
    return oid, res


def chart_for_run(conn, run_id):
    """Charts aren't stored: re-run the saved version + params on cached bars and render."""
    run = db.get_run(conn, run_id)
    market = {"ticker": run["ticker"], "interval": run["interval"], "start": run["start_date"], "end": run["end_date"]}
    code = db.get_version(conn, run["strategy_version_id"])["python_code"]
    return engine.chart_html(engine.run(code, _load(conn, market), run["params"], run["cash"], run["commission"]))
