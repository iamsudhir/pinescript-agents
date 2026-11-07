import pytest
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


def _setup(tmp_path, goog, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DB", str(tmp_path / "cli.db"))
    monkeypatch.setenv("WORKBENCH_DRY_RUN", "1")
    monkeypatch.setattr(actions.data, "load_data", lambda conn, ticker, interval, start, end: goog)
    conn = db.connect()
    db.create_strategy(conn, "Sma Cross", "description", python_code=SMA_CODE)
    return conn


def test_cli_new_import_analyze_in_dry_run(tmp_path, goog, monkeypatch, capsys):
    conn = _setup(tmp_path, goog, monkeypatch)
    main(["new", "--desc", "ema"])
    assert "created" in capsys.readouterr().out

    folder = tmp_path / "pines"
    folder.mkdir()
    (folder / "a.pine").write_text('//@version=6\nstrategy("A")\n', encoding="utf-8")
    main(["import", str(folder)])
    assert "imported" in capsys.readouterr().out
    main(["import", str(folder)])
    assert "skip" in capsys.readouterr().out

    main(["run", "sma-cross", "--start", "2005-01-01", "--end", "2010-01-01"])
    capsys.readouterr()
    main(["analyze", "sma-cross"])
    assert capsys.readouterr().out.startswith("## ")


def test_cli_import_folder_continues_after_a_bad_file(tmp_path, goog, monkeypatch, capsys):
    _setup(tmp_path, goog, monkeypatch)
    folder = tmp_path / "pines"
    folder.mkdir()
    (folder / "a-bad.pine").write_bytes(b"\xff\xfe\x00bad")
    (folder / "b.pine").write_text('//@version=6\nstrategy("B")\n', encoding="utf-8")
    main(["import", str(folder)])
    out = capsys.readouterr().out
    assert "failed a-bad.pine" in out and "imported" in out


@pytest.mark.parametrize("argv", [
    ["run", "sma-cross", "--param", "n1"],
    ["optimize", "sma-cross", "--range", "n1=5:10"],
    ["optimize", "sma-cross", "--range", "n1"],
    ["run", "sma-cross", "--param", "nope=1"],
    ["run", "no-such-slug"],
])
def test_cli_bad_input_exits_with_message(tmp_path, goog, monkeypatch, argv):
    _setup(tmp_path, goog, monkeypatch)
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None)
