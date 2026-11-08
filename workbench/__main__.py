"""Command line for the workbench. Run: python -m workbench --help"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import actions, data, db, dhan, engine, generate, insights, lake


def _pairs(items):
    bad = [i for i in items if "=" not in i]
    if bad:
        sys.exit(f"error: expected NAME=VALUE, got {bad[0]!r}")
    return dict(item.split("=", 1) for item in items)


def _range(text):
    parts = text.split(":")
    if len(parts) != 3:
        sys.exit(f"error: range must be MIN:MAX:STEP, got {text!r}")
    return tuple(float(x) for x in parts)


def _strategy(conn, slug):
    s = db.get_strategy(conn, slug=slug)
    if not s:
        sys.exit(f"No strategy {slug!r}. See: python -m workbench list")
    return s


def _market(a, s):
    interval, ticker = a.interval or s["default_interval"], a.ticker or s["default_ticker"]
    return {"ticker": ticker, "interval": interval,
            "start": a.start or data.default_start(interval, ticker), "end": a.end or dt.date.today().isoformat(),
            "cash": a.cash, "commission": a.commission}


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m workbench", description="Strategy workbench")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list strategies").add_argument("--status", choices=db.STATUSES)
    new = sub.add_parser("new", help="generate a strategy with Claude").add_mutually_exclusive_group(required=True)
    new.add_argument("--url", help="YouTube video URL")
    new.add_argument("--desc", help="plain-English strategy description")
    sub.add_parser("import", help="import a .pine file, or every .pine in a folder").add_argument("path", type=Path)
    run, opt = sub.add_parser("run", help="backtest"), sub.add_parser("optimize", help="grid-search parameters")
    for c in (run, opt):
        c.add_argument("slug")
        c.add_argument("--ticker")
        c.add_argument("--interval", choices=data.INTERVALS)
        c.add_argument("--start", help="YYYY-MM-DD")
        c.add_argument("--end", help="YYYY-MM-DD (exclusive)")
        c.add_argument("--cash", type=float, default=1_000_000)
        c.add_argument("--commission", type=float, default=0.0005)
    run.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    opt.add_argument("--range", action="append", required=True, metavar="NAME=MIN:MAX:STEP")
    opt.add_argument("--maximize", default="Sharpe Ratio", choices=engine.MAXIMIZE)
    sub.add_parser("summary", help="computed summary of all runs").add_argument("slug")
    sub.add_parser("analyze", help="ask Claude to analyze the results").add_argument("slug")
    sub.add_parser("lake-pull", help="copy symbols' 5m + daily bars from the MyHFTAlgoBot lake (LAKE_REMOTE)"
                   ).add_argument("tickers", nargs="+", metavar="TICKER", help="e.g. RAYMOND.NS ^NSEI")
    a = p.parse_args(argv)
    conn = db.connect()
    try:
        _dispatch(a, conn)
    except (generate.GenerationError, data.DataError, engine.StrategyContractError, ValueError, KeyError,
            OSError, dhan.DhanError) as e:
        sys.exit(f"error: {e}")


def _dispatch(a, conn):
    if a.cmd == "list":
        for r in db.list_strategies(conn, status=a.status):
            ret = (r["latest_stats"] or {}).get("Return [%]")
            print(f'{r["slug"]:40} {r["status"]:10} runs={r["n_runs"]:<4} '
                  f'last return={"-" if ret is None else f"{ret:.2f}%"}')
    elif a.cmd == "new":
        gen = generate.from_youtube(a.url) if a.url is not None else generate.from_description(a.desc)
        sid = actions.create_from(conn, gen, "youtube" if a.url is not None else "description")
        print("created", db.get_strategy(conn, sid)["slug"])
    elif a.cmd == "import":
        done = db.sources(conn, "pine_import")
        for path in sorted(a.path.glob("*.pine")) if a.path.is_dir() else [a.path]:
            if actions.rel(path) in done:
                print("skip (already imported)", path.name)
                continue
            try:
                print("imported", db.get_strategy(conn, actions.import_pine(conn, path))["slug"])
            except (generate.GenerationError, engine.StrategyContractError, ValueError, OSError) as e:
                print(f"failed {path.name}: {e}")
    elif a.cmd == "run":
        s = _strategy(conn, a.slug)
        rid, res = actions.backtest(conn, db.latest_version(conn, s["id"])["id"], _market(a, s), _pairs(a.param))
        print(json.dumps({"run_id": rid, "params": res.params, **res.stats}, indent=2))
    elif a.cmd == "optimize":
        s = _strategy(conn, a.slug)
        ranges = {k: _range(v) for k, v in _pairs(a.range).items()}
        oid, res = actions.optimize(conn, db.latest_version(conn, s["id"])["id"], _market(a, s), ranges, a.maximize)
        print(res.results.head(20).to_string(index=False))
        print(f"optimization_id={oid} best={res.best_params}")
    elif a.cmd == "summary":
        print(json.dumps(insights.summary(conn, _strategy(conn, a.slug)["id"]), indent=2, default=str))
    elif a.cmd == "analyze":
        s = _strategy(conn, a.slug)
        insights.analyze(conn, s["id"])
        print(db.list_insights(conn, s["id"])[0]["content"])
    elif a.cmd == "lake-pull":
        for ticker, size, status in lake.pull(conn, a.tickers):
            print(f"{ticker:15} {size:3} {status}")


if __name__ == "__main__":
    main()
