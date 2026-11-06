# Setup and architecture

## What this repo is

pinescript-agents is not a standalone app. It is a **Claude Code workspace**: a set of
instructions, skills, docs and tools that turn Claude Code into a Pine Script v6
developer for TradingView. You run `claude` in this folder, describe an indicator or
strategy, and Claude writes `.pine` files into `projects/`. Backtesting itself happens
in TradingView's Strategy Tester after you paste the script there.

```
CLAUDE.md               Rules Claude follows (syntax gotchas, limits, quality checklist)
.claude-plugin/         Plugin manifest ("pinescript"), so skills show as /pinescript:*
skills/                 The "agents": one SKILL.md per role
  pine-developer          writes code          pine-debugger     fixes errors
  pine-backtester         adds metrics         pine-optimizer    perf/UX
  pine-visualizer         breaks down ideas    pine-publisher    publication prep
  pine-manager            orchestrates the above
  start/create/video/templates/examples   user-facing slash commands
agents/                 Subagents: pine-reviewer, pine-explorer, beginner-helper
hooks/hooks.json        After every Write/Edit runs scripts/validate-pine.sh (lint for
                        missing //@version, repainting, split ternaries, alert annotation)
.claude/                Older copy of skills/commands/hooks (pre-plugin layout)
.mcp.json               Registers the "pinescript" docs MCP server below

docs/manual, docs/docs  Pine Script v6 reference + user guide (markdown, ~8 MB)
docs/server/            TypeScript MCP server indexing those docs. Tools:
                        pine_search, pine_reference, pine_guide, pine_examples, pine_categories
docs/pine-error-log.md  Running log of real compiler errors and fixes (Claude appends to it)

templates/              Starter indicators, strategies, utilities
examples/               Reference scripts by difficulty
projects/               Your scripts (about 30 already: strategies + indicators)
thepatternsite/         242 Bulkowski chart/candle/harmonic pattern specs as markdown
tools/video-analyzer.py YouTube URL -> transcript -> strategy spec JSON (projects/analysis/)
tools/traderspost-to-pine.py  TradersPost trade CSV -> Pine arrays for traderspost-replay.pine
```

## Requirements

- Python 3.10+ (video tools), Node 18+ (docs MCP server)
- Windows: run `setup.sh` from Git Bash. Install Python with `winget install Python.Python.3.12`
  and turn off the python/python3 "App execution aliases" (Settings > Apps > Advanced app settings)
- [Claude Code](https://claude.ai/code) CLI or IDE extension
- Optional: `ffmpeg` and `pip install openai-whisper` for videos without captions
- The Pine-in-Claude-Code workflow needs no API keys (Claude Code uses your own Claude login). The Strategy workbench needs an Anthropic API key in `.env`.

## Install

```bash
git clone https://github.com/iamsudhir/pinescript-agents.git
cd pinescript-agents
./setup.sh
```

`setup.sh` checks prerequisites, creates `.venv/` with the Python deps, runs
`npm ci` in `docs/server`, and runs the server's test suite. Re-run it any time.

## Use

```bash
claude            # approve the "pinescript" MCP server when prompted
> start           # guided wizard
> Create an RSI mean-reversion strategy with ATR stops
```

Video analysis directly from the shell:

```bash
source .venv/bin/activate      # Windows Git Bash: source .venv/Scripts/activate
python tools/video-analyzer.py "https://youtube.com/watch?v=..."
```

Docs server on its own (stdio MCP, mainly for debugging):

```bash
npm --prefix docs/server start     # or: npm --prefix docs/server test
```

Testing a strategy: copy the `.pine` file from `projects/` into TradingView's Pine Editor,
add it to a chart, and open the Strategy Tester tab.

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
.venv/Scripts/python -m workbench list   # (slugs: see `list`)
.venv/Scripts/python -m workbench new --url "https://www.youtube.com/watch?v=..."
.venv/Scripts/python -m workbench import projects/
.venv/Scripts/python -m workbench run <slug> --ticker ^NSEI --param fast_len=12
.venv/Scripts/python -m workbench optimize <slug> --range fast_len=5:20:5 --range slow_len=20:60:10
.venv/Scripts/python -m workbench analyze <slug>
```

Notes:
- Back up by copying `workbench.db` while the app is stopped.
- Generated Python runs inside the app as soon as it is generated. A check blocks imports other than
  numpy/pandas/math/backtesting and obvious escape routes, but it is not a sandbox, and a YouTube transcript
  is third-party text that can steer what Claude writes. Prefer videos from sources you trust, and read the
  generated Python before relying on it.
- Price data is cached; yfinance adjusts history for splits/dividends, so after a corporate action an old
  cached range and a newer fetch can differ slightly. To force a clean re-download, start a fresh DB
  (delete `workbench.db`; this also deletes your strategies and runs, so back it up first).
- Videos without captions need Whisper (`pip install openai-whisper`); the app never installs it for you.
- `WORKBENCH_DRY_RUN=1` runs everything without calling Claude (fixed EMA-cross example).
- Tests: `.venv/Scripts/python -m pytest`
