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
    res = engine.run(SMA_CODE, goog, {"n1": "5", "unknown": 1}, cash=100_000, commission=0.0)
    assert res.params == {"n1": 5, "n2": 20, "use_exit": True, "stop_pct": 0.0}
    assert list(res.stats) == engine.KEY_STATS
    assert res.stats["# Trades"] == len(res.trades) > 0
    assert res.trades[0]["EntryTime"].startswith("20") and isinstance(res.trades[0]["Duration"], str)
    assert len(res.equity) == len(goog) and res.equity[0][1] == 100_000


def test_params_change_the_result(goog):
    assert engine.run(SMA_CODE, goog, {"n1": 5}).stats != engine.run(SMA_CODE, goog, {"n1": 15}).stats


def test_chart_html(goog):
    assert "<html" in engine.chart_html(engine.run(SMA_CODE, goog)).lower()
