"""Claude API calls: video/description/.pine -> Pine + Python, fix errors, analyze results."""
import contextlib
import importlib.util
import io
import json
import os
import re
from dataclasses import dataclass, field

import anthropic

from . import ROOT

# Models that accept server-side refusal fallbacks (fallbacks="default").
FALLBACK_PREFIXES = ("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1")


def model():
    return os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")


def has_credentials():
    return os.environ.get("WORKBENCH_DRY_RUN") == "1" or any(
        os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))


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
    if os.environ.get("WORKBENCH_DRY_RUN") == "1":
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
    if msg.stop_reason != "end_turn":
        raise GenerationError(f"Claude stopped unexpectedly ({msg.stop_reason}). Try again.")
    # After a server-side fallback the content is [declining model's text, "fallback" block, fallback
    # model's text]: only the text after the last fallback block is the answer.
    start = max((i for i, b in enumerate(msg.content) if b.type == "fallback"), default=-1) + 1
    text = "".join(b.text for b in msg.content[start:] if b.type == "text")
    return json.loads(text) if schema else text


def _generate(user, schema=SCHEMA):
    """Call Claude; if the Python breaks the contract, retry once with the error. A second
    failure is returned anyway, with a note, so the user can fix it in the app."""
    from .engine import StrategyContractError, load_strategy

    out = _call(user, schema)
    try:
        load_strategy(out["python"])
    except StrategyContractError as e:
        try:
            retry = _call(f"{user}\n\nYour previous Python:\n```python\n{out['python']}\n```\n"
                          f"It failed the contract check:\n{e}\nReturn the complete corrected answer.", schema)
        except (GenerationError, anthropic.APIError, ValueError) as e2:
            out["notes"] = [*out["notes"], f"Python fails the contract check ({e}); automatic retry failed: {e2}"]
            return out
        out = retry
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
        va_mod.set_status = lambda message: None  # no status-file side effects
        va_mod.clear_status = lambda: None
        va = va_mod.VideoAnalyzer()
        if importlib.util.find_spec("whisper") is None:  # the analyzer would pip install it silently
            va.get_transcript_from_whisper = lambda url: (None, "no captions and Whisper is not installed")
        video_id = va.extract_video_id(url)
        if not video_id:
            raise GenerationError(f"Not a YouTube video URL: {url}")
        title = va.get_video_metadata(url).get("title")
        if not title or title == "Unknown":
            title = video_id
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
