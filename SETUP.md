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

- Python 3.9+ (video tools), Node 18+ (docs MCP server)
- [Claude Code](https://claude.ai/code) CLI or IDE extension
- Optional: `ffmpeg` and `pip install openai-whisper` for videos without captions
- No API keys or secrets are needed. Claude Code uses your own Claude login.

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
source .venv/bin/activate
python tools/video-analyzer.py "https://youtube.com/watch?v=..."
```

Docs server on its own (stdio MCP, mainly for debugging):

```bash
npm --prefix docs/server start     # or: npm --prefix docs/server test
```

Testing a strategy: copy the `.pine` file from `projects/` into TradingView's Pine Editor,
add it to a chart, and open the Strategy Tester tab.
