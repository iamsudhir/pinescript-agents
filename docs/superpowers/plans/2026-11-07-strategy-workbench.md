# Strategy Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local Streamlit app + CLI where a YouTube URL, a description, or an existing `.pine` file becomes a Pine Script v6 strategy and an equivalent backtesting.py strategy; every version, backtest, optimization and insight is stored in SQLite.

**Architecture:** A small `workbench/` package with one job per module (`db` storage, `data` prices, `engine` backtests, `generate` Claude calls, `insights` analysis, `actions` use cases shared by UI and CLI). Streamlit pages in `ui/` and the CLI in `workbench/__main__.py` only call `actions`/`db`. Spec: `docs/superpowers/specs/2026-11-07-strategy-workbench-design.md`.

**Tech Stack:** Python 3.14, sqlite3 (stdlib), pandas, backtesting 0.6.6, yfinance 1.8, anthropic 2.6 (structured outputs, streaming), streamlit 1.67 (+ altair, bundled), python-dotenv, pytest.

**Conventions for every task**
- Work in `D:\Python Pursuit\Strategy tester\pinescript-agents` on branch `strategy-workbench`. Shell examples are Git Bash.
- Python is the venv: `.venv/Scripts/python.exe` (abbreviated `PY` below: run `PY=.venv/Scripts/python.exe` once per shell).
- Commit messages end with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never `git add -A`: the working tree has unrelated uncommitted changes (`setup.sh`, `.claude/settings.local.json`). Add the files each task names.

## File map

| File | Responsibility |
|---|---|
| `workbench/__init__.py` | `ROOT` path of the repo |
| `workbench/db.py` | SQLite schema + all reads/writes |
| `workbench/data.py` | `load_data()`: yfinance download cached in `price_bars` |
| `workbench/engine.py` | load strategy code, `run`, `optimize`, `chart_html` |
| `workbench/generate.py` | Claude calls (generate / fix / analyze), contract + reference example, Pine lint |
| `workbench/insights.py` | computed summary, stability heuristic, Claude analysis saved to DB |
| `workbench/actions.py` | use cases: create/import, backtest, optimize, chart for a saved run |
| `workbench/__main__.py` | CLI `python -m workbench ...` |
| `app.py` | Streamlit entry: navigation only |
| `ui/library.py`, `ui/create.py`, `ui/strategy.py` | Streamlit pages |
| `tests/conftest.py` + `tests/test_*.py` | pytest, offline (GOOG data ships with backtesting.py) |
| `pytest.ini`, `.env.example`, `requirements.txt`, `.gitignore`, `SETUP.md` | setup/docs |

---

### Task 1: Project setup

**Files:**
- Create: `workbench/__init__.py`, `tests/conftest.py`, `pytest.ini`, `.env.example`
- Modify: `requirements.txt` (append), `.gitignore` (append)

- [ ] **Step 1: Install dependencies into the venv**

Append to `requirements.txt`:

```
# Strategy workbench (streamlit run app.py)
streamlit>=1.67
anthropic>=2.6
yfinance>=1.8
backtesting>=0.6.6
python-dotenv>=1.2
pytest>=9.0
```

Run: `$PY -m pip install -r requirements.txt`
Expected: ends without errors (already installed packages print "Requirement already satisfied").

- [ ] **Step 2: Append to `.gitignore`**

```
# Strategy workbench database (SQLite + WAL files)
workbench.db*
.pytest_cache/
```

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 4: Create `.env.example`**

```
# Copy to .env and fill in. .env is gitignored.
ANTHROPIC_API_KEY=
# Optional: model for generation and analysis (default claude-opus-5-5)
# ANTHROPIC_MODEL=claude-opus-5-5
# Optional: database file (default workbench.db in this folder)
# WORKBENCH_DB=
# Optional: 1 = never call Claude; generation returns a fixed EMA-cross example
# WORKBENCH_DRY_RUN=1
```

- [ ] **Step 5: Create `workbench/__init__.py`**

```python
"""Strategy workbench: YouTube/description/.pine -> Pine Script + backtested Python strategy."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
```

- [ ] **Step 6: Create `tests/conftest.py`**

```python
import pytest
from backtesting.test import GOOG

from workbench import db

# A hand-written strategy that follows the contract: one Strategy subclass,
# tunable values as int/float/bool class attributes.
SMA_CODE = '''
from backtesting import Strategy
from backtesting.lib import crossover
from backtesting.test import SMA


class SmaCross(Strategy):
    n1 = 10
    n2 = 20
    use_exit = True
    stop_pct = 0.0
    _private = 5

    def init(self):
        self.a = self.I(SMA, self.data.Close, self.n1)
        self.b = self.I(SMA, self.data.Close, self.n2)

    def next(self):
        if crossover(self.a, self.b):
            self.buy()
        elif crossover(self.b, self.a) and self.use_exit:
            self.position.close()
'''

MARKET = {"ticker": "GOOG", "interval": "1d", "start": "2004-08-19", "end": "2013-03-02",
          "cash": 100_000.0, "commission": 0.0}


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def goog():
    return GOOG.copy()
```

- [ ] **Step 7: Verify pytest runs**

