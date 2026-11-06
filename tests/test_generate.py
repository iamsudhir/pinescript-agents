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
