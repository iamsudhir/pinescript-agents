from backtesting.test import GOOG
from conftest import SMA_CODE
from streamlit.testing.v1 import AppTest

from workbench import actions, db


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


def test_strategy_page_interaction(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DB", str(tmp_path / "ui.db"))
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "1")
    monkeypatch.setattr(actions.data, "load_data", lambda *a, **k: GOOG.copy())
    conn = db.connect()
    a = db.create_strategy(conn, "A", "description", python_code=SMA_CODE, pine_code="//@version=6")
    db.update_strategy(conn, a, default_ticker="AAA.NS", default_interval="1h")
    b = db.create_strategy(conn, "B", "description", python_code=SMA_CODE, pine_code="//@version=6")
    vid = db.latest_version(conn, b)["id"]

    at = AppTest.from_file("../app.py", default_timeout=60).run()
    at.session_state["strategy_id"] = a
    at.switch_page("ui/strategy.py").run()
    assert not at.exception
    assert at.text_input[0].value == "AAA.NS"

    at.session_state["strategy_id"] = b  # market settings must not leak from the strategy opened before
    at.run()
    assert not at.exception
    assert (at.text_input[0].value, at.selectbox[1].value) == ("^NSEI", "1d")

    next(b for b in at.button if b.label == "Run backtest").click().run()
    assert not at.exception
    assert any(m.label == "Return [%]" for m in at.metric)

    next(n for n in at.number_input if n.label == "n2").set_value(25).run()  # not optimized: must reset on load
    at.checkbox(key=f"o_{vid}_p_n1").check().run()
    next(b for b in at.button if b.label.startswith("Run optimization")).click().run()
    assert not at.exception
    opt = db.list_optimizations(conn, b)[0]
    at.button(key=f"use_opt_{opt['id']}").click().run()
    assert not at.exception
    assert next(n for n in at.number_input if n.label == "n1").value == opt["best_params"]["n1"]
    assert next(n for n in at.number_input if n.label == "n2").value == 20
    assert not at.exception