Run: `$PY -m pytest`
Expected: `no tests ran` (exit code 5) — and no import errors. (`workbench.db` doesn't exist yet, so if pytest reports `ModuleNotFoundError: workbench.db` that is expected at this point too; it is fixed in Task 2.)

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .gitignore pytest.ini .env.example workbench/__init__.py tests/conftest.py
git commit -m "Workbench: project setup (deps, pytest, env example)"
```

---

### Task 2: db — schema, strategies, versions

**Files:**
- Create: `workbench/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_db.py`

```python
from workbench import db


def test_create_strategy_with_unique_slug_and_first_version(conn):
    sid = db.create_strategy(conn, "RSI Revert!", "description", source="buy rsi<30",
                             notes=["n1"], pine_code="//@version=6", python_code="code")
    s = db.get_strategy(conn, sid)
    assert s["slug"] == "rsi-revert"
    assert s["notes"] == ["n1"] and s["status"] == "idea" and s["rating"] is None
    v = db.latest_version(conn, sid)
    assert (v["version"], v["pine_code"], v["python_code"], v["change_note"]) == (1, "//@version=6", "code", "generated")

    sid2 = db.create_strategy(conn, "RSI Revert", "description")
    assert db.get_strategy(conn, sid2)["slug"] == "rsi-revert-2"
    assert db.get_strategy(conn, slug="rsi-revert-2")["id"] == sid2


def test_add_version_increments_and_lists_newest_first(conn):
    sid = db.create_strategy(conn, "S", "description", pine_code="p1", python_code="c1")
    v2 = db.add_version(conn, sid, "p2", "c2", "manual edit")
    assert db.latest_version(conn, sid)["id"] == v2
    assert [v["version"] for v in db.list_versions(conn, sid)] == [2, 1]
    assert db.get_version(conn, v2)["python_code"] == "c2"


def test_update_and_filter_strategies(conn):
    a = db.create_strategy(conn, "Alpha", "description")
    db.create_strategy(conn, "Beta", "youtube")
    db.update_strategy(conn, a, status="promising", rating=4, user_notes="works on banks", notes=["x"])
    s = db.get_strategy(conn, a)
    assert (s["status"], s["rating"], s["user_notes"], s["notes"]) == ("promising", 4, "works on banks", ["x"])
    assert [r["name"] for r in db.list_strategies(conn, status="promising")] == ["Alpha"]
    assert [r["name"] for r in db.list_strategies(conn, min_rating=3)] == ["Alpha"]
    assert [r["name"] for r in db.list_strategies(conn, search="bet")] == ["Beta"]
    assert db.sources(conn, "youtube") == {None}


def test_update_rejects_unknown_fields(conn):
    sid = db.create_strategy(conn, "S", "description")
    try:
        db.update_strategy(conn, sid, slug="hack")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest tests/test_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'db' from 'workbench'`

- [ ] **Step 3: Implement `workbench/db.py`** (complete file; later tasks append functions)

```python
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
    ticker TEXT NOT NULL, interval TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL
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
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "strategy"


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
    add_version(conn, sid, pine_code, python_code, change_note)
    return sid


def update_strategy(conn, strategy_id, **fields):
    bad = set(fields) - UPDATABLE
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
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

def add_version(conn, strategy_id, pine_code, python_code, change_note):
    with conn:
        version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM strategy_versions WHERE strategy_id=?",
                               (strategy_id,)).fetchone()[0]
        vid = conn.execute(
            "INSERT INTO strategy_versions(strategy_id, version, pine_code, python_code, change_note, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (strategy_id, version, pine_code, python_code, change_note, now())).lastrowid
        conn.execute("UPDATE strategies SET updated_at=? WHERE id=?", (now(), strategy_id))
    return vid


def list_versions(conn, strategy_id):
    return _all(conn, "SELECT id, version, change_note, created_at FROM strategy_versions"
                      " WHERE strategy_id=? ORDER BY version DESC", (strategy_id,))


def get_version(conn, version_id):
    return _one(conn, "SELECT * FROM strategy_versions WHERE id=?", (version_id,))


def latest_version(conn, strategy_id):
    return _one(conn, "SELECT * FROM strategy_versions WHERE strategy_id=? ORDER BY version DESC LIMIT 1",
                (strategy_id,))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest tests/test_db.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add workbench/db.py tests/test_db.py
git commit -m "Workbench: SQLite schema, strategies and code versions"
```

---

### Task 3: db — runs, optimizations, insights, notes

**Files:**
- Modify: `workbench/db.py` (append)
- Test: `tests/test_db.py` (append)

- [ ] **Step 1: Append failing tests** to `tests/test_db.py`

```python
from conftest import MARKET


def _run(conn, vid, ret=5.0):
    return db.save_run(conn, vid, MARKET, {"n1": 5}, {"Return [%]": ret, "Sharpe Ratio": 1.2},
                       [{"PnL": 1.0}], [["2020-01-01T00:00:00", 100000.0]])


def test_runs_roundtrip_and_library_summary(conn):
    sid = db.create_strategy(conn, "S", "description")
    vid = db.latest_version(conn, sid)["id"]
    _run(conn, vid, 1.0)
    rid = _run(conn, vid, 5.0)
    run = db.get_run(conn, rid)
    assert run["trades"] == [{"PnL": 1.0}] and run["params"] == {"n1": 5}
    assert (run["strategy_id"], run["version"], run["ticker"], run["start_date"]) == (sid, 1, "GOOG", "2004-08-19")
    db.set_note(conn, "runs", rid, "good on GOOG")
    runs = db.list_runs(conn, sid)
    assert [r["id"] for r in runs][0] == rid and runs[0]["note"] == "good on GOOG"
    assert "trades" not in runs[0]
    row = db.list_strategies(conn)[0]
    assert row["n_runs"] == 2 and row["latest_stats"]["Return [%]"] == 5.0


def test_optimizations_and_insights(conn):
    sid = db.create_strategy(conn, "S", "description")
    vid = db.latest_version(conn, sid)["id"]
    oid = db.save_optimization(conn, vid, MARKET, {"n1": [5, 15, 5]}, "Sharpe Ratio",
                               [{"n1": 10, "Sharpe Ratio": 1.5}], {"n1": 10}, 1.5)
    o = db.get_optimization(conn, oid)
    assert o["results"] == [{"n1": 10, "Sharpe Ratio": 1.5}] and o["best_params"] == {"n1": 10}
    assert db.list_optimizations(conn, sid)[0]["best_value"] == 1.5
    assert (db.list_strategies(conn)[0]["opt_maximize"], db.list_strategies(conn)[0]["opt_best"]) == ("Sharpe Ratio", 1.5)
    db.set_note(conn, "optimizations", oid, "sharp peak")
    assert db.get_optimization(conn, oid)["note"] == "sharp peak"
    iid = db.save_insight(conn, sid, "## Where it works", [1], [oid], "claude-opus-5-5")
    assert db.list_insights(conn, sid)[0]["id"] == iid
    assert db.list_insights(conn, sid)[0]["optimization_ids"] == [oid]


def test_set_note_rejects_other_tables(conn):
    try:
        db.set_note(conn, "strategies", 1, "x")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_delete_cascades(conn):
    sid = db.create_strategy(conn, "S", "description")
    vid = db.latest_version(conn, sid)["id"]
    _run(conn, vid)
    db.save_optimization(conn, vid, MARKET, {}, "Sharpe Ratio", [], {}, None)
    db.save_insight(conn, sid, "x", [], [], "m")
    db.delete_strategy(conn, sid)
    for table in ("strategies", "strategy_versions", "runs", "optimizations", "insights"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest tests/test_db.py -v`
Expected: 4 new tests FAIL with `AttributeError: module 'workbench.db' has no attribute 'save_run'`

- [ ] **Step 3: Append to `workbench/db.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest tests/test_db.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add workbench/db.py tests/test_db.py
git commit -m "Workbench: store runs, optimizations, insights and notes"
```

---

### Task 4: db — price bar cache

**Files:**
- Modify: `workbench/db.py` (append)
- Test: `tests/test_db.py` (append)

- [ ] **Step 1: Append failing test**

```python
def test_price_bars_roundtrip_and_fetch_log(conn, goog):
    df = goog.iloc[:10]  # 2004-08-19 .. 2004-09-01
    db.upsert_bars(conn, "GOOG", "1d", df)
    db.upsert_bars(conn, "GOOG", "1d", df)  # idempotent
    out = db.get_bars(conn, "GOOG", "1d", "2004-08-19", "2004-09-02")
    assert list(out.columns) == db.BAR_COLS
    assert list(out.index) == list(df.index)
    assert (out.values == df.values.astype(float)).all()
    assert len(db.get_bars(conn, "GOOG", "1d", "2004-08-20", "2004-09-01")) == 8  # end is exclusive
    assert not db.fetch_covered(conn, "GOOG", "1d", "2004-08-19", "2004-09-02")
    db.log_fetch(conn, "GOOG", "1d", "2004-08-19", "2004-09-02")
    assert db.fetch_covered(conn, "GOOG", "1d", "2004-08-20", "2004-09-01")
    assert not db.fetch_covered(conn, "GOOG", "1d", "2004-08-20", "2004-09-10")
```

- [ ] **Step 2: Run to verify it fails**

Run: `$PY -m pytest tests/test_db.py::test_price_bars_roundtrip_and_fetch_log -v`
Expected: FAIL with `AttributeError: ... 'upsert_bars'`

- [ ] **Step 3: Append to `workbench/db.py`**

```python
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
        conn.execute("INSERT INTO price_fetches VALUES (?,?,?,?)", (ticker, interval, start, end))
```

- [ ] **Step 4: Run tests**

Run: `$PY -m pytest tests/test_db.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add workbench/db.py tests/test_db.py
git commit -m "Workbench: price bar cache tables"
```

---

### Task 5: data — yfinance with DB cache

**Files:**
- Create: `workbench/data.py`
- Test: `tests/test_data.py`

- [ ] **Step 1: Write failing tests** — `tests/test_data.py`

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_data.py -v`
Expected: FAIL with `ImportError: cannot import name 'data'`

- [ ] **Step 3: Implement `workbench/data.py`**

```python
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
    return db.get_bars(conn, ticker, interval, start, end)


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
```

- [ ] **Step 4: Run tests**

Run: `$PY -m pytest tests/test_data.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add workbench/data.py tests/test_data.py
git commit -m "Workbench: yfinance loader with DB cache"
```

---

### Task 6: engine — load strategy code, coerce params

**Files:**
- Create: `workbench/engine.py`
- Test: `tests/test_engine.py`

- [ ] **Step 1: Write failing tests** — `tests/test_engine.py`

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_engine.py -v`
Expected: FAIL with `ImportError: cannot import name 'engine'`

- [ ] **Step 3: Implement `workbench/engine.py`** (first part; Tasks 7–8 append)

```python
"""Load a generated strategy module and backtest / optimize it with backtesting.py."""
import json
import math
import os
import tempfile
import warnings
from dataclasses import dataclass

import pandas as pd
from backtesting import Backtest, Strategy

# backtesting.py warns on every Windows optimize (no fork) and on pandas deprecations: noise in the UI.
warnings.filterwarnings("ignore", module="backtesting")

KEY_STATS = ["Return [%]", "Buy & Hold Return [%]", "CAGR [%]", "Sharpe Ratio", "Max. Drawdown [%]",
             "Win Rate [%]", "# Trades", "Profit Factor", "Expectancy [%]", "Exposure Time [%]"]
MAXIMIZE = ["Sharpe Ratio", "Return [%]", "Return/MaxDD"]
TRADE_COLS = ["Size", "EntryTime", "ExitTime", "EntryPrice", "ExitPrice", "SL", "TP", "PnL", "ReturnPct", "Duration"]
_MODULE = "workbench_strategy"


class StrategyContractError(Exception):
    """Generated Python doesn't follow the strategy contract (see generate.CONTRACT)."""


def load_strategy(code):
    """Exec strategy code; return (its single Strategy subclass, {param: default})."""
    # ponytail: runs in-process with no sandbox. Fine for code from your own Claude account;
    # move to a subprocess before ever loading strategies from other people.
    ns = {"__name__": _MODULE}
    try:
        exec(compile(code, "strategy.py", "exec"), ns)
    except Exception as e:
        raise StrategyContractError(f"strategy.py failed to load: {type(e).__name__}: {e}") from e
    classes = [c for c in ns.values()
               if isinstance(c, type) and issubclass(c, Strategy) and c.__module__ == _MODULE]
    if len(classes) != 1:
        raise StrategyContractError("strategy.py must define exactly one backtesting.Strategy subclass, "
                                    f"found {len(classes)}: {[c.__name__ for c in classes]}")
    cls = classes[0]
    return cls, {k: v for k, v in vars(cls).items() if not k.startswith("_") and type(v) in (int, float, bool)}


def coerce(value, default):
    """Cast a UI / CLI / JSON value to the type of the parameter's default."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(float(value))
    return float(value)


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None
```

- [ ] **Step 4: Run tests**

Run: `$PY -m pytest tests/test_engine.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add workbench/engine.py tests/test_engine.py
git commit -m "Workbench: load strategy code and enforce the contract"
```

---

### Task 7: engine — run a backtest, chart

**Files:**
- Modify: `workbench/engine.py` (append)
- Test: `tests/test_engine.py` (append)

- [ ] **Step 1: Append failing tests**

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_engine.py -v`
Expected: 3 new tests FAIL with `AttributeError: module 'workbench.engine' has no attribute 'run'`

- [ ] **Step 3: Append to `workbench/engine.py`**

```python
@dataclass
class RunResult:
    params: dict          # full parameter set used (defaults + overrides)
    stats: dict           # KEY_STATS -> float or None
    trades: list          # JSON-ready trade records
    equity: list          # [[iso_ts, equity], ...]
    raw: pd.Series        # backtesting.py result, for charting
    bt: Backtest


def _backtest(cls, df, cash, commission):
    return Backtest(df, cls, cash=cash, commission=commission, finalize_trades=True)


def run(code, df, params=None, cash=1_000_000, commission=0.0005):
    cls, defaults = load_strategy(code)
    full = {**defaults, **{k: coerce(v, defaults[k]) for k, v in (params or {}).items() if k in defaults}}
    bt = _backtest(cls, df, cash, commission)
    s = bt.run(**full)
    trades = s._trades[[c for c in TRADE_COLS if c in s._trades]].copy()
    trades["Duration"] = trades["Duration"].astype(str)
    return RunResult(
        params=full,
        stats={k: _num(s[k]) for k in KEY_STATS},
        trades=json.loads(trades.to_json(orient="records", date_format="iso")),
        equity=[[ts.isoformat(), float(v)] for ts, v in s._equity_curve["Equity"].items()],
        raw=s,
        bt=bt,
    )


def chart_html(result):
    """backtesting.py's interactive Bokeh chart for a run, as an HTML string."""
    fd, path = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    try:
        result.bt.plot(results=result.raw, filename=path, open_browser=False)
        with open(path, encoding="utf-8") as f:
            return f.read()
    finally:
        os.remove(path)
```

- [ ] **Step 4: Run tests**

Run: `$PY -m pytest tests/test_engine.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add workbench/engine.py tests/test_engine.py
git commit -m "Workbench: run backtests and render charts"
```

---

### Task 8: engine — parameter optimization

**Files:**
- Modify: `workbench/engine.py` (append)
- Test: `tests/test_engine.py` (append)

- [ ] **Step 1: Append failing tests**

```python
def test_values_and_grid_size():
    assert engine.values(5, 15, 5, 10) == [5, 10, 15]
    assert engine.values(0.5, 1.0, 0.25, 1.0) == [0.5, 0.75, 1.0]
    assert engine.values(0, 1, 1, True) == [False, True]
    assert engine.values(10, 5, 1, 3) == []
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
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_engine.py -v`
Expected: 4 new tests FAIL with `AttributeError: ... 'values'`

- [ ] **Step 3: Append to `workbench/engine.py`**

```python
def values(lo, hi, step, default):
    """Grid values for one parameter, typed like its default. Bools always try both."""
    if isinstance(default, bool):
        return [False, True]
    if isinstance(default, int):
        return list(range(int(lo), int(hi) + 1, max(1, int(step))))
    n = int(round((hi - lo) / step)) + 1 if step > 0 else 0
    return [round(lo + i * step, 10) for i in range(n)]


def grid_size(ranges, defaults):
    return math.prod(len(values(*r, defaults[k])) for k, r in ranges.items()) if ranges else 0


def default_range(d):
    """Starting (min, max, step) offered in the UI for a parameter's default value."""
    if isinstance(d, int):
        return (d // 2, d * 2, max(1, d // 5)) if d > 0 else (0, 10, 1)
    return (d / 2, d * 2, round(d / 10, 10)) if d > 0 else (0.0, 1.0, 0.1)


def return_over_maxdd(stats):
    dd = abs(stats["Max. Drawdown [%]"])
    return stats["Return [%]"] / dd if dd else float("nan")


@dataclass
class OptResult:
    results: pd.DataFrame  # one row per tried combination: params + the maximized metric, best first
    best_params: dict
    best_value: float | None


def optimize(code, df, ranges, maximize="Sharpe Ratio", cash=1_000_000, commission=0.0005, max_tries=500):
    """ranges: {param: (min, max, step)}. Unlisted params keep their defaults.
    Grids larger than max_tries are randomly sampled (seeded, so repeatable)."""
    cls, defaults = load_strategy(code)
    grid = {k: values(*r, defaults[k]) for k, r in ranges.items()}
    if not grid or not all(grid.values()):
        raise ValueError(f"Every optimized parameter needs at least one value: {grid}")
    n = math.prod(len(v) for v in grid.values())
    best, heat = _backtest(cls, df, cash, commission).optimize(
        **grid, maximize=return_over_maxdd if maximize == "Return/MaxDD" else maximize,
        return_heatmap=True, max_tries=max_tries if n > max_tries else None, random_state=0)
    results = (heat.rename(maximize).reset_index().dropna(subset=[maximize])
               .sort_values(maximize, ascending=False, ignore_index=True))
    return OptResult(
        results=results,
        best_params={k: coerce(best._strategy._params[k], defaults[k]) for k in grid},
        best_value=_num(results[maximize].iloc[0]) if len(results) else None,
    )
```

- [ ] **Step 4: Run tests**

Run: `$PY -m pytest tests/test_engine.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add workbench/engine.py tests/test_engine.py
git commit -m "Workbench: grid optimization of strategy parameters"
```

---

### Task 9: generate — Claude calls, contract, reference example, Pine lint

**Files:**
- Create: `workbench/generate.py`
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write failing tests** — `tests/test_generate.py`

```python
from workbench import engine, generate


def test_lint_pine_mirrors_validate_pine_sh():
    assert generate.lint_pine(generate.REFERENCE_PINE) == []
    bad = 'strategy("x")\nx = a\n  ? 1 : 2\ny = request.security(syminfo.tickerid, "D", close)\n'
    assert len(generate.lint_pine(bad)) == 4


def test_reference_python_follows_contract_and_trades(goog):
    _, params = engine.load_strategy(generate.REFERENCE_PY)
    assert params == {"fast_len": 9, "slow_len": 21, "sl_pct": 2.0, "tp_pct": 4.0, "use_short": False}
    assert engine.run(generate.REFERENCE_PY, goog).stats["# Trades"] > 0


def test_system_prompt_has_repo_rules_and_contract():
    s = generate.system_prompt()
    assert "Pine Script v6" in s and "exactly ONE subclass" in s and generate.REFERENCE_PY in s


def test_dry_run(monkeypatch):
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "1")
    g = generate.from_description("ema cross")
    assert (g.python, g.source, g.transcript) == (generate.REFERENCE_PY, "ema cross", None)
    p = generate.from_pine("//@version=6\nindicator('x')", "x")
    assert p.pine == "//@version=6\nindicator('x')" and p.python == generate.REFERENCE_PY
    assert generate.analyze_results("code", {}).startswith("## ")


def test_contract_failure_retries_once_then_keeps_answer_with_note(monkeypatch):
    replies = iter([{"name": "x", "pine": "p", "python": "x = 1", "notes": []},
                    {"name": "x", "pine": "p", "python": "x = 2", "notes": []}])
    prompts = []

    def fake_call(user, schema=generate.SCHEMA, system=None):
        prompts.append(user)
        return next(replies)

    monkeypatch.setattr(generate, "_call", fake_call)
    g = generate.from_description("d")
    assert g.python == "x = 2" and "contract" in g.notes[-1]
    assert "found 0" in prompts[1]


def test_has_credentials(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "WORKBENCH_DRY_RUN"):
        monkeypatch.delenv(k, raising=False)
    assert not generate.has_credentials()
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "1")
    assert generate.has_credentials()
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_generate.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate'`

- [ ] **Step 3: Implement `workbench/generate.py`**

```python
"""Claude API calls: video/description/.pine -> Pine + Python, fix errors, analyze results."""
import contextlib
import importlib.util
import io
import json
import os
import re
from dataclasses import dataclass, field

import anthropic
from dotenv import load_dotenv

from . import ROOT

load_dotenv(ROOT / ".env")

# Models that accept server-side refusal fallbacks (fallbacks="default").
FALLBACK_PREFIXES = ("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1")


def model():
    return os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")


def has_credentials():
    return any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "WORKBENCH_DRY_RUN"))


class GenerationError(Exception):
    pass


@dataclass
class Generated:
    name: str
    pine: str
    python: str
    notes: list = field(default_factory=list)
    transcript: str | None = None
    source: str | None = None


REFERENCE_PINE = """//@version=6
strategy("EMA Cross", overlay=true, default_qty_type=strategy.percent_of_equity, default_qty_value=100, commission_type=strategy.commission.percent, commission_value=0.05)
//@strategy_alert_message {{strategy.order.alert_message}}

fastLen = input.int(9, "Fast EMA Length", minval=1, group="EMA", tooltip="Period of the fast EMA")
slowLen = input.int(21, "Slow EMA Length", minval=1, group="EMA", tooltip="Period of the slow EMA")
slPct = input.float(2.0, "Stop Loss %", minval=0.1, step=0.1, group="Risk", tooltip="Stop distance from entry")
tpPct = input.float(4.0, "Take Profit %", minval=0.1, step=0.1, group="Risk", tooltip="Target distance from entry")
useShort = input.bool(false, "Allow Shorts", group="Risk", tooltip="Also go short on bearish crosses")

fast = ta.ema(close, fastLen)
slow = ta.ema(close, slowLen)

if ta.crossover(fast, slow)
    strategy.entry("Long", strategy.long)
    strategy.exit("Long Exit", "Long", stop=close * (1 - slPct / 100), limit=close * (1 + tpPct / 100))
if ta.crossunder(fast, slow)
    strategy.close("Long")
    if useShort
        strategy.entry("Short", strategy.short)
        strategy.exit("Short Exit", "Short", stop=close * (1 + slPct / 100), limit=close * (1 - tpPct / 100))

plot(fast, "Fast EMA", color.teal)
plot(slow, "Slow EMA", color.orange)
"""

REFERENCE_PY = '''import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover


def ema(values, n):
    return pd.Series(values).ewm(span=n, adjust=False).mean().to_numpy()


class EmaCross(Strategy):
    fast_len = 9        # Pine: fastLen
    slow_len = 21       # Pine: slowLen
    sl_pct = 2.0        # Pine: slPct
    tp_pct = 4.0        # Pine: tpPct
    use_short = False   # Pine: useShort

    def init(self):
        self.fast = self.I(ema, self.data.Close, self.fast_len)
        self.slow = self.I(ema, self.data.Close, self.slow_len)

    def next(self):
        price = self.data.Close[-1]
        if crossover(self.fast, self.slow):
            if self.position.is_short:
                self.position.close()
            self.buy(sl=price * (1 - self.sl_pct / 100), tp=price * (1 + self.tp_pct / 100))
        elif crossover(self.slow, self.fast):
            if self.position.is_long:
                self.position.close()
            if self.use_short:
                self.sell(sl=price * (1 + self.sl_pct / 100), tp=price * (1 - self.tp_pct / 100))
'''

CONTRACT = """# Output contract for the Strategy Workbench app

You are called from the Strategy Workbench app, not from Claude Code: you have no tools, files,
MCP servers or slash commands, and cannot ask the user questions. Ignore instructions above about
those. Answer only with the requested JSON.

Return:
- name: a short human name for the strategy, e.g. "RSI(2) Mean Reversion".
- pine: a complete Pine Script v6 strategy() following every rule above. Use
  default_qty_type=strategy.percent_of_equity, default_qty_value=100,
  commission_type=strategy.commission.percent, commission_value=0.05 so results are comparable
  with the Python backtest.
- python: a complete Python module for backtesting.py that
  * imports only numpy, pandas, math and backtesting / backtesting.lib;
  * defines exactly ONE subclass of backtesting.Strategy;
  * declares every tunable value as a class attribute of type int, float or bool, named in
    snake_case after the matching Pine input, with the same default (no other public class attributes);
  * computes indicators in init() with self.I(func, ...) where func is a plain numpy/pandas
    function (no TA-Lib, no pandas_ta);
  * trades in next() with self.buy / self.sell / self.position.close, using sl= and tp= prices for
    stops and targets, and no explicit size (full equity, matching default_qty_value=100);
  * does no I/O: no data loading, files, network, printing or plotting. Bars arrive as self.data
    with Open, High, Low, Close, Volume; cash and commission are set by the app.
- notes: every place the two versions can behave differently (intrabar stop/target fills,
  request.security or higher-timeframe data, sessions, pyramiding, ...) and every ambiguous rule
  from the source that you had to decide. Empty list if none.

The Pine and Python versions must implement the same rules with the same inputs and defaults.

## Reference example (follow its structure)

```pine
""" + REFERENCE_PINE + """```

```python
""" + REFERENCE_PY + """```
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "pine": {"type": "string"},
        "python": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "pine", "python", "notes"],
    "additionalProperties": False,
}
PY_SCHEMA = {**SCHEMA, "properties": {k: v for k, v in SCHEMA["properties"].items() if k != "pine"},
             "required": ["name", "python", "notes"]}

ANALYST_SYSTEM = ("You are a quantitative trading analyst reviewing backtests of a retail trader's "
                  "strategies (Indian and US markets). Be direct and specific; cite run ids and numbers.")

DRY_RUN = {"name": "EMA Cross (dry run)", "pine": REFERENCE_PINE, "python": REFERENCE_PY,
           "notes": ["Dry run: WORKBENCH_DRY_RUN is set, Claude was not called."]}
DRY_RUN_ANALYSIS = "## Where it works\n(dry run: Claude was not called)\n"


def system_prompt():
    """Repo rules for Pine (CLAUDE.md, pine-developer skill, error log) + the app's output contract."""
    parts = [ROOT / "CLAUDE.md", ROOT / "skills" / "pine-developer" / "SKILL.md", ROOT / "docs" / "pine-error-log.md"]
    return "\n\n---\n\n".join([p.read_text(encoding="utf-8") for p in parts] + [CONTRACT])


def _call(user, schema=SCHEMA, system=None):
    """One Claude request. Returns parsed JSON when `schema` is given, else markdown text."""
    if os.environ.get("WORKBENCH_DRY_RUN"):
        return dict(DRY_RUN) if schema else DRY_RUN_ANALYSIS
    output_config = {"effort": "high"}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    params = dict(
        model=model(),
        max_tokens=64000,
        system=[{"type": "text", "text": system or system_prompt(), "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config=output_config,
    )
    if model().startswith(FALLBACK_PREFIXES):
        params.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    with anthropic.Anthropic().beta.messages.stream(**params) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        category = getattr(msg.stop_details, "category", None)
        raise GenerationError(f"Claude declined this request (category: {category}).")
    if msg.stop_reason == "max_tokens":
        raise GenerationError("Claude's answer was cut off (max_tokens). Try a shorter input.")
    text = "".join(b.text for b in msg.content if b.type == "text")
    return json.loads(text) if schema else text


def _generate(user, schema=SCHEMA):
    """Call Claude; if the Python breaks the contract, retry once with the error. A second
    failure is returned anyway, with a note, so the user can fix it in the app."""
    from .engine import StrategyContractError, load_strategy

    out = _call(user, schema)
    try:
        load_strategy(out["python"])
    except StrategyContractError as e:
        out = _call(f"{user}\n\nYour previous answer's Python failed the contract check:\n{e}\n"
                    "Return the complete corrected answer.", schema)
        try:
            load_strategy(out["python"])
        except StrategyContractError as e2:
            out["notes"] = [*out["notes"], f"Python still fails the contract check: {e2}"]
    return out


def fetch_transcript(url):
    """(title, transcript) via the repo's tools/video-analyzer.py (captions, Whisper fallback)."""
    spec = importlib.util.spec_from_file_location("video_analyzer", ROOT / "tools" / "video-analyzer.py")
    va_mod = importlib.util.module_from_spec(spec)
    # The analyzer prints emoji progress; keep it out of the app's console.
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(va_mod)
        # Its paths are relative to the repo root; pin them so the app works from any folder.
        va_mod.CACHE_DIR = ROOT / "projects" / "analysis" / ".cache"
        va_mod.ANALYSIS_DIR = ROOT / "projects" / "analysis"
        va_mod.STATUS_FILE = ROOT / ".claude" / ".video_status"
        va = va_mod.VideoAnalyzer()
        video_id = va.extract_video_id(url)
        if not video_id:
            raise GenerationError(f"Not a YouTube video URL: {url}")
        title = va.get_video_metadata(url).get("title", video_id)
        transcript, source = va.get_transcript(url, video_id)
    if not transcript:
        raise GenerationError(f"Couldn't get a transcript ({source}). Install Whisper "
                              "(pip install openai-whisper) or paste a summary into the Description tab.")
    return title, transcript


def from_youtube(url):
    title, transcript = fetch_transcript(url)
    out = _generate(
        f"Video title: {title}\nURL: {url}\n\nTranscript:\n{transcript}\n\n"
        "Extract the trading strategy this video teaches and implement it in both languages. If the "
        "video describes an indicator rather than a full strategy, turn its signals into entries and "
        "exits. List every rule you had to decide yourself in notes.")
    return Generated(**out, transcript=transcript, source=url)


def from_description(text):
    out = _generate(f"Implement this trading strategy in both languages:\n\n{text}\n\n"
                    "List every rule you had to decide yourself in notes.")
    return Generated(**out, source=text)


def from_pine(pine_code, name):
    """Keep the given Pine as is; Claude writes only the Python."""
    out = _generate(
        f"Below is an existing Pine Script ({name}.pine) from the user's library. Write the equivalent "
        "Python strategy following the contract. If it is an indicator rather than a strategy, turn its "
        "signals into entries and exits and say so in notes. Return name, python and notes only; the "
        f"Pine code is kept as is.\n\n```pine\n{pine_code}\n```", PY_SCHEMA)
    out["pine"] = pine_code
    return Generated(**out)


def fix(pine, python, error):
    out = _generate(
        "The user hit this error with the strategy below. Fix it and return the complete corrected "
        "name, pine and python. Change only what the error requires; keep inputs and defaults. "
        f"Add a note describing the fix.\n\nError:\n```\n{error}\n```\n\n"
        f"Pine:\n```pine\n{pine}\n```\n\nPython:\n```python\n{python}\n```")
    return Generated(**out)


def analyze_results(python_code, payload):
    """Markdown analysis of a strategy's saved results (see insights.analyze)."""
    return _call(
        "Analyze these backtest results for the strategy below. Write markdown with exactly these "
        "sections: ## Where it works, ## Where it fails, ## Overfitting risk, "
        "## Pine vs Python differences to check, ## Next experiments (concrete tickers, intervals and "
        "parameter values to try next).\n\n"
        f"Strategy code:\n```python\n{python_code}\n```\n\n"
        f"Results (JSON):\n```json\n{json.dumps(payload, indent=1, default=str)}\n```",
        schema=None, system=ANALYST_SYSTEM)


def lint_pine(pine):
    """The checks from scripts/validate-pine.sh, in Python so they work without bash."""
    issues = []
    if not re.search(r"^//@version=", pine, re.M):
        issues.append("Missing //@version declaration")
    if "request.security" in pine and "lookahead=barmerge.lookahead_off" not in pine:
        issues.append("Potential repainting: request.security() without lookahead_off")
    if re.search(r"^\s*\?", pine, re.M):
        issues.append("Possible line continuation error: ternary operator on new line")
    if re.search(r"^strategy\(", pine, re.M) and "@strategy_alert_message" not in pine:
        issues.append("Strategy missing @strategy_alert_message annotation")
    return issues
```

- [ ] **Step 4: Run tests**

Run: `$PY -m pytest tests/test_generate.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add workbench/generate.py tests/test_generate.py
git commit -m "Workbench: Claude generation, fixing and analysis with dry-run mode"
```

---

### Task 10: actions — use cases shared by UI and CLI

**Files:**
- Create: `workbench/actions.py`
- Test: `tests/test_actions.py`

- [ ] **Step 1: Write failing tests** — `tests/test_actions.py`

```python
from conftest import MARKET, SMA_CODE

from workbench import actions, db, generate


def test_backtest_and_optimize_are_saved(conn, goog, monkeypatch):
    monkeypatch.setattr(actions.data, "load_data", lambda conn, ticker, interval, start, end: goog)
    sid = db.create_strategy(conn, "S", "description", python_code=SMA_CODE)
    vid = db.latest_version(conn, sid)["id"]

    rid, res = actions.backtest(conn, vid, MARKET, {"n1": 5})
    run = db.get_run(conn, rid)
    assert run["params"] == {"n1": 5, "n2": 20, "use_exit": True, "stop_pct": 0.0}
    assert run["stats"] == res.stats and len(run["trades"]) == len(res.trades)

    oid, opt = actions.optimize(conn, vid, MARKET, {"n1": (5, 10, 5)}, "Sharpe Ratio")
    saved = db.get_optimization(conn, oid)
    assert saved["best_params"] == opt.best_params and len(saved["results"]) == len(opt.results)

    assert "<html" in actions.chart_for_run(conn, rid).lower()


def test_create_from_and_import_pine(conn, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "1")
    sid = actions.create_from(conn, generate.from_description("ema"), "description")
    assert db.latest_version(conn, sid)["python_code"] == generate.REFERENCE_PY

    pine = tmp_path / "my-strat.pine"
    pine.write_text('//@version=6\nstrategy("My Strat")\n', encoding="utf-8")
    sid = actions.import_pine(conn, pine)
    s = db.get_strategy(conn, sid)
    assert s["source_type"] == "pine_import" and s["source"] == actions.rel(pine)
    assert db.latest_version(conn, sid)["pine_code"] == '//@version=6\nstrategy("My Strat")\n'
    assert actions.rel(pine) in db.sources(conn, "pine_import")


def test_rel_is_repo_relative_inside_repo():
    from workbench import ROOT
    assert actions.rel(ROOT / "projects" / "blank.pine") == "projects/blank.pine"
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_actions.py -v`
Expected: FAIL with `ImportError: cannot import name 'actions'`

- [ ] **Step 3: Implement `workbench/actions.py`**

```python
"""Use cases shared by the Streamlit pages and the CLI."""
import json
from pathlib import Path

from . import ROOT, data, db, engine, generate


def rel(path):
    """Repo-relative posix path when inside the repo (how imports are recorded), else absolute."""
    p = Path(path).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def create_from(conn, gen, source_type):
    return db.create_strategy(conn, gen.name, source_type, source=gen.source, transcript=gen.transcript,
                              notes=gen.notes, pine_code=gen.pine, python_code=gen.python)


def import_pine(conn, path):
    path = Path(path)
    gen = generate.from_pine(path.read_text(encoding="utf-8"), path.stem)
    gen.source = rel(path)
    return create_from(conn, gen, "pine_import")


def _load(conn, market):
    return data.load_data(conn, market["ticker"], market["interval"], market["start"], market["end"])


def backtest(conn, version_id, market, params):
    """Run a saved code version on market data and store the run. Returns (run_id, RunResult)."""
    code = db.get_version(conn, version_id)["python_code"]
    res = engine.run(code, _load(conn, market), params, market["cash"], market["commission"])
    rid = db.save_run(conn, version_id, market, res.params, res.stats, res.trades, res.equity)
    return rid, res


def optimize(conn, version_id, market, ranges, maximize):
    """Grid-search a saved code version and store the result. Returns (optimization_id, OptResult)."""
    code = db.get_version(conn, version_id)["python_code"]
    res = engine.optimize(code, _load(conn, market), ranges, maximize, market["cash"], market["commission"])
    oid = db.save_optimization(conn, version_id, market, ranges, maximize,
                               json.loads(res.results.to_json(orient="records")), res.best_params, res.best_value)
    return oid, res


def chart_for_run(conn, run_id):
    """Charts aren't stored: re-run the saved version + params on cached bars and render."""
    run = db.get_run(conn, run_id)
    market = {"ticker": run["ticker"], "interval": run["interval"], "start": run["start_date"], "end": run["end_date"]}
    code = db.get_version(conn, run["strategy_version_id"])["python_code"]
    return engine.chart_html(engine.run(code, _load(conn, market), run["params"], run["cash"], run["commission"]))
```

- [ ] **Step 4: Run tests**

Run: `$PY -m pytest tests/test_actions.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add workbench/actions.py tests/test_actions.py
git commit -m "Workbench: shared actions for create, import, backtest, optimize, chart"
```

---

### Task 11: insights — summary, stability, Claude analysis

**Files:**
- Create: `workbench/insights.py`
- Test: `tests/test_insights.py`

- [ ] **Step 1: Write failing tests** — `tests/test_insights.py`

```python
from conftest import MARKET, SMA_CODE

from workbench import db, insights


def _run(conn, vid, ticker, ret, sharpe):
    return db.save_run(conn, vid, {**MARKET, "ticker": ticker}, {},
                       {"Return [%]": ret, "Sharpe Ratio": sharpe, "Max. Drawdown [%]": -10.0}, [], [])


def test_summary_empty(conn):
    sid = db.create_strategy(conn, "S", "description")
    assert insights.summary(conn, sid) == {"n_runs": 0, "stability": None}


def test_summary_best_worst_and_per_market(conn):
    sid = db.create_strategy(conn, "S", "description")
    vid = db.latest_version(conn, sid)["id"]
    _run(conn, vid, "A", 10.0, 1.0)
    best = _run(conn, vid, "A", 30.0, 0.5)
    worst = _run(conn, vid, "B", -5.0, None)
    sm = insights.summary(conn, sid)
    assert sm["n_runs"] == 3
    assert (sm["best_by_return"], sm["worst_by_return"]) == (best, worst)
    assert sm["mean"]["Return [%]"] == 35.0 / 3 and sm["mean"]["Sharpe Ratio"] == 0.75
    by = {r["ticker"]: r for r in sm["by_market"]}
    assert by["A"]["runs"] == 2 and by["A"]["pct_profitable"] == 100.0 and by["B"]["pct_profitable"] == 0.0


def test_stability_flags_a_lone_spike():
    spike = {"id": 1, "maximize": "Sharpe Ratio",
             "results": [{"n": i, "Sharpe Ratio": 2.0 if i == 5 else 0.1} for i in range(20)]}
    st = insights.stability(spike)
    assert st["share_within_80pct"] == 0.05 and st["likely_overfit"] is True
    plateau = {"id": 2, "maximize": "Sharpe Ratio", "results": [{"n": i, "Sharpe Ratio": 1.0} for i in range(5)]}
    assert insights.stability(plateau)["likely_overfit"] is False
    assert insights.stability({"id": 3, "maximize": "Sharpe Ratio", "results": []}) is None


def test_analyze_saves_insight(conn, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "1")
    sid = db.create_strategy(conn, "S", "description", python_code=SMA_CODE)
    vid = db.latest_version(conn, sid)["id"]
    rid = _run(conn, vid, "A", 10.0, 1.0)
    iid = insights.analyze(conn, sid)
    ins = db.list_insights(conn, sid)[0]
    assert ins["id"] == iid and ins["run_ids"] == [rid] and ins["content"].startswith("## ")
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_insights.py -v`
Expected: FAIL with `ImportError: cannot import name 'insights'`

- [ ] **Step 3: Implement `workbench/insights.py`**

```python
"""Per-strategy insights: a summary computed from saved runs, and Claude's analysis (stored)."""
import pandas as pd

from . import db, generate

RET, SHARPE, DD = "Return [%]", "Sharpe Ratio", "Max. Drawdown [%]"


def _num(x):
    return None if pd.isna(x) else float(x)


def _pick(df, col, largest=True):
    s = df[col].dropna()
    if s.empty:
        return None
    return int(df.loc[s.idxmax() if largest else s.idxmin(), "run_id"])


def summary(conn, strategy_id):
    """Computed on demand (never stored) so it always reflects every saved run."""
    runs = db.list_runs(conn, strategy_id)
    out = {"n_runs": len(runs)}
    if runs:
        df = pd.DataFrame([{"run_id": r["id"], "ticker": r["ticker"], "interval": r["interval"],
                            **{c: r["stats"].get(c) for c in (RET, SHARPE, DD)}} for r in runs])
        df[[RET, SHARPE, DD]] = df[[RET, SHARPE, DD]].astype(float)
        by_market = (df.groupby(["ticker", "interval"])
                     .agg(runs=("run_id", "count"), pct_profitable=(RET, lambda x: 100 * (x > 0).mean()),
                          avg_return=(RET, "mean"), avg_sharpe=(SHARPE, "mean"))
                     .reset_index())
        out.update(
            best_by_return=_pick(df, RET), worst_by_return=_pick(df, RET, largest=False),
            best_by_sharpe=_pick(df, SHARPE),
            mean={c: _num(df[c].mean()) for c in (RET, SHARPE, DD)},
            median={c: _num(df[c].median()) for c in (RET, SHARPE, DD)},
            by_market=by_market.to_dict("records"),
        )
    opts = db.list_optimizations(conn, strategy_id)
    out["stability"] = stability(db.get_optimization(conn, opts[0]["id"])) if opts else None
    return out


def stability(opt):
    """Share of tried combinations scoring within 80% of the best. Under 10% means the best
    result is a lone spike, which rarely survives new data."""
    # ponytail: one-number heuristic; add neighbour or walk-forward checks if it misleads.
    res = pd.DataFrame(opt["results"])
    m = opt["maximize"]
    if res.empty or m not in res:
        return None
    best = res[m].max()
    share = float((res[m] >= 0.8 * best).mean()) if best > 0 else None
    return {"optimization_id": opt["id"], "maximize": m, "best": _num(best), "combinations": len(res),
            "share_within_80pct": share, "likely_overfit": share is not None and share < 0.1}


def analyze(conn, strategy_id, run_ids=None):
    """Ask Claude to review the strategy's results; saves and returns the insight id.
    Default scope: the latest 20 runs and the latest optimization's top 20 combinations."""
    s = db.get_strategy(conn, strategy_id)
    runs = db.list_runs(conn, strategy_id)
    runs = [r for r in runs if r["id"] in run_ids] if run_ids else runs[:20]
    opts = [db.get_optimization(conn, o["id"]) for o in db.list_optimizations(conn, strategy_id)[:1]]
    payload = {
        "strategy": s["name"],
        "translation_notes": s["notes"],
        "user_notes": s["user_notes"],
        "summary": summary(conn, strategy_id),
        "runs": [{k: r[k] for k in ("id", "version", "ticker", "interval", "start_date", "end_date", "params",
                                    "stats", "note")} for r in runs],
        "optimizations": [{**{k: o[k] for k in ("id", "ticker", "interval", "start_date", "end_date", "ranges",
                                                "maximize", "best_params", "best_value", "note")},
                           "top_20": o["results"][:20]} for o in opts],
    }
    content = generate.analyze_results(db.latest_version(conn, strategy_id)["python_code"], payload)
    return db.save_insight(conn, strategy_id, content, [r["id"] for r in runs], [o["id"] for o in opts],
                           generate.model())
```

- [ ] **Step 4: Run tests**

Run: `$PY -m pytest tests/test_insights.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add workbench/insights.py tests/test_insights.py
git commit -m "Workbench: run summary, stability check and Claude analysis"
```

---

### Task 12: CLI

**Files:**
- Create: `workbench/__main__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing test** — `tests/test_cli.py`

```python
import json

from conftest import SMA_CODE

from workbench import actions, db
from workbench.__main__ import main


def test_cli_list_run_optimize_summary(tmp_path, goog, monkeypatch, capsys):
    monkeypatch.setenv("WORKBENCH_DB", str(tmp_path / "cli.db"))
    monkeypatch.setattr(actions.data, "load_data", lambda conn, ticker, interval, start, end: goog)
    conn = db.connect()
    db.create_strategy(conn, "Sma Cross", "description", python_code=SMA_CODE)

    main(["list"])
    assert "sma-cross" in capsys.readouterr().out

    main(["run", "sma-cross", "--ticker", "GOOG", "--start", "2005-01-01", "--end", "2010-01-01", "--param", "n1=5"])
    out = json.loads(capsys.readouterr().out)
    assert out["params"]["n1"] == 5 and "Sharpe Ratio" in out

    main(["optimize", "sma-cross", "--range", "n1=5:10:5", "--maximize", "Return [%]"])
    assert "best=" in capsys.readouterr().out

    main(["summary", "sma-cross"])
    assert json.loads(capsys.readouterr().out)["n_runs"] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'workbench.__main__'`

- [ ] **Step 3: Implement `workbench/__main__.py`**

```python
"""Command line for the workbench. Run: python -m workbench --help"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import actions, data, db, engine, generate, insights


def _pairs(items):
    return dict(item.split("=", 1) for item in items)


def _strategy(conn, slug):
    s = db.get_strategy(conn, slug=slug)
    if not s:
        sys.exit(f"No strategy {slug!r}. See: python -m workbench list")
    return s


def _market(a, s):
    interval = a.interval or s["default_interval"]
    return {"ticker": a.ticker or s["default_ticker"], "interval": interval,
            "start": a.start or data.default_start(interval), "end": a.end or dt.date.today().isoformat(),
            "cash": a.cash, "commission": a.commission}


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m workbench", description="Strategy workbench")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list strategies").add_argument("--status", choices=db.STATUSES)
    new = sub.add_parser("new", help="generate a strategy with Claude").add_mutually_exclusive_group(required=True)
    new.add_argument("--url", help="YouTube video URL")
    new.add_argument("--desc", help="plain-English strategy description")
    sub.add_parser("import", help="import a .pine file, or every .pine in a folder").add_argument("path", type=Path)
    run, opt = sub.add_parser("run", help="backtest"), sub.add_parser("optimize", help="grid-search parameters")
    for c in (run, opt):
        c.add_argument("slug")
        c.add_argument("--ticker")
        c.add_argument("--interval", choices=data.INTERVALS)
        c.add_argument("--start", help="YYYY-MM-DD")
        c.add_argument("--end", help="YYYY-MM-DD (exclusive)")
        c.add_argument("--cash", type=float, default=1_000_000)
        c.add_argument("--commission", type=float, default=0.0005)
    run.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    opt.add_argument("--range", action="append", required=True, metavar="NAME=MIN:MAX:STEP")
    opt.add_argument("--maximize", default="Sharpe Ratio", choices=engine.MAXIMIZE)
    sub.add_parser("summary", help="computed summary of all runs").add_argument("slug")
    sub.add_parser("analyze", help="ask Claude to analyze the results").add_argument("slug")
    a = p.parse_args(argv)
    conn = db.connect()

    if a.cmd == "list":
        for r in db.list_strategies(conn, status=a.status):
            ret = (r["latest_stats"] or {}).get("Return [%]")
            print(f'{r["slug"]:40} {r["status"]:10} runs={r["n_runs"]:<4} '
                  f'last return={"-" if ret is None else f"{ret:.2f}%"}')
    elif a.cmd == "new":
        gen = generate.from_youtube(a.url) if a.url else generate.from_description(a.desc)
        sid = actions.create_from(conn, gen, "youtube" if a.url else "description")
        print("created", db.get_strategy(conn, sid)["slug"])
    elif a.cmd == "import":
        done = db.sources(conn, "pine_import")
        for path in sorted(a.path.glob("*.pine")) if a.path.is_dir() else [a.path]:
            if actions.rel(path) in done:
                print("skip (already imported)", path.name)
            else:
                print("imported", db.get_strategy(conn, actions.import_pine(conn, path))["slug"])
    elif a.cmd == "run":
        s = _strategy(conn, a.slug)
        rid, res = actions.backtest(conn, db.latest_version(conn, s["id"])["id"], _market(a, s), _pairs(a.param))
        print(json.dumps({"run_id": rid, "params": res.params, **res.stats}, indent=2))
    elif a.cmd == "optimize":
        s = _strategy(conn, a.slug)
        ranges = {k: tuple(float(x) for x in v.split(":")) for k, v in _pairs(a.range).items()}
        oid, res = actions.optimize(conn, db.latest_version(conn, s["id"])["id"], _market(a, s), ranges, a.maximize)
        print(res.results.head(20).to_string(index=False))
        print(f"optimization_id={oid} best={res.best_params}")
    elif a.cmd == "summary":
        print(json.dumps(insights.summary(conn, _strategy(conn, a.slug)["id"]), indent=2, default=str))
    elif a.cmd == "analyze":
        s = _strategy(conn, a.slug)
        insights.analyze(conn, s["id"])
        print(db.list_insights(conn, s["id"])[0]["content"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `$PY -m pytest tests/test_cli.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add workbench/__main__.py tests/test_cli.py
git commit -m "Workbench: command line interface"
```

---

### Task 13: Streamlit — entry, Library and Create pages

**Files:**
- Create: `app.py`, `ui/library.py`, `ui/create.py`
- Test: `tests/test_app.py`

- [ ] **Step 1: Write failing smoke test** — `tests/test_app.py`

```python
from conftest import SMA_CODE
from streamlit.testing.v1 import AppTest

from workbench import db


def test_library_and_create_pages_render(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DB", str(tmp_path / "ui.db"))
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "1")
    conn = db.connect()
    db.create_strategy(conn, "Smoke Test", "description", python_code=SMA_CODE, pine_code="//@version=6")
    conn.close()

    at = AppTest.from_file("../app.py", default_timeout=60).run()
    assert not at.exception
    assert [t.value for t in at.title] == ["Strategy library"]

    at.switch_page("ui/create.py").run()
    assert not at.exception
    assert [t.value for t in at.title] == ["Create a strategy"]
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_app.py -v`
Expected: FAIL — `AppTest` can't find `app.py` (file not found).

- [ ] **Step 3: Create `app.py`**

```python
"""Strategy Workbench. Run from the repo folder: streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="Strategy Workbench", layout="wide")
st.navigation([
    st.Page("ui/library.py", title="Library", default=True),
    st.Page("ui/create.py", title="Create"),
    st.Page("ui/strategy.py", title="Strategy"),
]).run()
```

- [ ] **Step 4: Create `ui/library.py`**

```python
"""Library page: every saved strategy with its latest results; click a row to open it."""
import pandas as pd
import streamlit as st

