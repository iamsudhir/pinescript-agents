"""SQLite storage for the workbench: strategies, code versions, runs, optimizations,
insights and cached price bars. Plain functions over sqlite3, no ORM."""
import json
import os
import re
import sqlite3
from datetime import datetime

import pandas as pd

from . import ROOT

STATUSES = ["idea", "testing", "promising", "rejected", "live"]
BAR_COLS = ["Open", "High", "Low", "Close", "Volume"]
MARKET = ("ticker", "interval", "start", "end", "cash", "commission")

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies(
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source TEXT,
    transcript TEXT,
    notes TEXT NOT NULL DEFAULT '[]',
    default_ticker TEXT NOT NULL DEFAULT '^NSEI',
    default_interval TEXT NOT NULL DEFAULT '1d',
    status TEXT NOT NULL DEFAULT 'idea',
    rating INTEGER,
    user_notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_versions(
    id INTEGER PRIMARY KEY,
    strategy_id INTEGER NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    pine_code TEXT NOT NULL,
    python_code TEXT NOT NULL,
    change_note TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(strategy_id, version)
);
CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY,
    strategy_version_id INTEGER NOT NULL REFERENCES strategy_versions(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL, interval TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
    cash REAL NOT NULL, commission REAL NOT NULL,
    params TEXT NOT NULL, stats TEXT NOT NULL, trades TEXT NOT NULL, equity TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS optimizations(
    id INTEGER PRIMARY KEY,
    strategy_version_id INTEGER NOT NULL REFERENCES strategy_versions(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL, interval TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
    cash REAL NOT NULL, commission REAL NOT NULL,
    ranges TEXT NOT NULL, maximize TEXT NOT NULL, results TEXT NOT NULL,
    best_params TEXT NOT NULL, best_value REAL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS insights(
    id INTEGER PRIMARY KEY,
    strategy_id INTEGER NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    content TEXT NOT NULL, run_ids TEXT NOT NULL, optimization_ids TEXT NOT NULL,
    model TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS price_bars(
    ticker TEXT NOT NULL, interval TEXT NOT NULL, ts TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY(ticker, interval, ts)
);
CREATE TABLE IF NOT EXISTS price_fetches(
    ticker TEXT NOT NULL, interval TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
    PRIMARY KEY(ticker, interval, start_date, end_date)
);
CREATE INDEX IF NOT EXISTS runs_by_version ON runs(strategy_version_id);
CREATE INDEX IF NOT EXISTS opts_by_version ON optimizations(strategy_version_id);
"""

JSON_COLS = {"notes", "params", "stats", "trades", "equity", "ranges", "results", "best_params",
             "run_ids", "optimization_ids", "latest_stats"}
UPDATABLE = {"name", "status", "rating", "user_notes", "notes", "default_ticker", "default_interval"}


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect(path=None):
    """Open (and create if needed) the workbench DB: $WORKBENCH_DB or workbench.db in the repo."""
    conn = sqlite3.connect(path or os.environ.get("WORKBENCH_DB") or ROOT / "workbench.db",
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def _dict(row):
    if row is None:
        return None
    return {k: json.loads(row[k]) if k in JSON_COLS and row[k] is not None else row[k] for k in row.keys()}


def _all(conn, sql, args=()):
    return [_dict(r) for r in conn.execute(sql, args)]


def _one(conn, sql, args=()):
    return _dict(conn.execute(sql, args).fetchone())


# --- strategies ---------------------------------------------------------------

def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower())[:60].strip("-") or "strategy"


def create_strategy(conn, name, source_type, source=None, transcript=None, notes=None,
                    pine_code="", python_code="", change_note="generated"):
    """Insert a strategy and its first code version; returns the strategy id."""
    base = slug = slugify(name)
    n = 2
    while conn.execute("SELECT 1 FROM strategies WHERE slug=?", (slug,)).fetchone():
        slug, n = f"{base}-{n}", n + 1
    ts = now()
    with conn:
        sid = conn.execute(
            "INSERT INTO strategies(slug, name, source_type, source, transcript, notes, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (slug, name, source_type, source, transcript, json.dumps(notes or []), ts, ts)).lastrowid
        _insert_version(conn, sid, pine_code, python_code, change_note)
    return sid


def update_strategy(conn, strategy_id, **fields):
    bad = set(fields) - UPDATABLE
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
    if not fields:
        return
    if "notes" in fields:
        fields["notes"] = json.dumps(fields["notes"])
    sets = ", ".join(f"{k}=?" for k in fields)
    with conn:
        conn.execute(f"UPDATE strategies SET {sets}, updated_at=? WHERE id=?",
                     (*fields.values(), now(), strategy_id))


def get_strategy(conn, strategy_id=None, slug=None):
    if slug is not None:
        return _one(conn, "SELECT * FROM strategies WHERE slug=?", (slug,))
    return _one(conn, "SELECT * FROM strategies WHERE id=?", (strategy_id,))


def delete_strategy(conn, strategy_id):
    """Deletes the strategy and (via ON DELETE CASCADE) its versions, runs, optimizations, insights."""
    with conn:
        conn.execute("DELETE FROM strategies WHERE id=?", (strategy_id,))


def sources(conn, source_type):
    return {r[0] for r in conn.execute("SELECT source FROM strategies WHERE source_type=?", (source_type,))}


def list_strategies(conn, status=None, min_rating=None, search=None):
    """Library rows with run count, latest run stats and latest optimization's best value."""
    where, args = [], []
    if status:
        where.append("s.status=?")
        args.append(status)
    if min_rating:
        where.append("s.rating>=?")
        args.append(min_rating)
    if search:
        where.append("s.name LIKE ?")
        args.append(f"%{search}%")
    of_strategy = "JOIN strategy_versions v ON v.id = x.strategy_version_id WHERE v.strategy_id = s.id"
    return _all(conn, f"""
        SELECT s.id, s.slug, s.name, s.source_type, s.status, s.rating, s.created_at,
          (SELECT COUNT(*) FROM runs x {of_strategy}) AS n_runs,
          (SELECT x.stats FROM runs x {of_strategy} ORDER BY x.id DESC LIMIT 1) AS latest_stats,
          (SELECT x.maximize FROM optimizations x {of_strategy} ORDER BY x.id DESC LIMIT 1) AS opt_maximize,
          (SELECT x.best_value FROM optimizations x {of_strategy} ORDER BY x.id DESC LIMIT 1) AS opt_best
        FROM strategies s {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY s.updated_at DESC, s.id DESC""", args)


# --- versions -----------------------------------------------------------------

def _insert_version(conn, strategy_id, pine_code, python_code, change_note):
    """Caller owns the transaction (`with conn:`)."""
    ts = now()
    version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM strategy_versions WHERE strategy_id=?",
                           (strategy_id,)).fetchone()[0]
    vid = conn.execute(
        "INSERT INTO strategy_versions(strategy_id, version, pine_code, python_code, change_note, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (strategy_id, version, pine_code, python_code, change_note, ts)).lastrowid
    conn.execute("UPDATE strategies SET updated_at=? WHERE id=?", (ts, strategy_id))
    return vid


def add_version(conn, strategy_id, pine_code, python_code, change_note):
    with conn:
        return _insert_version(conn, strategy_id, pine_code, python_code, change_note)


def list_versions(conn, strategy_id):
    return _all(conn, "SELECT id, version, change_note, created_at FROM strategy_versions"
                      " WHERE strategy_id=? ORDER BY version DESC", (strategy_id,))


def get_version(conn, version_id):
    return _one(conn, "SELECT * FROM strategy_versions WHERE id=?", (version_id,))


def latest_version(conn, strategy_id):
    return _one(conn, "SELECT * FROM strategy_versions WHERE strategy_id=? ORDER BY version DESC LIMIT 1",
                (strategy_id,))


# --- runs, optimizations, insights --------------------------------------------
# `market` is a dict with the keys in MARKET: ticker, interval, start, end ('YYYY-MM-DD'), cash, commission.

_RUN = ("r.id, r.strategy_version_id, v.version, v.strategy_id, r.ticker, r.interval, r.start_date,"
        " r.end_date, r.cash, r.commission, r.params, r.stats, r.note, r.created_at")
_OPT = ("o.id, o.strategy_version_id, v.version, v.strategy_id, o.ticker, o.interval, o.start_date,"
        " o.end_date, o.cash, o.commission, o.ranges, o.maximize, o.best_params, o.best_value, o.note, o.created_at")
NOTE_TABLES = {"runs", "optimizations"}


def save_run(conn, version_id, market, params, stats, trades, equity):
    with conn:
        return conn.execute(
            "INSERT INTO runs(strategy_version_id, ticker, interval, start_date, end_date, cash, commission,"
            " params, stats, trades, equity, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (version_id, *(market[k] for k in MARKET), json.dumps(params), json.dumps(stats),
             json.dumps(trades), json.dumps(equity), now())).lastrowid


def list_runs(conn, strategy_id):
    """Newest first, without the bulky trades/equity columns."""
    return _all(conn, f"SELECT {_RUN} FROM runs r JOIN strategy_versions v ON v.id = r.strategy_version_id"
                      " WHERE v.strategy_id=? ORDER BY r.id DESC", (strategy_id,))


def get_run(conn, run_id):
    return _one(conn, f"SELECT {_RUN}, r.trades, r.equity FROM runs r"
                      " JOIN strategy_versions v ON v.id = r.strategy_version_id WHERE r.id=?", (run_id,))


def save_optimization(conn, version_id, market, ranges, maximize, results, best_params, best_value):
    with conn:
        return conn.execute(
            "INSERT INTO optimizations(strategy_version_id, ticker, interval, start_date, end_date, cash,"
            " commission, ranges, maximize, results, best_params, best_value, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (version_id, *(market[k] for k in MARKET), json.dumps(ranges), maximize, json.dumps(results),
             json.dumps(best_params), best_value, now())).lastrowid


def list_optimizations(conn, strategy_id):
    """Newest first, without the per-combination results."""
    return _all(conn, f"SELECT {_OPT} FROM optimizations o JOIN strategy_versions v ON v.id = o.strategy_version_id"
                      " WHERE v.strategy_id=? ORDER BY o.id DESC", (strategy_id,))


def get_optimization(conn, opt_id):
    return _one(conn, f"SELECT {_OPT}, o.results FROM optimizations o"
                      " JOIN strategy_versions v ON v.id = o.strategy_version_id WHERE o.id=?", (opt_id,))


def set_note(conn, table, row_id, note):
    if table not in NOTE_TABLES:
        raise ValueError(f"notes live on {sorted(NOTE_TABLES)}, not {table}")
    with conn:
        conn.execute(f"UPDATE {table} SET note=? WHERE id=?", (note, row_id))


def save_insight(conn, strategy_id, content, run_ids, optimization_ids, model):
    with conn:
        return conn.execute(
            "INSERT INTO insights(strategy_id, content, run_ids, optimization_ids, model, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (strategy_id, content, json.dumps(run_ids), json.dumps(optimization_ids), model, now())).lastrowid


def list_insights(conn, strategy_id):
    return _all(conn, "SELECT * FROM insights WHERE strategy_id=? ORDER BY id DESC", (strategy_id,))


# --- price cache --------------------------------------------------------------
# Timestamps are stored as naive ISO strings in exchange-local time, so string
# comparison against 'YYYY-MM-DD' dates works: ts >= start AND ts < end.

def upsert_bars(conn, ticker, interval, df):
    rows = [(ticker, interval, ts.isoformat(), *map(float, row))
            for ts, row in zip(df.index, df[BAR_COLS].itertuples(index=False))]
    with conn:
        conn.executemany("INSERT OR REPLACE INTO price_bars VALUES (?,?,?,?,?,?,?,?)", rows)


def get_bars(conn, ticker, interval, start, end):
    rows = conn.execute("SELECT ts, open, high, low, close, volume FROM price_bars"
                        " WHERE ticker=? AND interval=? AND ts>=? AND ts<? ORDER BY ts",
                        (ticker, interval, start, end)).fetchall()
    return pd.DataFrame([tuple(r)[1:] for r in rows], columns=BAR_COLS,
                        index=pd.to_datetime([r[0] for r in rows]))


def fetch_covered(conn, ticker, interval, start, end):
    return conn.execute("SELECT 1 FROM price_fetches WHERE ticker=? AND interval=? AND start_date<=? AND end_date>=?",
                        (ticker, interval, start, end)).fetchone() is not None


def log_fetch(conn, ticker, interval, start, end):
    with conn:
        conn.execute("INSERT OR IGNORE INTO price_fetches VALUES (?,?,?,?)", (ticker, interval, start, end))
