import pandas as pd
import pytest

from workbench import data, dhan
from tests.test_dhan import candles_json, master  # noqa: F401  (master is a fixture)


def write_lake(root, days):
    """5m bars 9:05-15:35 (pre-open and after-hours too) on each day, in MyHFTAlgoBot's layout, for RAYMOND (NSE_EQ:2859)."""
    ts = pd.DatetimeIndex([t for d in days for t in pd.date_range(f"{d} 09:05", f"{d} 15:35", freq="5min")])
    f = root / "bars/5m/segment=NSE_EQ/security_id=2859/year=2024/part.parquet"
    f.parent.mkdir(parents=True)
    pd.DataFrame({"ts": ts, "session_date": ts.normalize(), "open": 1.0, "high": 2.0, "low": 0.5,
                  "close": 1.5, "volume": 10}).to_parquet(f, index=False)


def test_lake_1h_bars_start_at_915_and_the_api_fills_days_after_the_lake(conn, master, tmp_path, monkeypatch):
    write_lake(tmp_path, ["2024-03-04", "2024-03-05"])
    monkeypatch.setenv("LAKE_ROOT", str(tmp_path))
    asked = []

    def fake_post(kind, body):
        asked.append(body["fromDate"])
        return candles_json(f"{body['fromDate'][:10]} 09:15", 60, 2)  # Dhan's own 1h bars

    monkeypatch.setattr(dhan, "_post", fake_post)
    assert data.source("RAYMOND.NS") == "Dhan"

    df = data.load_data(conn, "RAYMOND.NS", "1h", "2024-03-04", "2024-03-07")  # no token: lake only
    assert asked == [] and list(df.index.strftime("%H:%M")[:7]) == \
        ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]
    assert len(df) == 14 and df["Volume"].iloc[0] == 120  # 12 five-minute bars

    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "t")
    monkeypatch.setattr(dhan.time, "sleep", lambda s: None)
    df = data.load_data(conn, "RAYMOND.NS", "1h", "2024-03-04", "2024-03-07")
    assert asked == ["2024-03-06 00:00:00"]  # only the day the lake doesn't have
    assert df.index[-1] == pd.Timestamp("2024-03-06 10:15") and len(df) == 16


def test_symbol_missing_from_lake_without_token_says_how_to_get_it(conn, master, tmp_path, monkeypatch):
    monkeypatch.setenv("LAKE_ROOT", str(tmp_path))
    with pytest.raises(data.DataError, match=r"lake-pull RAYMOND.NS\) and DHAN_ACCESS_TOKEN in .env is empty"):
        data.load_data(conn, "RAYMOND.NS", "5m", "2024-03-04", "2024-03-07")
