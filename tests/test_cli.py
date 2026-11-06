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