from workbench import db

conn = db.connect()
st.title("Strategy library")

c1, c2, c3 = st.columns([3, 1, 1])
search = c1.text_input("Search by name")
status = c2.selectbox("Status", ["all", *db.STATUSES])
min_rating = c3.selectbox("Min rating", [0, 1, 2, 3, 4, 5], format_func=lambda r: "any" if r == 0 else "★" * r)

rows = db.list_strategies(conn, status=None if status == "all" else status,
                          min_rating=min_rating or None, search=search or None)
if not rows:
    st.info("No strategies yet. Make one on the **Create** page.")
    st.stop()


def stat(r, key):
    return (r["latest_stats"] or {}).get(key)


table = pd.DataFrame([{
    "Name": r["name"], "Status": r["status"], "Rating": "★" * (r["rating"] or 0), "Source": r["source_type"],
    "Runs": r["n_runs"], "Return %": stat(r, "Return [%]"), "Sharpe": stat(r, "Sharpe Ratio"),
    "Max DD %": stat(r, "Max. Drawdown [%]"),
    "Latest optimization": f'{r["opt_maximize"]} {r["opt_best"]:.2f}' if r["opt_best"] is not None else "",
    "Created": r["created_at"][:10],
} for r in rows])
st.caption("Stats are from each strategy's latest run. Click a row to open the strategy.")
event = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row", width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%.2f")
                                    for c in ("Return %", "Sharpe", "Max DD %")})
