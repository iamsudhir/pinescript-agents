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
