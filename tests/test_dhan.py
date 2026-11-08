import io
import json
import urllib.error

import pandas as pd
import pytest

from workbench import data, dhan

MASTER = """SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_EXPIRY_CODE,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,SEM_EXPIRY_FLAG,SEM_EXCH_INSTRUMENT_TYPE,SEM_SERIES,SM_SYMBOL_NAME
NSE,E,9999,EQUITY,0,RAYMOND,1.0,Raymond,,,,10.0000,NA,ES,BE,RAYMOND LTD
NSE,E,2859,EQUITY,0,RAYMOND,1.0,Raymond,,,,10.0000,NA,ES,EQ,RAYMOND LTD
BSE,E,500330,EQUITY,0,RAYMOND,1.0,Raymond,,,,10.0000,NA,ES,A,RAYMOND LTD
NSE,I,13,INDEX,0,NIFTY,1.0,Nifty 50,0001-01-01,,XX,0.0500,,INDEX,X,NIFTY
NSE,D,49081,FUTIDX,0,NIFTY-Nov2026-FUT,75.0,NIFTY NOV FUT,2026-11-26,-0.01,XX,0.05,M,FUTIDX,,NIFTY
"""


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "t")
    monkeypatch.setattr(dhan.time, "sleep", lambda s: None)


@pytest.fixture
def master(monkeypatch):
    monkeypatch.setattr(dhan.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(MASTER.encode()))


def candles_json(start, minutes, n):
    """n candles from start (IST wall clock), as Dhan sends them: epoch seconds."""
    ts = pd.date_range(start, periods=n, freq=f"{minutes}min", tz="Asia/Kolkata")
    close = list(range(1, n + 1))
    return {"timestamp": [int(t.timestamp()) for t in ts], "open": close, "high": close, "low": close,
            "close": close, "volume": [10] * n}


def test_serves_nse_only_with_a_token(monkeypatch):
    assert not dhan.serves("RAYMOND.NS")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "t")
    assert dhan.serves("RAYMOND.NS") and dhan.serves("^NSEI") and not dhan.serves("AAPL")
    assert data.source("AAPL") == "yfinance" and data.source("^NSEI") == "Dhan"


def test_security_prefers_eq_series_and_maps_indices(conn, master):
    assert dhan.security(conn, "RAYMOND.NS") == ("2859", "NSE_EQ", "EQUITY")
    assert dhan.security(conn, "^NSEI") == ("13", "IDX_I", "INDEX")
    with pytest.raises(dhan.DhanError, match="NOPE.NS isn't in"):
        dhan.security(conn, "NOPE.NS")


def test_intraday_is_fetched_in_chunks_and_converted_to_ist(conn, token, master, monkeypatch):
    bodies = []

    def fake_post(kind, body):
        bodies.append((kind, body))
        return candles_json(f"{body['fromDate'][:10]} 09:15", 1, 6)

    monkeypatch.setattr(dhan, "_post", fake_post)
    df = data.load_data(conn, "RAYMOND.NS", "3m", "2024-01-01", "2024-07-01")
    assert all(k == "intraday" and b["interval"] == "1" and b["securityId"] == "2859" for k, b in bodies)
    spans = [(pd.Timestamp(b["toDate"]) - pd.Timestamp(b["fromDate"])).days for _, b in bodies]
    assert len(bodies) == 3 and max(spans) <= 90
    first = df.loc["2024-01-01"]
    assert [str(t.time()) for t in first.index] == ["09:15:00", "09:18:00"]  # 1m -> 3m from the open
    assert first.Close.tolist() == [3, 6] and first.Volume.tolist() == [30, 30]


def test_30m_bars_start_at_the_nse_open(conn, token, master, monkeypatch):
    monkeypatch.setattr(dhan, "_post", lambda kind, body: candles_json("2024-01-01 09:15", 15, 4))
    df = data.load_data(conn, "RAYMOND.NS", "30m", "2024-01-01", "2024-01-02")
    assert [str(t.time()) for t in df.index] == ["09:15:00", "09:45:00"]


def test_daily_drops_bars_from_the_end_date_on(conn, token, master, monkeypatch):
    ts = pd.date_range("2024-01-01", periods=3, freq="D", tz="Asia/Kolkata")
    js = {"timestamp": [int(t.timestamp()) for t in ts], "open": [1, 2, 3], "high": [1, 2, 3],
          "low": [1, 2, 3], "close": [1, 2, 3], "volume": [1, 1, 1]}
    monkeypatch.setattr(dhan, "_post", lambda kind, body: js)
    df = data.load_data(conn, "^NSEI", "1d", "2024-01-01", "2024-01-03")
    assert [str(d.date()) for d in df.index] == ["2024-01-01", "2024-01-02"]


def test_dhan_and_yfinance_bars_are_cached_apart(conn, token, master, monkeypatch):
    monkeypatch.setattr(dhan, "_post", lambda kind, body: candles_json("2024-01-01 09:15", 15, 2))
    data.load_data(conn, "RAYMOND.NS", "15m", "2024-01-01", "2024-01-02")
    tickers = {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM price_bars")}
    assert tickers == {"dhan:RAYMOND.NS"}


def test_expired_token_explains_what_to_do(conn, token, master, monkeypatch):
    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {},
                                     io.BytesIO(json.dumps({"errorCode": "DH-901"}).encode()))

    dhan.security(conn, "RAYMOND.NS")  # load the master before urlopen starts refusing
    monkeypatch.setattr(dhan.urllib.request, "urlopen", refuse)
    with pytest.raises(data.DataError, match="generate a new one"):
        data.load_data(conn, "RAYMOND.NS", "5m", "2024-01-01", "2024-01-02")