if event.selection.rows:
    st.session_state.strategy_id = rows[event.selection.rows[0]]["id"]
    st.switch_page("ui/strategy.py")
```

- [ ] **Step 5: Create `ui/create.py`**

```python
"""Create page: a new strategy from a YouTube video, a description, or an existing .pine file."""
import streamlit as st

from workbench import ROOT, actions, db, generate

conn = db.connect()
st.title("Create a strategy")

if not generate.has_credentials():
    st.warning("Claude needs an API key. Create a file named `.env` in the repo folder containing\n\n"
               "`ANTHROPIC_API_KEY=sk-ant-...`\n\nand restart the app. To try the app without a key, "
               "start it with the environment variable `WORKBENCH_DRY_RUN=1`.")
    st.stop()


def create(label, make):
    """Run make() (returns a strategy id) inside a status box, then open the new strategy."""
    with st.status(label) as box:
        try:
            sid = make()
        except Exception as e:
            box.update(label="Failed", state="error")
            st.error(str(e))
            return
    st.session_state.strategy_id = sid
    st.switch_page("ui/strategy.py")


url_tab, desc_tab, pine_tab = st.tabs(["YouTube URL", "Description", "Import .pine"])

with url_tab:
    url = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...")
    if st.button("Generate from video", type="primary", disabled=not url.strip()):
        create("Fetching the transcript and writing Pine + Python, usually 1-3 minutes...",
               lambda: actions.create_from(conn, generate.from_youtube(url.strip()), "youtube"))

