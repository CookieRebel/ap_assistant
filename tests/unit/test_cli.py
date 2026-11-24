import json

import pytest
from typer.testing import CliRunner

from ap_assistant.cli import app


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AP_DB", str(tmp_path / "ap.db"))


@pytest.mark.parametrize("command", ["approve", "reject"])
def test_missing_approver_is_refused(command, db):
    result = CliRunner().invoke(app, [command, "run-x"])

    assert result.exit_code == 2
    assert "Missing option" in result.output


def test_approve_without_callback_id_generates_one(db):
    runner = CliRunner()
    run_id = json.loads(runner.invoke(app, ["start", "fixtures/cases/FIN-001.json"]).output)["run_id"]

    result = runner.invoke(app, ["approve", run_id, "--approver", "colin"])

    assert result.exit_code == 0
    response = json.loads(result.output)
    assert response["state"] == "SUBMITTED"
    assert response["callback_id"].startswith("cb-")
