"""Price data: yfinance downloads cached in the workbench DB. A Dhan source can plug in here later."""
import datetime as dt

import yfinance as yf

from . import db

INTERVALS = ["1d", "1wk", "1h", "30m", "15m", "5m"]


class DataError(Exception):
    pass


def default_start(interval):
    """A start date yfinance can serve for this interval."""
    if interval in ("1d", "1wk"):
        return "2015-01-01"
    days = 700 if interval == "1h" else 55  # yfinance keeps ~730 days of 1h, ~60 days of 5m-30m
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def load_data(conn, ticker, interval, start, end):
    """OHLCV bars in [start, end) ('YYYY-MM-DD') as a DataFrame backtesting.py accepts.
    End is capped at today: today's bar is still forming, so it is never used or cached."""
    end = min(end, dt.date.today().isoformat())
    if start >= end:
        raise DataError(f"Start {start} must be before end {end}.")
    if not db.fetch_covered(conn, ticker, interval, start, end):
        db.upsert_bars(conn, ticker, interval, _download(ticker, interval, start, end))
        db.log_fetch(conn, ticker, interval, start, end)
    df = db.get_bars(conn, ticker, interval, start, end)
    if df.empty:
        raise DataError(f"No bars for {ticker} ({interval}) between {start} and {end}.")
    return df


def _download(ticker, interval, start, end):
    df = yf.download(ticker, start=start, end=end, interval=interval, auto_adjust=True,
                     progress=False, multi_level_index=False)
    if df is None or df.empty:
        raise DataError(
            f"No data for {ticker} ({interval}, {start} -> {end}). Check the ticker: NSE stocks need .NS "
            "(RELIANCE.NS), indices start with ^ (^NSEI). Intraday must be recent: yfinance keeps "
            "~60 days of 5m-30m bars and ~2 years of 1h.")
    df = df[db.BAR_COLS].dropna()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)  # keep exchange-local wall-clock time
    return df