with desc_tab:
    desc = st.text_area("Describe the strategy", height=200, placeholder=(
        "RSI(2) mean reversion on Nifty: buy when RSI(2) < 10 and close > 200 EMA; "
        "exit when close crosses above the 5 SMA; 3% stop."))
    if st.button("Generate from description", type="primary", disabled=not desc.strip()):
        create("Writing Pine + Python, usually 1-3 minutes...",
               lambda: actions.create_from(conn, generate.from_description(desc), "description"))

with pine_tab:
    done = db.sources(conn, "pine_import")
    files = sorted((ROOT / "projects").glob("*.pine"))
    st.caption("Indicators can be imported too: Claude turns their signals into entries and exits "
               "and says so in the notes.")
    pick = st.selectbox("Script from projects/", files,
                        format_func=lambda p: p.name + ("  (imported)" if actions.rel(p) in done else ""))
    if st.button("Import selected", type="primary", disabled=pick is None):
        create(f"Writing the Python version of {pick.name}...", lambda: actions.import_pine(conn, pick))
    todo = [p for p in files if actions.rel(p) not in done]
    if st.button(f"Import all not yet imported ({len(todo)})", disabled=not todo):
        bar = st.progress(0.0)
        for i, p in enumerate(todo):
            bar.progress(i / len(todo), text=f"{p.name} ({i + 1}/{len(todo)})")
            try:
                actions.import_pine(conn, p)
            except Exception as e:
                st.error(f"{p.name}: {e}")
        bar.progress(1.0, text="Done. Open the Library to see them.")
