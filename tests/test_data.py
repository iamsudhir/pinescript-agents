import pandas as pd
import pytest

from workbench import data


def test_downloads_once_then_serves_from_cache(conn, goog, monkeypatch):
    calls = []

    def fake_download(ticker, start, end, interval, **kw):
        calls.append((ticker, start, end, interval))
        return goog[(goog.index >= start) & (goog.index < end)]

    monkeypatch.setattr(data.yf, "download", fake_download)
    a = data.load_data(conn, "GOOG", "1d", "2005-01-01", "2005-06-01")
    b = data.load_data(conn, "GOOG", "1d", "2005-02-01", "2005-03-01")
    assert calls == [("GOOG", "2005-01-01", "2005-06-01", "1d")]
    assert list(a.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(a) > len(b) > 0


def test_empty_download_raises_data_error(conn, monkeypatch):
    monkeypatch.setattr(data.yf, "download", lambda *a, **k: pd.DataFrame())
    with pytest.raises(data.DataError, match="No data for NOPE"):
        data.load_data(conn, "NOPE", "1d", "2020-01-01", "2020-02-01")


def test_start_after_end_raises(conn):
    with pytest.raises(data.DataError, match="before"):
        data.load_data(conn, "GOOG", "1d", "2020-02-01", "2020-01-01")


def test_tz_aware_bars_keep_exchange_local_time(conn, monkeypatch):
    idx = pd.date_range("2024-01-02 09:15", periods=3, freq="15min", tz="Asia/Kolkata")
    bars = pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10.0}, index=idx)
    monkeypatch.setattr(data.yf, "download", lambda *a, **k: bars)
    out = data.load_data(conn, "X.NS", "15m", "2024-01-02", "2024-01-03")
    assert str(out.index[0]) == "2024-01-02 09:15:00" and len(out) == 3


def test_default_start():
    assert data.default_start("1d") == "2015-01-01"
    assert data.default_start("15m") > "2015-01-01"
