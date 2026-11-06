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
