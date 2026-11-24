from pathlib import Path

import pytest

from ap_assistant import workflow
from ap_assistant.schemas import CaseRequest
from ap_assistant.store import Store
from ap_assistant.workflow import WorkflowError

CASES = Path(__file__).parents[2] / "fixtures" / "cases"


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "ap.db")


def start(store, case_id):
    request = CaseRequest.model_validate_json((CASES / f"{case_id}.json").read_text())
    return workflow.start(store, request)


def test_start_waits_for_approval(store):
    run = start(store, "FIN-001")

    assert run["state"] == "AWAITING_APPROVAL"
    assert run["recommendation"]["outcome"] == "APPROVE_FOR_POSTING"
    assert run["decisions"] == []


def test_approve_submits_once(store):
    run_id = start(store, "FIN-001")["run_id"]

    response = workflow.approve(store, run_id, "u-1", "COST_CENTRE_MANAGER", "cb-1")

    assert response["state"] == "SUBMITTED"
    assert response["submitted"]["idempotency_key"] == f"{run_id}:APPROVE_FOR_POSTING"
    assert len(workflow.get_run(store, run_id)["decisions"]) == 1


def test_repeated_callback_returns_the_same_response(store):
    run_id = start(store, "FIN-005")["run_id"]

    first = workflow.approve(store, run_id, "u-1", "COST_CENTRE_MANAGER", "cb-5")
    second = workflow.approve(store, run_id, "u-1", "COST_CENTRE_MANAGER", "cb-5")

    assert first == second
    assert len(workflow.get_run(store, run_id)["decisions"]) == 1


def test_reject_submits_nothing(store):
    run_id = start(store, "FIN-001")["run_id"]

    response = workflow.reject(store, run_id, "u-1", "COST_CENTRE_MANAGER", "cb-r")

    assert response["state"] == "REJECTED_BY_APPROVER"
    assert workflow.get_run(store, run_id)["decisions"] == []


def test_wrong_role_is_refused(store):
    run_id = start(store, "FIN-003")["run_id"]

    with pytest.raises(WorkflowError):
        workflow.approve(store, run_id, "u-1", "COST_CENTRE_MANAGER", "cb-3")

    run = workflow.get_run(store, run_id, with_events=True)
    assert run["state"] == "AWAITING_APPROVAL"
    assert run["decisions"] == []
    assert run["events"][-1]["type"] == "approval_refused"


def test_second_approval_with_new_callback_is_refused(store):
    run_id = start(store, "FIN-001")["run_id"]
    workflow.approve(store, run_id, "u-1", "COST_CENTRE_MANAGER", "cb-a")

    with pytest.raises(WorkflowError):
        workflow.approve(store, run_id, "u-1", "COST_CENTRE_MANAGER", "cb-b")
    assert len(workflow.get_run(store, run_id)["decisions"]) == 1


def test_submit_without_approval_is_refused(store):
    run_id = start(store, "FIN-001")["run_id"]

    with pytest.raises(WorkflowError):
        workflow.submit_finance_decision(store, run_id, "APPROVE_FOR_POSTING", f"{run_id}:APPROVE_FOR_POSTING", "cb-x")


def test_run_survives_a_new_process(tmp_path):
    run_id = start(Store(tmp_path / "ap.db"), "FIN-001")["run_id"]

    reopened = Store(tmp_path / "ap.db")
    response = workflow.approve(reopened, run_id, "u-1", "COST_CENTRE_MANAGER", "cb-1")

    assert response["state"] == "SUBMITTED"