```

- [ ] **Step 6: Create an empty placeholder `ui/strategy.py`** so navigation resolves (filled in Task 14)

```python
"""Strategy page: filled in by Task 14."""
import streamlit as st

st.title("Strategy")
```

- [ ] **Step 7: Run the smoke test**

Run: `$PY -m pytest tests/test_app.py -v`
Expected: 1 passed

- [ ] **Step 8: Commit**

```bash
git add app.py ui/library.py ui/create.py ui/strategy.py tests/test_app.py
git commit -m "Workbench UI: navigation, Library and Create pages"
```

---

### Task 14: Streamlit — Strategy page (Code, Backtest, Optimize, History, Insights)

**Files:**
- Modify: `ui/strategy.py` (replace placeholder)
- Test: `tests/test_app.py` (append)

- [ ] **Step 1: Append failing smoke test**

```python
def test_strategy_page_renders_all_tabs(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DB", str(tmp_path / "ui.db"))
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "1")
    conn = db.connect()
    sid = db.create_strategy(conn, "Smoke Test", "description", python_code=SMA_CODE, pine_code="//@version=6")
    conn.close()

    at = AppTest.from_file("../app.py", default_timeout=60).run()
    at.session_state["strategy_id"] = sid
    at.switch_page("ui/strategy.py").run()
    assert not at.exception
    assert at.title[0].value == "Smoke Test"
    assert {t.label for t in at.tabs} == {"Code", "Backtest", "Optimize", "History", "Insights"}
    assert {n.label for n in at.number_input} >= {"n1", "n2", "stop_pct"}
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_app.py::test_strategy_page_renders_all_tabs -v`
Expected: FAIL — title is "Strategy", not "Smoke Test".

- [ ] **Step 3: Replace `ui/strategy.py`** with the full page

```python
"""Strategy page: code, backtest, optimize, history and insights for one strategy."""
import datetime as dt
import json
import traceback

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from workbench import actions, data, db, engine, generate, insights

conn = db.connect()
state = st.session_state
sid = state.get("strategy_id")
s = db.get_strategy(conn, sid) if sid else None
if not s:
    st.info("Open a strategy from the **Library** page.")
    st.stop()

state.setdefault("form_gen", 0)
state.setdefault("market", {
    "ticker": s["default_ticker"], "interval": s["default_interval"],
    "start": dt.date.fromisoformat(data.default_start(s["default_interval"])), "end": dt.date.today(),
    "cash": 1_000_000.0, "commission": 0.0005,
})

# Buttons that load a run or parameters store a "goto" and rerun. A widget's value can't be
# changed once it is drawn, so the goto is applied here, and form_gen gives the form fresh
# widget keys so the new values show up.
goto = state.pop("goto", None)
if goto:
    state[f"cur_ver_{sid}"] = goto["version"]
    if "params" in goto:
        key = f"params_{goto['version']}"
        state[key] = {**state.get(key, {}), **goto["params"]}
    if "market" in goto:
        state.market = goto["market"]
    state.form_gen += 1
    st.toast(goto["message"])
gen = state.form_gen


def jump(version_id, message, params=None, market=None):
    state.goto = {"version": version_id, "message": message,
                  **({"params": params} if params else {}), **({"market": market} if market else {})}
    st.rerun()


