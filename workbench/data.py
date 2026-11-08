"""Price data. NSE (when LAKE_ROOT or DHAN_ACCESS_TOKEN is set): the local MyHFTAlgoBot lake, then the Dhan API
for newer bars. Everything else: yfinance. API downloads are cached in the workbench DB."""
import datetime as dt
import os

import pandas as pd
import yfinance as yf

from . import db, dhan, lake

INTERVALS = ["1d", "1wk", "1h", "30m", "15m", "5m", "3m"]


OHLCV = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
# App interval -> (Dhan candle size, resample args). Resampled bins line up with the NSE 9:15 open.
DHAN = {"1d": ("1d", None), "1wk": ("1d", dict(rule="W-MON", label="left", closed="left")),
        "1h": ("1h", None), "30m": ("15m", dict(rule="30min", offset="15min")),
        "15m": ("15m", None), "5m": ("5m", None), "3m": ("1m", dict(rule="3min"))}
# Same from the lake, which holds 5m and daily bars only (3m needs 1m bars, so it always comes from the API).
LAKE = {"1d": ("1d", None), "1wk": DHAN["1wk"], "1h": ("5m", dict(rule="1h", offset="15min")),
        "30m": ("5m", DHAN["30m"][1]), "15m": ("5m", dict(rule="15min")), "5m": ("5m", None)}
# The regular session, as TradingView charts NSE. Dhan's minute bars also hold pre-open (9:05-9:10) and stray
# after-hours bars, which would move the session-anchored HTF bars. ponytail: drops the Diwali Muhurat hour too.
NSE_HOURS = ("09:15", "15:29")


class DataError(Exception):
    pass


def source(ticker):
    return "Dhan" if dhan.serves(ticker) else "yfinance"


def default_start(interval, ticker=""):
    """A start date the ticker's data source can serve for this interval."""
    if interval in ("1d", "1wk"):
        return "2015-01-01"
    if source(ticker) == "Dhan":  # 5 years are available; one keeps the first download quick
        return (dt.date.today() - dt.timedelta(days=365)).isoformat()
    # yfinance keeps ~730 days of 1h, ~60 days of 5m-30m and ~30 days of 1m (which 3m is built from)
    days = {"1h": 700, "3m": 28}.get(interval, 55)
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def load_data(conn, ticker, interval, start, end):
    """OHLCV bars in [start, end) ('YYYY-MM-DD') as a DataFrame backtesting.py accepts.
    End is capped at today: today's bar is still forming, so it is never used or cached."""
    end = min(end, dt.date.today().isoformat())
    if start >= end:
        raise DataError(f"Start {start} must be before end {end}.")
    if source(ticker) == "Dhan":
        df = _dhan(conn, ticker, interval, start, end)
    else:
        df = _cached(conn, ticker, interval, start, end, lambda: _download(ticker, interval, start, end))
    if df.empty:
        raise DataError(f"No bars for {ticker} ({interval}) between {start} and {end}.")
    return df


def _cached(conn, key, interval, start, end, fetch):
    if not db.fetch_covered(conn, key, interval, start, end):
        db.upsert_bars(conn, key, interval, fetch())
        db.log_fetch(conn, key, interval, start, end)
    return db.get_bars(conn, key, interval, start, end)


def _dhan(conn, ticker, interval, start, end):
    """Lake bars where the lake has them, then the Dhan API (cached) from the day after the lake's last bar."""
    try:
        size, how = LAKE.get(interval, (None, None))
        df = lake.bars(conn, ticker, size, start, end)
        df = df.between_time(*NSE_HOURS) if size == "5m" else df
        df = _resample(df, **how) if how else df
        gap = start if df.empty else (df.index[-1].normalize() + pd.Timedelta(days=1)).date().isoformat()
        if gap < end and os.environ.get("DHAN_ACCESS_TOKEN"):
            api = _cached(conn, f"dhan:{ticker}", interval, gap, end, lambda: _dhan_api(conn, ticker, interval, gap, end))
            df = pd.concat([df, api]) if not df.empty else api
    except dhan.DhanError as e:
        raise DataError(str(e)) from e
    if df.empty:
        raise DataError(f"No {interval} bars for {ticker} between {start} and {end}: it isn't in the lake "
                        f"(python -m workbench lake-pull {ticker}) and DHAN_ACCESS_TOKEN in .env is "
                        f"{'set' if os.environ.get('DHAN_ACCESS_TOKEN') else 'empty'}.")
    return df


def _resample(df, rule, **kw):
    return df.resample(rule, **kw).agg(OHLCV).dropna() if not df.empty else df


def _dhan_api(conn, ticker, interval, start, end):
    size, how = DHAN[interval]
    df = dhan.candles(conn, ticker, size, start, end)
    df = df.between_time(*NSE_HOURS) if size != "1d" else df
    return _resample(df, **how) if how else df


def _download(ticker, interval, start, end):
    if interval == "3m":
        # yfinance has no 3m bars: build them from 1m, which it serves at most 8 days per request.
        # 3-minute bins counted from midnight line up with the NSE (9:15) and US (9:30) opens.
        edges = [*pd.date_range(start, end, freq="7D").strftime("%Y-%m-%d"), end]
        parts = [_fetch(ticker, "1m", a, b) for a, b in zip(edges, edges[1:]) if a < b]
        df = _resample(pd.concat([p for p in parts if not p.empty] or [pd.DataFrame()]), "3min")
    else:
        df = _fetch(ticker, interval, start, end)
    if df.empty:
        raise DataError(
            f"No data for {ticker} ({interval}, {start} -> {end}). Check the ticker: NSE stocks need .NS "
            "(RELIANCE.NS), indices start with ^ (^NSEI). Intraday must be recent: yfinance keeps "
            "~30 days of 1m (used for 3m), ~60 days of 5m-30m bars and ~2 years of 1h.")
    return df


def _fetch(ticker, interval, start, end):
    df = yf.download(ticker, start=start, end=end, interval=interval, auto_adjust=True,
                     progress=False, multi_level_index=False)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[db.BAR_COLS].dropna()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)  # keep exchange-local wall-clock time
    return df
