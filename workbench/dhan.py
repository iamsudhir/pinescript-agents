"""Dhan v2 historical candles for NSE stocks (RELIANCE.NS) and the Nifty indices (^NSEI, ^NSEBANK).
Used instead of yfinance when DHAN_ACCESS_TOKEN or LAKE_ROOT is set (see lake.py): years of intraday history."""
import csv
import datetime as dt
import io
import json
import os
import time
import urllib.error
import urllib.request

import pandas as pd

API = "https://api.dhan.co/v2/charts/"
MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
INDICES = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY"}  # Yahoo index ticker -> Dhan index symbol
MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}     # Dhan's intraday candle sizes the app uses
CHUNK_DAYS = 85                                        # Dhan serves at most 90 days of intraday per request


class DhanError(Exception):
    pass


def serves(ticker):
    on = os.environ.get("DHAN_ACCESS_TOKEN") or os.environ.get("LAKE_ROOT")
    return bool(on) and (ticker.endswith(".NS") or ticker in INDICES)


def security(conn, ticker):
    """(security_id, exchange_segment, instrument) from Dhan's instrument list, cached in the DB."""
    key = f"IDX:{INDICES[ticker]}" if ticker in INDICES else ticker
    sql = "SELECT security_id, segment, instrument FROM dhan_symbols WHERE symbol=?"
    row = conn.execute(sql, (key,)).fetchone()
    if row is None:  # new listing, or the list was never loaded
        _load_master(conn)
        row = conn.execute(sql, (key,)).fetchone()
    if row is None:
        raise DhanError(f"{ticker} isn't in Dhan's NSE instrument list. Use the NSE symbol + .NS (RELIANCE.NS).")
    return tuple(row)


def _load_master(conn):
    """Keep NSE stocks (as SYMBOL.NS) and NSE indices (as IDX:NAME) from the ~30 MB instrument list."""
    with urllib.request.urlopen(MASTER_URL, timeout=120) as r:
        rows = csv.DictReader(io.TextIOWrapper(r, encoding="utf-8"))
        found = {}
        for x in rows:
            if x["SEM_EXM_EXCH_ID"] != "NSE":
                continue
            if x["SEM_INSTRUMENT_NAME"] == "EQUITY":
                key = x["SEM_TRADING_SYMBOL"] + ".NS"
                if key not in found or x["SEM_SERIES"] == "EQ":  # a symbol can list in several series
                    found[key] = (key, x["SEM_SMST_SECURITY_ID"], "NSE_EQ", "EQUITY")
            elif x["SEM_INSTRUMENT_NAME"] == "INDEX":
                key = "IDX:" + x["SEM_TRADING_SYMBOL"]
                found[key] = (key, x["SEM_SMST_SECURITY_ID"], "IDX_I", "INDEX")
    with conn:
        conn.executemany("INSERT OR REPLACE INTO dhan_symbols(symbol, security_id, segment, instrument)"
                         " VALUES (?,?,?,?)", found.values())


def candles(conn, ticker, size, start, end):
    """OHLCV in [start, end) ('YYYY-MM-DD'); size is '1d' or a key of MINUTES. Index is IST wall-clock time."""
    sid, segment, instrument = security(conn, ticker)
    body = {"securityId": sid, "exchangeSegment": segment, "instrument": instrument}
    if size == "1d":
        df = _frame(_post("historical", {**body, "expiryCode": 0, "oi": False, "fromDate": start, "toDate": end}))
        df.index = df.index.normalize()
        return df[df.index < pd.Timestamp(end)]
    parts, a, stop = [], dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    while a < stop:
        b = min(a + dt.timedelta(days=CHUNK_DAYS), stop)
        parts.append(_frame(_post("intraday", {**body, "interval": str(MINUTES[size]), "oi": False,
                                               "fromDate": f"{a} 00:00:00", "toDate": f"{b} 00:00:00"})))
        a = b
        time.sleep(0.25)  # Dhan allows 5 data requests a second
    df = pd.concat(parts)
    df = df[~df.index.duplicated()].sort_index()
    return df[(df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end))]


def _frame(js):
    if not js.get("timestamp"):
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"], index=pd.DatetimeIndex([]))
    idx = pd.to_datetime(js["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata").tz_localize(None)
    return pd.DataFrame({"Open": js["open"], "High": js["high"], "Low": js["low"], "Close": js["close"],
                         "Volume": js["volume"]}, index=idx).dropna()


def _post(kind, body):
    req = urllib.request.Request(API + kind, data=json.dumps(body).encode(), method="POST", headers={
        "access-token": os.environ["DHAN_ACCESS_TOKEN"], "client-id": os.environ.get("DHAN_CLIENT_ID", ""),
        "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        hint = ""
        if e.code in (401, 403) or "DH-901" in detail:
            hint = (" The access token is invalid or expired: generate a new one at web.dhan.co -> My Profile -> "
                    "Access DhanHQ APIs and update DHAN_ACCESS_TOKEN in .env.")
        elif "DH-902" in detail or "806" in detail:
            hint = " Historical data needs an active Data API plan on your Dhan account."
        raise DhanError(f"Dhan {kind} request failed (HTTP {e.code}): {detail}.{hint}") from e
    except urllib.error.URLError as e:
        raise DhanError(f"Can't reach Dhan ({e.reason}).") from e