def market_of(rec):
    return {"ticker": rec["ticker"], "interval": rec["interval"],
            "start": dt.date.fromisoformat(rec["start_date"]), "end": dt.date.fromisoformat(rec["end_date"]),
            "cash": rec["cash"], "commission": rec["commission"]}


def fmt(x):
    return "-" if x is None else f"{x:,.2f}"


# --- header, version, market ----------------------------------------------------

st.title(s["name"])
st.caption(f'{s["source_type"]} · {s["source"] or "-"} · created {s["created_at"][:10]} · status: {s["status"]}')

versions = db.list_versions(conn, sid)
ids = [v["id"] for v in versions]
cur = state.get(f"cur_ver_{sid}", ids[0])
vid = st.selectbox("Code version", ids, index=ids.index(cur) if cur in ids else 0, key=f"ver_{sid}_{gen}",
                   format_func=lambda i: next(f'v{v["version"]} · {v["change_note"]} · {v["created_at"][:16]}'
                                              for v in versions if v["id"] == i))
state[f"cur_ver_{sid}"] = vid
v = db.get_version(conn, vid)

m = state.market
c = st.columns(6)
market = {
    "ticker": c[0].text_input("Ticker", m["ticker"], key=f"mk_ticker_{gen}",
                              help="NSE stock: RELIANCE.NS · Nifty 50: ^NSEI · Bank Nifty: ^NSEBANK · "
                                   "US: AAPL · crypto: BTC-USD").strip(),
    "interval": c[1].selectbox("Interval", data.INTERVALS, key=f"mk_interval_{gen}",
                               index=data.INTERVALS.index(m["interval"]) if m["interval"] in data.INTERVALS else 0,
                               help="yfinance keeps ~60 days of 5m-30m bars and ~2 years of 1h bars"),
    "start": c[2].date_input("Start", m["start"], key=f"mk_start_{gen}"),
    "end": c[3].date_input("End (exclusive)", m["end"], key=f"mk_end_{gen}"),
    "cash": c[4].number_input("Cash", value=float(m["cash"]), step=100_000.0, key=f"mk_cash_{gen}"),
    "commission": c[5].number_input("Commission", value=float(m["commission"]), step=0.0001, format="%.4f",
                                    key=f"mk_comm_{gen}", help="Fraction per side: 0.0005 = 0.05%"),
}
state.market = market
run_market = {**market, "start": market["start"].isoformat(), "end": market["end"].isoformat()}


# --- helpers shared by the tabs ------------------------------------------------------

def strategy_params(version):
    """The version's parameters, or None if its Python fails to load (kept for 'Fix with Claude')."""
    try:
        return engine.load_strategy(version["python_code"])[1]
    except engine.StrategyContractError as e:
        state.error = (version["id"], str(e))
        return None


def guarded(fn):
    """Run fn(): data problems are shown; code problems are kept for 'Fix with Claude'."""
    try:
        fn()
        state.pop("error", None)
    except data.DataError as e:
        st.error(str(e))
    except Exception:
        state.error = (vid, traceback.format_exc())


def fix_with_claude(pine, python, error):
    try:
        with st.spinner("Claude is fixing the code..."):
            fixed = generate.fix(pine, python, error)
    except Exception as e:
        st.error(f"Claude call failed: {e}")
        return
    new_vid = db.add_version(conn, sid, fixed.pine, fixed.python,
                             "fix with Claude: " + error.strip().splitlines()[-1][:80])
    db.update_strategy(conn, sid, notes=fixed.notes)
    state.pop("error", None)
    jump(new_vid, "Saved Claude's fix as a new version")


def show_error(where):
    err = state.get("error")
    if err and err[0] == vid:
        st.error("The Python strategy failed. Claude can fix it, or edit it in the Code tab.")
        st.code(err[1], language=None)
        if st.button("Fix with Claude", key=f"fix_{where}"):
            fix_with_claude(v["pine_code"], v["python_code"], err[1])


def show_run(run, where):
    st.markdown(f'**Run #{run["id"]}** · v{run["version"]} · {run["ticker"]} {run["interval"]} · '
                f'{run["start_date"]} -> {run["end_date"]}')
    cols = st.columns(5)
    for i, k in enumerate(engine.KEY_STATS):
        cols[i % 5].metric(k, fmt(run["stats"].get(k)))
    if run["equity"]:
        eq = pd.DataFrame(run["equity"], columns=["Time", "Equity"])
        eq["Time"] = pd.to_datetime(eq["Time"])
        st.line_chart(eq, x="Time", y="Equity")
    st.dataframe(pd.DataFrame(run["trades"]), hide_index=True)
    if st.button("Open full interactive chart", key=f"chart_{where}_{run['id']}"):
        guarded(lambda: components.html(actions.chart_for_run(conn, run["id"]), height=900, scrolling=True))


def show_opt(opt, where):
    metric = opt["maximize"]
    res = pd.DataFrame(opt["results"])
    st.markdown(f'**Optimization #{opt["id"]}** · v{opt["version"]} · {opt["ticker"]} {opt["interval"]} · '
                f'{opt["start_date"]} -> {opt["end_date"]} · {len(res)} combinations')
    if opt["best_value"] is None:
        st.warning("No combination produced a result (no trades?).")
        return
    st.markdown(f'Best {metric} = **{opt["best_value"]:.3f}** with `{opt["best_params"]}`')
    names = [col for col in res.columns if col != metric]
    if len(names) == 2 and all(res[n].dtype != bool for n in names):
        st.altair_chart(alt.Chart(res.rename(columns={metric: "metric"})).mark_rect().encode(
            x=alt.X(f"{names[0]}:O"), y=alt.Y(f"{names[1]}:O"),
            color=alt.Color("metric:Q", title=metric), tooltip=[*names, "metric"]))
    picked = st.dataframe(res, hide_index=True, on_select="rerun", selection_mode="single-row",
                          key=f"optres_{where}_{opt['id']}")
    row = res.iloc[picked.selection.rows[0]].to_dict() if picked.selection.rows else opt["best_params"]
    if st.button("Load selected row (or best) into Backtest", key=f"use_{where}_{opt['id']}"):
        version = db.get_version(conn, opt["strategy_version_id"])
        defaults = engine.load_strategy(version["python_code"])[1]
        params = {k: engine.coerce(row[k], defaults[k]) for k in names if k in defaults}
        jump(version["id"], "Parameters loaded: open the Backtest tab", params=params, market=market_of(opt))


code_tab, bt_tab, opt_tab, hist_tab, ins_tab = st.tabs(["Code", "Backtest", "Optimize", "History", "Insights"])

# --- Code ---------------------------------------------------------------------------

with code_tab:
    for w in generate.lint_pine(v["pine_code"]):
        st.warning(f"Pine check: {w}")
    if s["notes"]:
        with st.expander(f'Where Pine and Python may differ ({len(s["notes"])} notes)'):
            st.markdown("\n".join(f"- {n}" for n in s["notes"]))
    left, right = st.columns(2)
    pine = left.text_area("Pine Script v6: paste into TradingView", v["pine_code"], height=520, key=f"pine_{vid}")
    python = right.text_area("Python: backtesting.py", v["python_code"], height=520, key=f"py_{vid}")
    left.download_button("Download .pine", pine, f'{s["slug"]}.pine', key="dl_pine")
    right.download_button("Download .py", python, f'{s["slug"]}.py', key="dl_py")
    with left.expander("Pine with a copy button"):
        st.code(pine, language=None)
    if st.button("Save edits as a new version", disabled=(pine, python) == (v["pine_code"], v["python_code"])):
        jump(db.add_version(conn, sid, pine, python, "manual edit"), "Saved as a new version")
    error = st.text_area("Paste an error for Claude to fix (TradingView compiler error or Python traceback)",
                         key=f"err_{vid}")
    if st.button("Fix with Claude", disabled=not error.strip(), key="fix_code"):
        fix_with_claude(pine, python, error)

# --- Backtest -----------------------------------------------------------------------

with bt_tab:
    params = strategy_params(v)
    if params is not None:
        saved = state.get(f"params_{vid}", {})
        cols = st.columns(4)
        chosen = {}
        for i, (k, d) in enumerate(params.items()):
            val, key = engine.coerce(saved.get(k, d), d), f"p_{vid}_{gen}_{k}"
            if isinstance(d, bool):
                chosen[k] = cols[i % 4].checkbox(k, val, key=key)
            elif isinstance(d, int):
                chosen[k] = cols[i % 4].number_input(k, value=val, step=1, key=key)
            else:
                chosen[k] = cols[i % 4].number_input(k, value=val, format="%g", key=key)
        state[f"params_{vid}"] = chosen
        if st.button("Run backtest", type="primary"):
            def go():
                with st.spinner("Loading data and running the backtest..."):
                    state.view_run = actions.backtest(conn, vid, run_market, chosen)[0]
            guarded(go)
    show_error("bt")
    run = db.get_run(conn, state["view_run"]) if state.get("view_run") else None
    if run and run["strategy_id"] == sid:
        show_run(run, "bt")

# --- Optimize -----------------------------------------------------------------------

with opt_tab:
    params = strategy_params(v)
    if params is not None:
        st.caption("Tick the parameters to vary; the others keep their defaults. "
                   "Grids over 500 combinations are randomly sampled down to 500.")
        ranges = {}
        for k, d in params.items():
            row = st.columns([2, 1, 1, 1])
            if not row[0].checkbox(k, key=f"o_{vid}_{k}"):
                continue
            if isinstance(d, bool):
                row[1].caption("tries False and True")
                ranges[k] = (0, 1, 1)
                continue
            lo, hi, step = engine.default_range(d)
            f = None if isinstance(d, int) else "%g"
            ranges[k] = (row[1].number_input("min", value=lo, format=f, key=f"o_{vid}_{k}_lo"),
                         row[2].number_input("max", value=hi, format=f, key=f"o_{vid}_{k}_hi"),
                         row[3].number_input("step", value=step, format=f, key=f"o_{vid}_{k}_step"))
        maximize = st.selectbox("Maximize", engine.MAXIMIZE, key=f"o_{vid}_max")
        n = engine.grid_size(ranges, params)
        if st.button(f"Run optimization ({n} combinations)", type="primary", disabled=n == 0):
            def go():
                with st.spinner("Optimizing..."):
                    state.view_opt = actions.optimize(conn, vid, run_market, ranges, maximize)[0]
            guarded(go)
    show_error("opt")
    opt = db.get_optimization(conn, state["view_opt"]) if state.get("view_opt") else None
    if opt and opt["strategy_id"] == sid:
        show_opt(opt, "opt")

# --- History ------------------------------------------------------------------------

