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


def test_start_without_ingest_is_refused(db):
    result = CliRunner().invoke(app, ["start", "fixtures/cases/FIN-001.json"])

    assert result.exit_code == 1
    assert "ap_assistant ingest" in result.output


def test_crash_exit_code_and_resume(db, monkeypatch):
    runner = CliRunner()
    runner.invoke(app, ["ingest", "corpus"])
    monkeypatch.setenv("AP_CRASH_AFTER", "RECOMMENDED")

    crashed = runner.invoke(app, ["start", "fixtures/cases/FIN-002.json"])
    monkeypatch.delenv("AP_CRASH_AFTER")
    resumed = runner.invoke(app, ["resume", "RUN-001"])

    assert crashed.exit_code == 75
    assert json.loads(resumed.output)["state"] == "AWAITING_APPROVAL"


def test_approve_without_callback_id_generates_one(db):
    runner = CliRunner()
    runner.invoke(app, ["ingest", "corpus"])
    run_id = json.loads(runner.invoke(app, ["start", "fixtures/cases/FIN-001.json"]).output)["run_id"]

    result = runner.invoke(app, ["approve", run_id, "--approver", "colin"])

    assert result.exit_code == 0
    response = json.loads(result.output)
    assert response["state"] == "SUBMITTED"
    assert response["callback_id"].startswith("cb-")
