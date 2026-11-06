# Strategy Workbench — Design

Date: 2026-11-07
Status: approved in chat, pending spec review

## Goal

Turn this repo from "Claude writes Pine in a chat" into a local framework where you can:

1. Paste a YouTube URL (or type a description) and get **both** a Pine Script v6 file
   (pasted manually into TradingView) **and** an equivalent Python strategy.
2. Backtest the Python strategy on yfinance data, any time, on any ticker/interval/date range.
3. Tune the strategy's parameters from a UI: single runs with chosen values, and grid optimization.
4. Keep everything (strategies, code versions, price data, runs, optimization results) in a
   database for later use.
5. Import the ~30 existing `projects/*.pine` scripts into the same library.

## Decisions

| Topic | Choice |
|---|---|
| Code generation | Anthropic API (`anthropic` SDK), key in `.env` as `ANTHROPIC_API_KEY`, model from `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`) |
| UI | Streamlit, local (`streamlit run app.py`) |
| Data | yfinance now; Dhan later behind the same `load_data()` function |
| Backtest engine | `backtesting.py` (`Backtest.run`, `Backtest.optimize`) |
| Persistence | SQLite, single file `workbench.db` (stdlib `sqlite3`, no ORM) |
| Out of scope | Dhan data, live/paper trading, batch URL processing, walk-forward, portfolio backtests |

## Architecture

```
app.py  (Streamlit UI only — no business logic)
  │
  ├── workbench/generate.py   URL/description/.pine → Claude API → {pine, python, notes}
  │       └── reuses tools/video-analyzer.py (VideoAnalyzer) for transcript + metadata
  ├── workbench/engine.py     load strategy class from source, list params, run(), optimize()
  ├── workbench/data.py       load_data(ticker, interval, start, end) with DB cache (yfinance)
  └── workbench/db.py         all SQLite reads/writes; schema creation; nothing else

workbench/__main__.py         CLI: python -m workbench run|optimize|list|import ...
workbench.db                  the database (gitignored)
```

Each module has one job and is usable without the UI. The CLI and the UI call the same functions.

## Database schema (`workbench/db.py`)

```sql
strategies(
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL,         -- 'youtube' | 'description' | 'pine_import'
  source TEXT,                       -- URL, description text, or original .pine path
  transcript TEXT,                   -- NULL unless youtube
  notes TEXT,                        -- Claude's translation caveats (JSON list)
  default_ticker TEXT DEFAULT '^NSEI',
  default_interval TEXT DEFAULT '1d',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)

strategy_versions(                   -- every save of code creates a new row; latest = current
  id INTEGER PRIMARY KEY,
  strategy_id INTEGER NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,          -- 1, 2, 3 ... per strategy
  pine_code TEXT NOT NULL,
  python_code TEXT NOT NULL,
  change_note TEXT,                  -- 'generated', 'manual edit', 'fix with Claude: <error>'
  created_at TEXT NOT NULL,
  UNIQUE(strategy_id, version)
)

runs(
  id INTEGER PRIMARY KEY,
  strategy_version_id INTEGER NOT NULL REFERENCES strategy_versions(id) ON DELETE CASCADE,
  ticker TEXT NOT NULL, interval TEXT NOT NULL,
  start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  cash REAL NOT NULL, commission REAL NOT NULL,
  params TEXT NOT NULL,              -- JSON {name: value}
  stats TEXT NOT NULL,               -- JSON of key stats (see below)
  trades TEXT NOT NULL,              -- JSON records of backtesting.py _trades
  equity TEXT NOT NULL,              -- JSON [[iso_ts, equity], ...]
  created_at TEXT NOT NULL
)

optimizations(
  id INTEGER PRIMARY KEY,
  strategy_version_id INTEGER NOT NULL REFERENCES strategy_versions(id) ON DELETE CASCADE,
  ticker TEXT NOT NULL, interval TEXT NOT NULL,
  start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  cash REAL NOT NULL, commission REAL NOT NULL,
  ranges TEXT NOT NULL,              -- JSON {param: [min, max, step]}
  maximize TEXT NOT NULL,            -- 'Return [%]' | 'Sharpe Ratio' | 'Return/MaxDD'
  results TEXT NOT NULL,             -- JSON records: one row per combination (params + key stats)
  best_params TEXT NOT NULL,         -- JSON
  created_at TEXT NOT NULL
)

price_bars(
  ticker TEXT NOT NULL, interval TEXT NOT NULL, ts TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY (ticker, interval, ts)
)
```

Key stats stored per run: Return [%], Buy & Hold Return [%], CAGR [%], Sharpe Ratio,
Max. Drawdown [%], Win Rate [%], # Trades, Profit Factor, Expectancy [%], Exposure Time [%].

Charts are **not** stored: `chart.html` is regenerated on demand by re-running the stored
version + params on cached bars (deterministic and fast). PRAGMA `foreign_keys=ON`,
`journal_mode=WAL`.

## Strategy contract (enforced by prompt and by `engine.load_strategy`)

`python_code` must:

- define exactly one subclass of `backtesting.Strategy`;
- expose every tunable value as a class attribute of type `int`, `float` or `bool`
  (these become the UI parameters, names and defaults matching the Pine `input.*` calls);
- compute indicators in `init()` via `self.I(...)` using only `numpy`, `pandas`
  (and `backtesting.lib` helpers) — no network or file access, no data loading;
- trade in `next()` with `self.buy/sell/position.close`, using `sl=`/`tp=` for stops/targets.

`engine.load_strategy(code)` executes the code in a fresh module namespace, finds the single
`Strategy` subclass, and returns `(cls, params)` where `params` is
`{name: default}` for public int/float/bool class attributes. Violations raise
`StrategyContractError` with a readable message (shown in UI, usable by "Fix with Claude").

