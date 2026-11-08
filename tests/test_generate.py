import json
from types import SimpleNamespace as NS

import pytest

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
    assert "found 0" in prompts[1] and "x = 1" in prompts[1]


def test_failed_retry_keeps_first_answer_with_note(monkeypatch):
    calls = []

    def fake_call(user, schema=generate.SCHEMA, system=None):
        calls.append(user)
        if len(calls) == 2:
            raise generate.GenerationError("boom")
        return {"name": "x", "pine": "p", "python": "x = 1", "notes": []}

    monkeypatch.setattr(generate, "_call", fake_call)
    g = generate.from_description("d")
    assert g.python == "x = 1" and "automatic retry failed: boom" in g.notes[-1]


def test_has_credentials(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "WORKBENCH_DRY_RUN"):
        monkeypatch.delenv(k, raising=False)
    assert not generate.has_credentials()
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "1")
    assert generate.has_credentials()
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "0")
    assert not generate.has_credentials()


class FakeClient:
    """Stands in for anthropic.Anthropic(): .beta.messages.stream(**params) -> context manager."""
    seen = []

    def __init__(self, msg):
        self.beta = NS(messages=NS(stream=self._stream))
        self.msg = msg

    def _stream(self, **params):
        FakeClient.seen.append(params)
        msg = self.msg

        class Ctx:
            def __enter__(self):
                return NS(get_final_message=lambda: msg)

            def __exit__(self, *a):
                return False
        return Ctx()


def _msg(stop_reason, *blocks):
    return NS(stop_reason=stop_reason, stop_details=None, content=[NS(type=t, text=x) for t, x in blocks])


def _use(monkeypatch, msg):
    monkeypatch.delenv("WORKBENCH_DRY_RUN", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    FakeClient.seen = []
    monkeypatch.setattr(generate.anthropic, "Anthropic", lambda: FakeClient(msg))


def test_call_uses_only_text_after_the_last_fallback_block(monkeypatch):
    good = {"name": "n", "pine": "p", "python": "y", "notes": []}
    _use(monkeypatch, _msg("end_turn", ("text", '{"name": "par'), ("fallback", ""), ("text", json.dumps(good))))
    assert generate._call("hi") == good
    assert FakeClient.seen[0]["fallbacks"] == "default"


@pytest.mark.parametrize("reason", ["pause_turn", "refusal", "max_tokens"])
def test_call_raises_on_incomplete_answers(monkeypatch, reason):
    _use(monkeypatch, _msg(reason, ("text", "{}")))
    with pytest.raises(generate.GenerationError):
        generate._call("hi")


def _stub_analyzer(tmp_path, monkeypatch, valid_url=True, transcript=("text", "captions"), via_whisper=False):
    get = ("self.get_transcript_from_youtube(video_id); return self.get_transcript_from_whisper(url)"
           if via_whisper else f"return {transcript!r}")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "video-analyzer.py").write_text(f"""
CACHE_DIR = ANALYSIS_DIR = None
def set_status(m): raise RuntimeError("status file touched")
def clear_status(): raise RuntimeError("status file touched")

class VideoAnalyzer:
    def extract_video_id(self, url): return "vid1" if {valid_url!r} else None
    def get_video_metadata(self, url): return {{"title": "Unknown"}}
    def get_transcript_from_youtube(self, video_id): return None, "disabled"
    def get_transcript_from_whisper(self, url): raise AssertionError("would pip install whisper")
    def get_transcript(self, url, video_id):
        {get}
""", encoding="utf-8")
    monkeypatch.setattr(generate, "ROOT", tmp_path)


def test_fetch_transcript_success_falls_back_to_video_id_for_title(tmp_path, monkeypatch):
    _stub_analyzer(tmp_path, monkeypatch)
    assert generate.fetch_transcript("https://youtu.be/vid1") == ("vid1", "text")


def test_fetch_transcript_rejects_bad_url(tmp_path, monkeypatch):
    _stub_analyzer(tmp_path, monkeypatch, valid_url=False)
    with pytest.raises(generate.GenerationError, match="Not a YouTube"):
        generate.fetch_transcript("nope")


def test_fetch_transcript_without_captions_explains_options(tmp_path, monkeypatch):
    _stub_analyzer(tmp_path, monkeypatch, transcript=(None, "x"))
    with pytest.raises(generate.GenerationError, match="Whisper.*Description"):
        generate.fetch_transcript("https://youtu.be/vid1")


def test_fetch_transcript_never_installs_whisper(tmp_path, monkeypatch):
    _stub_analyzer(tmp_path, monkeypatch, via_whisper=True)
    monkeypatch.setattr(generate.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(generate.GenerationError, match="captions: disabled; Whisper is not installed"):
        generate.fetch_transcript("https://youtu.be/vid1")