with hist_tab:
    runs = db.list_runs(conn, sid)
    st.subheader(f"Backtest runs ({len(runs)})")
    if runs:
        table = pd.DataFrame([{
            "Run": r["id"], "Ver": r["version"], "Ticker": r["ticker"], "Interval": r["interval"],
            "From": r["start_date"], "To": r["end_date"], "Params": json.dumps(r["params"]),
            **{k: r["stats"].get(k) for k in ("Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "Win Rate [%]",
                                              "# Trades")},
            "Note": r["note"] or "", "When": r["created_at"][:16],
        } for r in runs])
        rows = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="multi-row",
                            key="hist_runs").selection.rows
        picked = [runs[i] for i in rows]
        if len(picked) == 1:
            r = picked[0]
            note = st.text_input("Note for this run", r["note"] or "", key=f"rnote_{r['id']}")
            b1, b2 = st.columns(2)
            if b1.button("Save note", key="save_rnote"):
                db.set_note(conn, "runs", r["id"], note)
                st.rerun()
            if b2.button("Load into Backtest tab", key="load_run"):
                state.view_run = r["id"]
                jump(r["strategy_version_id"], f"Run #{r['id']} loaded into the Backtest tab",
                     params=r["params"], market=market_of(r))
        elif len(picked) > 1:
            st.markdown("**Compare runs**")
            compare = pd.DataFrame({f'#{r["id"]} {r["ticker"]} {r["interval"]}':
                                    {**r["stats"], **{f"param {k}": x for k, x in r["params"].items()}}
                                    for r in picked})
            st.dataframe(compare.map(lambda x: f"{x:,.2f}" if isinstance(x, float) else str(x)))

    opts = db.list_optimizations(conn, sid)
    st.subheader(f"Optimizations ({len(opts)})")
    if opts:
        otable = pd.DataFrame([{
            "Opt": o["id"], "Ver": o["version"], "Ticker": o["ticker"], "Interval": o["interval"],
            "From": o["start_date"], "To": o["end_date"], "Maximize": o["maximize"], "Best": o["best_value"],
            "Best params": json.dumps(o["best_params"]), "Note": o["note"] or "", "When": o["created_at"][:16],
        } for o in opts])
        sel = st.dataframe(otable, hide_index=True, on_select="rerun", selection_mode="single-row",
                           key="hist_opts").selection.rows
        if sel:
            o = db.get_optimization(conn, opts[sel[0]]["id"])
            note = st.text_input("Note for this optimization", o["note"] or "", key=f"onote_{o['id']}")
            if st.button("Save note", key="save_onote"):
                db.set_note(conn, "optimizations", o["id"], note)
                st.rerun()
            show_opt(o, "hist")

# --- Insights -----------------------------------------------------------------------

with ins_tab:
    c1, c2 = st.columns(2)
    status = c1.selectbox("Status", db.STATUSES, index=db.STATUSES.index(s["status"]), key=f"status_{sid}")
    rating = c2.select_slider("Rating", options=[0, 1, 2, 3, 4, 5], value=s["rating"] or 0, key=f"rating_{sid}",
                              format_func=lambda r: "unrated" if r == 0 else "★" * r)
    notes = st.text_area("My notes", s["user_notes"] or "", height=150, key=f"notes_{sid}",
                         placeholder="What works, what doesn't, ideas to try...")
    if (status, rating or None, notes) != (s["status"], s["rating"], s["user_notes"] or ""):
        db.update_strategy(conn, sid, status=status, rating=rating or None, user_notes=notes)
        st.toast("Saved")

    st.subheader("Summary of all runs")
    sm = insights.summary(conn, sid)
    if not sm["n_runs"]:
        st.info("No runs yet. Backtest the strategy to build up a summary.")
    else:
        mc = st.columns(4)
        mc[0].metric("Runs", sm["n_runs"])
        mc[1].metric("Avg return %", fmt(sm["mean"]["Return [%]"]))
        mc[2].metric("Avg Sharpe", fmt(sm["mean"]["Sharpe Ratio"]))
        mc[3].metric("Avg max drawdown %", fmt(sm["mean"]["Max. Drawdown [%]"]))
        st.caption(f'Best run by return: #{sm["best_by_return"]} · by Sharpe: #{sm["best_by_sharpe"]} · '
                   f'worst by return: #{sm["worst_by_return"]}')
        st.dataframe(pd.DataFrame(sm["by_market"]), hide_index=True)
    stab = sm["stability"]
    if stab and stab["share_within_80pct"] is None:
        st.info(f'Latest optimization #{stab["optimization_id"]}: best {stab["maximize"]} is not positive, '
                "so stability wasn't measured.")
    elif stab:
        msg = (f'Latest optimization #{stab["optimization_id"]}: {stab["share_within_80pct"]:.0%} of '
               f'{stab["combinations"]} combinations score within 80% of the best {stab["maximize"]}.')
        if stab["likely_overfit"]:
            st.warning(msg + " The best result is a lone spike, so it is likely overfit.")
        else:
            st.info(msg)

    st.subheader("Claude's analysis")
    runs = db.list_runs(conn, sid)
    label = {r["id"]: f'#{r["id"]} {r["ticker"]} {r["interval"]} {r["start_date"]}->{r["end_date"]}' for r in runs}
    pick = st.multiselect("Runs to include (empty = latest 20)", list(label), format_func=label.get,
                          key=f"ins_runs_{sid}")
    if st.button("Analyze with Claude", type="primary", disabled=not runs or not generate.has_credentials()):
        try:
            with st.spinner("Claude is reviewing the results..."):
                insights.analyze(conn, sid, pick or None)
        except Exception as e:
            st.error(f"Analysis failed: {e}")
    for i, ins in enumerate(db.list_insights(conn, sid)):
        with st.expander(f'{ins["created_at"][:16]} · {len(ins["run_ids"])} runs · {ins["model"]}', expanded=i == 0):
            st.markdown(ins["content"])

    with st.expander("Delete strategy"):
        sure = st.checkbox(f'Yes, delete "{s["name"]}" with all its versions, runs, optimizations and insights',
                           key=f"del_{sid}")
        if st.button("Delete permanently", disabled=not sure):
            db.delete_strategy(conn, sid)
            state.pop("strategy_id", None)
            st.switch_page("ui/library.py")
```

- [ ] **Step 4: Run the UI tests**

Run: `$PY -m pytest tests/test_app.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add ui/strategy.py tests/test_app.py
git commit -m "Workbench UI: strategy page with code, backtest, optimize, history, insights"
```

---

### Task 15: Manual end-to-end check in the browser (dry run, then real)

**Files:** none (verification only; fix anything found in the file it belongs to, with a test where practical)

- [ ] **Step 1: Start the app in dry-run mode against a scratch DB**

Run (Git Bash, from the repo folder):
`WORKBENCH_DRY_RUN=1 WORKBENCH_DB=/tmp/wb-check.db .venv/Scripts/streamlit.exe run app.py --server.headless true --server.port 8501`
(run in the background; open http://localhost:8501 in the built-in browser)

- [ ] **Step 2: Walk the flow and check each result**

1. Create → Description → type "ema cross" → **Generate**. Expected: lands on the Strategy page titled "EMA Cross (dry run)".
2. Code tab: Pine and Python shown, no Pine check warnings, notes expander shows the dry-run note.
3. Market row: ticker `^NSEI`, interval `1d`. Backtest tab → **Run backtest**. Expected: stats cards, equity chart, trades table. **Open full interactive chart** shows the Bokeh chart.
4. Change ticker to `RELIANCE.NS`, run again. Then ticker `NOPE`, run. Expected: red "No data for NOPE ..." message, app still works.
5. Optimize tab: tick `fast_len` and `slow_len` → **Run optimization**. Expected: heatmap + table; select a row → **Load selected row** → toast; Backtest tab inputs show those values.
6. History tab: two runs listed; select both → comparison table; select one → save a note → note appears in the table.
7. Insights tab: set status "testing", rating 3, type a note → toast "Saved"; Library shows the status and rating. **Analyze with Claude** → dry-run analysis appears.
8. Code tab: break the Python (e.g. delete the `class` line), **Save edits as a new version**, then Backtest → **Run backtest**. Expected: error box with traceback and **Fix with Claude** (in dry run this returns the reference code as a new version).
9. Delete strategy (Insights → Delete) → back on Library, strategy gone.

- [ ] **Step 3: Real Claude check (needs `ANTHROPIC_API_KEY` in `.env`; costs a few cents to ~$1)**

Stop the dry-run server, start without `WORKBENCH_DRY_RUN`, then: Create → YouTube URL with a short strategy video → Generate. Expected: a strategy whose Pine compiles when pasted into TradingView, whose Python backtests on `^NSEI`. Then Import .pine → `ema-crossover-strategy.pine` → Import selected.
If no key is available yet, skip this step and say so in the hand-off.

- [ ] **Step 4: Stop the server and delete the scratch DB**

---

### Task 16: Docs and full test run

**Files:**
- Modify: `SETUP.md` (append section)

- [ ] **Step 1: Append to `SETUP.md`**

````markdown
## Strategy workbench (YouTube → Pine + Python backtest)

A local web app that turns a YouTube video, a description, or a `.pine` file from `projects/`
into a Pine Script v6 strategy (paste it into TradingView) **and** an equivalent Python strategy,
backtests it on yfinance data, tunes its parameters, and keeps every version, run, optimization
and insight in `workbench.db` (SQLite).

Setup (once):

```bash
cp .env.example .env              # then put your Anthropic API key in .env
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
```

Run:

```bash
.venv/Scripts/streamlit run app.py
```

Pages: **Create** (URL / description / import .pine), **Library** (all strategies, filter by
status and rating), **Strategy** (Code, Backtest, Optimize, History, Insights).

Tickers are yfinance symbols: `RELIANCE.NS`, `^NSEI`, `^NSEBANK`, `AAPL`, `BTC-USD`. Intraday data
is limited by yfinance (~60 days for 5m-30m, ~2 years for 1h).

Command line (same database):

```bash
.venv/Scripts/python -m workbench list
.venv/Scripts/python -m workbench new --url "https://www.youtube.com/watch?v=..."
.venv/Scripts/python -m workbench import projects/
.venv/Scripts/python -m workbench run ema-cross --ticker ^NSEI --param fast_len=12
.venv/Scripts/python -m workbench optimize ema-cross --range fast_len=5:20:5 --range slow_len=20:60:10
.venv/Scripts/python -m workbench analyze ema-cross
```

Notes:
- Back up by copying `workbench.db` while the app is stopped.
- Generated Python runs inside the app without a sandbox; only load strategies you generated.
- `WORKBENCH_DRY_RUN=1` runs everything without calling Claude (fixed EMA-cross example).
- Tests: `.venv/Scripts/python -m pytest`
````

- [ ] **Step 2: Run the full suite**

Run: `$PY -m pytest`
Expected: all tests pass (≈48 tests), no errors.

- [ ] **Step 3: Commit**

```bash
git add SETUP.md
git commit -m "Workbench: setup and usage docs"
```