## Components

### `workbench/data.py`
`load_data(ticker, interval, start, end) -> DataFrame[Open, High, Low, Close, Volume]`
- Reads `price_bars`; fetches only missing ranges from yfinance (`auto_adjust=True`), upserts.
- Flattens yfinance MultiIndex columns; drops NaN rows; raises `DataError` on empty result
  (e.g. bad ticker, intraday interval beyond yfinance's history limit — message says which).
- Today's bar is never cached (it is still forming).

### `workbench/engine.py`
- `load_strategy(code) -> (cls, params)` — see contract.
- `run(code, df, params, cash=1_000_000, commission=0.0005) -> RunResult(stats, trades, equity, bt)`
- `optimize(code, df, ranges, maximize, cash, commission, max_tries=500) -> OptResult(results_df, best_params)`
  uses `Backtest.optimize(..., return_heatmap=True)`; `Return/MaxDD` implemented as a callable.
  Grids larger than `max_tries` are randomly sampled (backtesting.py `max_tries`).
- `chart_html(run_result) -> str` via `bt.plot(open_browser=False, filename=tmp)`.

### `workbench/generate.py`
- `from_youtube(url) -> Generated` — `VideoAnalyzer().analyze(url)` for transcript/metadata, then Claude.
- `from_description(text) -> Generated`
- `from_pine(pine_code, name) -> Generated` — keeps given Pine, asks Claude for the Python only.
- `fix(pine, python, error) -> Generated` — returns corrected Python (and Pine if relevant).
- One `messages.create` call each, system prompt = repo `CLAUDE.md` + `skills/pine-developer/SKILL.md`
  + the strategy contract + a reference example (SMA cross in both languages).
- Output via a tool/JSON schema: `{name, slug, pine, python, notes[]}`. Invalid JSON or a
  contract failure → one automatic retry with the error appended; then surface the error.
- After generation, Pine is linted with `scripts/validate-pine.sh` if bash is available; warnings
  shown, never blocking.

### `workbench/db.py`
Plain functions: `connect()`, `init_schema()`, `create_strategy`, `add_version`,
`list_strategies` (with latest + best run summary), `get_strategy`, `latest_version`,
`save_run`, `list_runs`, `save_optimization`, `list_optimizations`, `delete_strategy`,
price-bar `get_bars`/`upsert_bars`. Path from `WORKBENCH_DB` env var, default `workbench.db`.

### `app.py` (Streamlit)
Sidebar navigation: **Create**, **Library**, **Strategy**.

1. **Create** — tabs: *YouTube URL* | *Description* | *Import .pine* (picker over `projects/*.pine`,
   plus "Import all" with progress). Generate → saves strategy v1 → opens it in Strategy page.
2. **Library** — table: name, source type, created, latest run Return/Sharpe/MaxDD, best
   optimization metric; search box; delete with confirm.
3. **Strategy** (selected strategy) — tabs:
   - **Code**: Pine and Python editors (`st.text_area`, monospace), Save → new version,
     version selector, copy/download buttons, **Fix with Claude** (pre-filled with last error).
   - **Backtest**: ticker / interval / start / end / cash / commission; auto-generated widgets
     per param (`number_input` for int/float, `checkbox` for bool); Run → stats cards, equity
     line chart, trades table, "Open full chart" (bt.plot HTML via `components.html`). Saved to `runs`.
   - **Optimize**: per numeric param: include?, min, max, step; maximize selector; Run →
     sortable results table, heatmap when exactly 2 params, "Use these params" → Backtest tab.
     Saved to `optimizations`.
   - **History**: runs and optimizations for this strategy (all versions), multi-select runs to
     compare stats side by side, reopen any run (loads its params + version into Backtest).

### CLI (`python -m workbench`)
- `list`
- `run <slug> [--ticker --interval --start --end] [--param name=value ...]`
- `optimize <slug> --range name=min:max:step ... [--maximize ...]`
- `new --url URL | --desc TEXT`
- `import <path.pine | projects/>`

## Error handling

- Missing `ANTHROPIC_API_KEY` → Create page shows setup instructions instead of the form.
- No captions and no Whisper → clear message suggesting the Description tab with a pasted summary.
- Generated code exceptions (contract or runtime) → traceback in UI + "Fix with Claude"; never crash the app.
- Strategy code runs in-process (`exec`). Accepted risk: code comes from your own Claude account;
  documented in README. ponytail: no sandbox; add subprocess isolation if code from others is ever loaded.
- yfinance failures → `DataError` message; cached data still usable offline.

## Testing

`tests/test_workbench.py` (pytest), offline, using a fixed CSV fixture `tests/data/sample_1d.csv`
and a temp DB:
- `load_strategy` finds params; rejects code with zero/two Strategy classes.
- `run` returns stats with expected keys; a known SMA-cross on the fixture gives a stable trade count.
- `optimize` returns one row per combination and a best_params dict.
- db round-trip: create strategy → add version → save run → list shows summary; cascade delete.
- `data.load_data` with yfinance monkeypatched: second call hits the cache only for the cached range.

Claude API calls are not unit-tested; `generate.py` has a `--dry-run` path that returns the
reference example for UI testing without a key.

## Dependencies

Add to `requirements.txt`: `streamlit`, `anthropic`, `yfinance`, `backtesting`, `python-dotenv`,
`pytest`. `.gitignore`: `workbench.db*`.

## Later (not in this build)

Dhan data source in `data.py`; walk-forward / out-of-sample split in Optimize; scheduled re-runs.
