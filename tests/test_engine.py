import pytest
from conftest import SMA_CODE

from workbench import engine


def test_load_strategy_finds_public_numeric_params():
    cls, params = engine.load_strategy(SMA_CODE)
    assert cls.__name__ == "SmaCross"
    assert params == {"n1": 10, "n2": 20, "use_exit": True, "stop_pct": 0.0}


@pytest.mark.parametrize("code,message", [
    ("x = 1", "found 0"),
    (SMA_CODE + "\n\nclass Other(SmaCross):\n    pass\n", "found 2"),
    ("def broken(:\n", "failed to load"),
    ("import not_a_real_module_xyz", "failed to load"),
])
def test_load_strategy_rejects_contract_violations(code, message):
    with pytest.raises(engine.StrategyContractError, match=message):
        engine.load_strategy(code)


def test_coerce_to_default_type():
    assert engine.coerce("12", 10) == 12
    assert engine.coerce(3.0, 10) == 3 and isinstance(engine.coerce(3.0, 10), int)
    assert engine.coerce("2.5", 1.0) == 2.5
    assert engine.coerce("false", True) is False and engine.coerce("yes", False) is True


def test_run_returns_params_stats_trades_equity(goog):
    res = engine.run(SMA_CODE, goog, {"n1": "5"}, cash=100_000, commission=0.0)
    assert res.params == {"n1": 5, "n2": 20, "use_exit": True, "stop_pct": 0.0}
    assert list(res.stats) == engine.KEY_STATS
    assert res.stats["# Trades"] == len(res.trades) > 0
    assert isinstance(res.stats["# Trades"], int)
    assert res.trades[0]["EntryTime"].startswith("20") and isinstance(res.trades[0]["Duration"], str)
    assert len(res.equity) == len(goog) and res.equity[0][1] == 100_000


def test_run_rejects_unknown_params(goog):
    with pytest.raises(ValueError, match="unknown parameters.*nope"):
        engine.run(SMA_CODE, goog, {"n1": 5, "nope": 1})


def test_params_change_the_result(goog):
    assert engine.run(SMA_CODE, goog, {"n1": 5}).stats != engine.run(SMA_CODE, goog, {"n1": 15}).stats


def test_chart_html(goog):
    assert "<html" in engine.chart_html(engine.run(SMA_CODE, goog)).lower()


def test_values_and_grid_size():
    assert engine.values(5, 15, 5, 10) == [5, 10, 15]
    assert engine.values(0.5, 1.0, 0.25, 1.0) == [0.5, 0.75, 1.0]
    assert engine.values(0, 1, 1, True) == [False, True]
    assert engine.values(10, 5, 1, 3) == []
    assert engine.values(0, 1, 0.6, 0.2) == [0.0, 0.6]
    assert engine.grid_size({"n1": (5, 15, 5), "use_exit": (0, 1, 1)}, {"n1": 10, "use_exit": True}) == 6
    assert engine.grid_size({}, {"n1": 10}) == 0


def test_default_range():
    assert engine.default_range(10) == (5, 20, 2)
    assert engine.default_range(0) == (0, 10, 1)
    assert engine.default_range(2.0) == (1.0, 4.0, 0.2)


def test_optimize_returns_one_row_per_combination(goog):
    res = engine.optimize(SMA_CODE, goog, {"n1": (5, 15, 5), "use_exit": (0, 1, 1)}, maximize="Return/MaxDD")
    assert list(res.results.columns) == ["n1", "use_exit", "Return/MaxDD"]
    assert 0 < len(res.results) <= 6
    assert res.results["Return/MaxDD"].is_monotonic_decreasing
    assert res.best_value == res.results["Return/MaxDD"].iloc[0]
    assert set(res.best_params) == {"n1", "use_exit"}
    assert type(res.best_params["n1"]) is int and type(res.best_params["use_exit"]) is bool


def test_optimize_rejects_empty_range(goog):
    with pytest.raises(ValueError, match="at least one value"):
        engine.optimize(SMA_CODE, goog, {"n1": (10, 5, 1)})


def test_optimize_with_no_result_has_no_fake_best(goog):
    res = engine.optimize(SMA_CODE, goog, {"n1": (3000, 3002, 1)})
    assert res.results.empty and res.best_params == {} and res.best_value is None


def test_optimize_samples_large_grids(goog):
    res = engine.optimize(SMA_CODE, goog, {"n1": (5, 15, 5), "use_exit": (0, 1, 1)}, max_tries=3)
    assert 0 < len(res.results) <= 6
    assert set(res.best_params) == {"n1", "use_exit"}


@pytest.mark.parametrize("code", [
    "import os",
    "from subprocess import run",
    "import numpy as np\nimport socket",
    "x = open('f')",
    "exec('1')",
    "y = getattr(int, 'real')",
])
def test_load_strategy_rejects_io_and_dynamic_code(code):
    with pytest.raises(engine.StrategyContractError, match="not allowed"):
        engine.load_strategy(code)


@pytest.mark.parametrize("code", [
    "x = __builtins__.__import__('os')",
    "import pandas as pd\nx = pd.io.common.os.getcwd()",
    "x = ().__class__",
    "import numpy as np\nx = np.sys",
])
def test_load_strategy_rejects_escape_routes(code):
    with pytest.raises(engine.StrategyContractError, match="not allowed"):
        engine.load_strategy(code)


def test_load_strategy_allows_super_init():
    engine.load_strategy(SMA_CODE + "\n    def __init__(self, *a, **k):\n        super().__init__(*a, **k)\n")


def test_load_strategy_still_accepts_reference_code():
    from workbench import generate
    engine.load_strategy(generate.REFERENCE_PY)
    engine.load_strategy("import math\nimport pandas as pd\nimport numpy as np\n" + SMA_CODE)


def test_load_strategy_wraps_system_exit():
    with pytest.raises(engine.StrategyContractError, match="failed to load"):
        engine.load_strategy("raise SystemExit(1)")
