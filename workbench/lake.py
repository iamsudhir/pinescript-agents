"""Bars from a local copy of MyHFTAlgoBot's Parquet lake (8 years of 5m, 10 of daily, Dhan feed).

    <LAKE_ROOT>/bars/5m/segment=NSE_EQ/security_id=2859/year=2026/part.parquet

`ts` is tz-naive IST wall clock. Only the symbols you need are copied, by `python -m workbench lake-pull`."""
import os
import subprocess

import pandas as pd

from . import ROOT, dhan

COLS = ["ts", "open", "high", "low", "close", "volume"]
SIZES = ("5m", "1d")  # what the lake holds


def _empty():
    return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"], index=pd.DatetimeIndex([]), dtype=float)


def root():
    r = os.environ.get("LAKE_ROOT")
    return ROOT / r if r else None  # relative paths are relative to the project; absolute ones win


def bars(conn, ticker, size, start, end):
    """OHLCV in [start, end) from the lake; empty when the symbol, size or years aren't there."""
    if root() is None or size not in SIZES:
        return _empty()
    sid, segment, _ = dhan.security(conn, ticker)
    base = root() / "bars" / size / f"segment={segment}" / f"security_id={sid}"
    files = [f for y in range(int(start[:4]), int(end[:4]) + 1) if (f := base / f"year={y}" / "part.parquet").is_file()]
    if not files:
        return _empty()
    df = pd.concat(pd.read_parquet(f, columns=COLS) for f in files).set_index("ts").sort_index()
    df.index = pd.DatetimeIndex(df.index, name=None)
    df = df.rename(columns=str.capitalize).astype(float)
    return df[(df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end))]


def pull(conn, tickers):
    """Copy each ticker's 5m and daily years from LAKE_REMOTE (user@host:/path/to/data) with scp."""
    remote, local = os.environ.get("LAKE_REMOTE"), root()
    if not remote or local is None:
        raise ValueError("Set LAKE_ROOT and LAKE_REMOTE in .env first.")
    for ticker in tickers:
        try:
            sid, segment, _ = dhan.security(conn, ticker)
        except dhan.DhanError as e:  # unknown or renamed symbol: report it, pull the rest
            yield ticker, "-", str(e)
            continue
        for size in SIZES:
            dest = local / "bars" / size / f"segment={segment}"
            dest.mkdir(parents=True, exist_ok=True)
            src = f"{remote}/bars/{size}/segment={segment}/security_id={sid}"
            ok = subprocess.run(["scp", "-r", "-q", src, str(dest)]).returncode == 0
            yield ticker, size, "ok" if ok else "FAILED (see scp error above)"
