import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ap_assistant.cli import app

ROOT = Path(__file__).parents[2]
CORPUS = str(ROOT / "corpus")


def case(case_id):
    return str(ROOT / "fixtures" / "cases" / f"{case_id}.json")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AP_DB", str(tmp_path / "ap.db"))


@pytest.mark.parametrize("command", ["approve", "reject"])
def test_missing_approver_is_refused(command, db):
    result = CliRunner().invoke(app, [command, "run-x"])

    assert result.exit_code == 2
    assert "Missing option" in result.output


def test_start_without_ingest_is_refused(db):
    result = CliRunner().invoke(app, ["start", case("FIN-001")])

    assert result.exit_code == 1
    assert "ap_assistant ingest" in result.output


def test_crash_exit_code_and_resume(db, monkeypatch):
    runner = CliRunner()
    runner.invoke(app, ["ingest", CORPUS])
    monkeypatch.setenv("AP_CRASH_AFTER", "RECOMMENDED")

    crashed = runner.invoke(app, ["start", case("FIN-002")])
    monkeypatch.delenv("AP_CRASH_AFTER")
    resumed = runner.invoke(app, ["resume", "RUN-001", "--json"])

    assert crashed.exit_code == 75
    assert json.loads(resumed.output)["state"] == "AWAITING_APPROVAL"


def test_approve_without_callback_id_generates_one(db):
    runner = CliRunner()
    runner.invoke(app, ["ingest", CORPUS])
    run_id = json.loads(runner.invoke(app, ["start", case("FIN-001"), "--json"]).output)["run_id"]

    result = runner.invoke(app, ["approve", run_id, "--approver", "colin", "--json"])

    assert result.exit_code == 0
    response = json.loads(result.output)
    assert response["state"] == "SUBMITTED"
    assert response["callback_id"].startswith("cb-")


def test_summary_by_default_and_json_on_request(db):
    runner = CliRunner()
    runner.invoke(app, ["ingest", CORPUS])

    summary = runner.invoke(app, ["start", case("FIN-003")]).output
    approved = runner.invoke(app, ["approve", "RUN-001", "--approver", "alice"]).output
    full = runner.invoke(app, ["get", "RUN-001", "--json"]).output

    assert "Next: ap_assistant approve RUN-001 --approver alice" in summary
    assert "RUN-001  SUBMITTED" in approved
    assert "approved by alice (AP_MANAGER)" in approved
    assert json.loads(full)["recommendation"]["calculations"] is not None


def test_offline_flag_wins_over_a_live_model_in_env_file(db, tmp_path):
    (tmp_path / ".env").write_text("AP_LLM_MODEL=a-live-model\nOPENAI_API_KEY=not-a-key\n")
    runner = CliRunner()
    runner.invoke(app, ["ingest", CORPUS])

    result = runner.invoke(app, ["start", case("FIN-001"), "--offline", "--json"])

    assert json.loads(result.output)["grounding"]["model"] == "offline"


def test_env_file_wins_over_the_shell(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("AP_DB=from-env-file.db\n")
    monkeypatch.setenv("AP_DB", "from-shell.db")

    CliRunner().invoke(app, ["get", "RUN-999"])

    assert (tmp_path / "from-env-file.db").exists()
    assert not (tmp_path / "from-shell.db").exists()
