"""Load a generated strategy module and backtest / optimize it with backtesting.py."""
import json
import math
import os
import tempfile
import warnings
from dataclasses import dataclass

import pandas as pd
from backtesting import Backtest, Strategy

# backtesting.py warns on every Windows optimize (no fork) and on pandas deprecations: noise in the UI.
warnings.filterwarnings("ignore", module="backtesting")

KEY_STATS = ["Return [%]", "Buy & Hold Return [%]", "CAGR [%]", "Sharpe Ratio", "Max. Drawdown [%]",
             "Win Rate [%]", "# Trades", "Profit Factor", "Expectancy [%]", "Exposure Time [%]"]
MAXIMIZE = ["Sharpe Ratio", "Return [%]", "Return/MaxDD"]
TRADE_COLS = ["Size", "EntryTime", "ExitTime", "EntryPrice", "ExitPrice", "SL", "TP", "PnL", "ReturnPct", "Duration"]
_MODULE = "workbench_strategy"


class StrategyContractError(Exception):
    """Generated Python doesn't follow the strategy contract (see generate.CONTRACT)."""


def load_strategy(code):
    """Exec strategy code; return (its single Strategy subclass, {param: default})."""
    # ponytail: runs in-process with no sandbox. Fine for code from your own Claude account;
    # move to a subprocess before ever loading strategies from other people.
    ns = {"__name__": _MODULE}
    try:
        exec(compile(code, "strategy.py", "exec"), ns)
    except Exception as e:
        raise StrategyContractError(f"strategy.py failed to load: {type(e).__name__}: {e}") from e
    classes = [c for c in ns.values()
               if isinstance(c, type) and issubclass(c, Strategy) and c.__module__ == _MODULE]
    if len(classes) != 1:
        raise StrategyContractError("strategy.py must define exactly one backtesting.Strategy subclass, "
                                    f"found {len(classes)}: {[c.__name__ for c in classes]}")
    cls = classes[0]
    return cls, {k: v for k, v in vars(cls).items() if not k.startswith("_") and type(v) in (int, float, bool)}


def coerce(value, default):
    """Cast a UI / CLI / JSON value to the type of the parameter's default."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(float(value))
    return float(value)


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


@dataclass
class RunResult:
    params: dict          # full parameter set used (defaults + overrides)
    stats: dict           # KEY_STATS -> float or None
    trades: list          # JSON-ready trade records
    equity: list          # [[iso_ts, equity], ...]
    raw: pd.Series        # backtesting.py result, for charting
    bt: Backtest


def _backtest(cls, df, cash, commission):
    return Backtest(df, cls, cash=cash, commission=commission, finalize_trades=True)


def run(code, df, params=None, cash=1_000_000, commission=0.0005):
    cls, defaults = load_strategy(code)
    full = {**defaults, **{k: coerce(v, defaults[k]) for k, v in (params or {}).items() if k in defaults}}
    bt = _backtest(cls, df, cash, commission)
    s = bt.run(**full)
    trades = s._trades[[c for c in TRADE_COLS if c in s._trades]].copy()
    trades["Duration"] = trades["Duration"].astype(str)
    stats = {k: _num(s[k]) for k in KEY_STATS}
    stats["# Trades"] = int(s["# Trades"])
    return RunResult(
        params=full,
        stats=stats,
        trades=json.loads(trades.to_json(orient="records", date_format="iso")),
        equity=[[ts.isoformat(), float(v)] for ts, v in s._equity_curve["Equity"].items()],
        raw=s,
        bt=bt,
    )


def chart_html(result):
    """backtesting.py's interactive Bokeh chart for a run, as an HTML string."""
    fd, path = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    try:
        result.bt.plot(results=result.raw, filename=path, open_browser=False)
        with open(path, encoding="utf-8") as f:
            return f.read()
    finally:
        os.remove(path)


def values(lo, hi, step, default):
    """Grid values for one parameter, typed like its default. Bools always try both."""
    if isinstance(default, bool):
        return [False, True]
    if isinstance(default, int):
        return list(range(int(lo), int(hi) + 1, max(1, int(step))))
    n = int((hi - lo) / step + 1e-9) + 1 if step > 0 else 0
    return [round(lo + i * step, 10) for i in range(n)]


def grid_size(ranges, defaults):
    return math.prod(len(values(*r, defaults[k])) for k, r in ranges.items()) if ranges else 0


def default_range(d):
    """Starting (min, max, step) offered in the UI for a parameter's default value."""
    if isinstance(d, int):
        return (d // 2, d * 2, max(1, d // 5)) if d > 0 else (0, 10, 1)
    return (d / 2, d * 2, round(d / 10, 10)) if d > 0 else (0.0, 1.0, 0.1)


def return_over_maxdd(stats):
    dd = abs(stats["Max. Drawdown [%]"])
    return stats["Return [%]"] / dd if dd else float("nan")


@dataclass
class OptResult:
    results: pd.DataFrame  # one row per tried combination: params + the maximized metric, best first
    best_params: dict
    best_value: float | None


def optimize(code, df, ranges, maximize="Sharpe Ratio", cash=1_000_000, commission=0.0005, max_tries=500):
    """ranges: {param: (min, max, step)}. Unlisted params keep their defaults.
    Grids larger than max_tries are randomly sampled down to about max_tries combinations (seeded, so repeatable)."""
    cls, defaults = load_strategy(code)
    grid = {k: values(*r, defaults[k]) for k, r in ranges.items()}
    if not grid or not all(grid.values()):
        raise ValueError(f"Every optimized parameter needs at least one value: {grid}")
    n = math.prod(len(v) for v in grid.values())
    best, heat = _backtest(cls, df, cash, commission).optimize(
        **grid, maximize=return_over_maxdd if maximize == "Return/MaxDD" else maximize,
        return_heatmap=True, max_tries=max_tries if n > max_tries else None, random_state=0)
    results = (heat.rename(maximize).reset_index().dropna(subset=[maximize])
               .sort_values(maximize, ascending=False, ignore_index=True))
    if results.empty:  # nothing traded: backtesting.py's fallback "best" would be a fake
        return OptResult(results, {}, None)
    return OptResult(
        results=results,
        best_params={k: coerce(best._strategy._params[k], defaults[k]) for k in grid},
        best_value=_num(results[maximize].iloc[0]) if len(results) else None,
    )
