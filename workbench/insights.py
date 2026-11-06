"""Per-strategy insights: a summary computed from saved runs, and Claude's analysis (stored)."""
import pandas as pd

from . import db, generate

RET, SHARPE, DD = "Return [%]", "Sharpe Ratio", "Max. Drawdown [%]"


def _num(x):
    return None if pd.isna(x) else float(x)


def _pick(df, col, largest=True):
    s = df[col].dropna()
    if s.empty:
        return None
    return int(df.loc[s.idxmax() if largest else s.idxmin(), "run_id"])


def summary(conn, strategy_id):
    """Computed on demand (never stored) so it always reflects every saved run."""
    runs = db.list_runs(conn, strategy_id)
    out = {"n_runs": len(runs)}
    if runs:
        df = pd.DataFrame([{"run_id": r["id"], "ticker": r["ticker"], "interval": r["interval"],
                            **{c: r["stats"].get(c) for c in (RET, SHARPE, DD)}} for r in runs])
        df[[RET, SHARPE, DD]] = df[[RET, SHARPE, DD]].astype(float)
        by_market = (df.groupby(["ticker", "interval"])
                     .agg(runs=("run_id", "count"),
                          pct_profitable=(RET, lambda x: 100 * (x.dropna() > 0).mean() if x.notna().any() else None),
                          avg_return=(RET, "mean"), avg_sharpe=(SHARPE, "mean"))
                     .reset_index())
        by_market = by_market.astype(object).where(by_market.notna(), None)  # NaN -> None: JSON-safe
        out.update(
            best_by_return=_pick(df, RET), worst_by_return=_pick(df, RET, largest=False),
            best_by_sharpe=_pick(df, SHARPE),
            mean={c: _num(df[c].mean()) for c in (RET, SHARPE, DD)},
            median={c: _num(df[c].median()) for c in (RET, SHARPE, DD)},
            by_market=by_market.to_dict("records"),
        )
    opts = db.list_optimizations(conn, strategy_id)
    out["stability"] = stability(db.get_optimization(conn, opts[0]["id"])) if opts else None
    return out


def stability(opt):
    """Share of tried combinations scoring within 80% of the best. Under 10% means the best
    result is a lone spike, which rarely survives new data."""
    # ponytail: one-number heuristic; add neighbour or walk-forward checks if it misleads.
    res = pd.DataFrame(opt["results"])
    m = opt["maximize"]
    if res.empty or m not in res:
        return None
    best = res[m].max()
    share = float((res[m] >= 0.8 * best).mean()) if best > 0 else None
    return {"optimization_id": opt["id"], "maximize": m, "best": _num(best), "combinations": len(res),
            "share_within_80pct": share, "likely_overfit": share is not None and share < 0.1}


def analyze(conn, strategy_id, run_ids=None):
    """Ask Claude to review the strategy's results; saves and returns the insight id.
    Default scope: the latest 20 runs and the latest optimization's top 20 combinations."""
    s = db.get_strategy(conn, strategy_id)
    runs = db.list_runs(conn, strategy_id)
    runs = [r for r in runs if r["id"] in run_ids] if run_ids else runs[:20]
    if not runs:
        raise ValueError("No runs to analyze yet — run a backtest first.")
    opts = [db.get_optimization(conn, o["id"]) for o in db.list_optimizations(conn, strategy_id)[:1]]
    payload = {
        "strategy": s["name"],
        "translation_notes": s["notes"],
        "user_notes": s["user_notes"],
        "summary": summary(conn, strategy_id),
        "runs": [{k: r[k] for k in ("id", "version", "ticker", "interval", "start_date", "end_date", "params",
                                    "stats", "note")} for r in runs],
        "optimizations": [{**{k: o[k] for k in ("id", "ticker", "interval", "start_date", "end_date", "ranges",
                                                "maximize", "best_params", "best_value", "note")},
                           "top_20": o["results"][:20]} for o in opts],
    }
    content = generate.analyze_results(db.get_version(conn, runs[0]["strategy_version_id"])["python_code"], payload)
    return db.save_insight(conn, strategy_id, content, [r["id"] for r in runs], [o["id"] for o in opts],
                           generate.model())
