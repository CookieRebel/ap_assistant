from pathlib import Path

import pytest

from ap_assistant import workflow
from ap_assistant.ingestion import read_corpus
from ap_assistant.llm import ModelReply
from ap_assistant.schemas import CaseRequest
from ap_assistant.store import Store
from ap_assistant.workflow import SimulatedCrash, WorkflowError

ROOT = Path(__file__).parents[2]
CASES = ROOT / "fixtures" / "cases"


def ingested_store(path):
    store = Store(path)
    store.replace_chunks(read_corpus(ROOT / "corpus"))
    return store


@pytest.fixture
def store(tmp_path):
    return ingested_store(tmp_path / "ap.db")


def request(case_id):
    return CaseRequest.model_validate_json((CASES / f"{case_id}.json").read_text())


def start(store, case_id, **kwargs):
    return workflow.start(store, request(case_id), **kwargs)


class BrokenModel:
    name = "broken"

    def complete(self, messages, tools):
        return ModelReply(text="not json")


def tool_attempts(run):
    return [e["tool"] for e in run["events"] if e["type"] == "tool_attempt"]


def test_start_without_chunks_is_refused(tmp_path):
    with pytest.raises(WorkflowError, match="ap_assistant ingest"):
        start(Store(tmp_path / "empty.db"), "FIN-001")


def test_start_grounds_the_recommendation(store):
    run = start(store, "FIN-001")

    assert run["grounding"]["model"] == "offline"
    assert run["grounding"]["citations"][0]["document_id"] == "FIN-POL-003"


def test_crash_after_evidence_resumes_without_repeated_lookups(store):
    with pytest.raises(SimulatedCrash):
        start(store, "FIN-001", crash_after="EVIDENCE_COLLECTED")
    assert workflow.get_run(store, "RUN-001")["state"] == "EVIDENCE_COLLECTED"

    run = workflow.resume(store, "RUN-001")

    run = workflow.get_run(store, "RUN-001", with_events=True)
    assert run["state"] == "AWAITING_APPROVAL"
    assert run["recommendation"]["outcome"] == "APPROVE_FOR_POSTING"
    assert sorted(tool_attempts(run)) == ["check_invoice_history", "get_purchase_order", "get_vendor_record"]


def test_failed_grounding_blocks_approval_and_resumes_at_grounding(store):
    run = start(store, "FIN-001", model=BrokenModel())
    assert run["state"] == "GROUNDING_FAILED"
    assert run["grounding"] is None
    assert "not valid JSON" in run["error"]
    with pytest.raises(WorkflowError):
        workflow.approve(store, run["run_id"], "colin", "cb-1")

    workflow.resume(store, run["run_id"])

    run = workflow.get_run(store, run["run_id"], with_events=True)
    assert run["state"] == "AWAITING_APPROVAL"
    assert run["error"] is None
    assert len(tool_attempts(run)) == 3


def test_resume_of_a_waiting_run_is_refused(store):
    run_id = start(store, "FIN-001")["run_id"]

    with pytest.raises(WorkflowError, match="only a run that stopped"):
        workflow.resume(store, run_id)


def test_run_ids_are_sequential(store):
    assert [start(store, "FIN-001")["run_id"] for _ in range(3)] == ["RUN-001", "RUN-002", "RUN-003"]


def test_start_waits_for_approval(store):
    run = start(store, "FIN-001")

    assert run["state"] == "AWAITING_APPROVAL"
    assert run["recommendation"]["outcome"] == "APPROVE_FOR_POSTING"
    assert run["decisions"] == []


def test_approve_submits_once(store):
    run_id = start(store, "FIN-001")["run_id"]

    response = workflow.approve(store, run_id, "colin", "cb-1")

    assert response["state"] == "SUBMITTED"
    assert response["submitted"]["idempotency_key"] == f"{run_id}:APPROVE_FOR_POSTING"
    assert len(workflow.get_run(store, run_id)["decisions"]) == 1


def test_repeated_callback_returns_the_same_response(store):
    run_id = start(store, "FIN-005")["run_id"]

    first = workflow.approve(store, run_id, "colin", "cb-5")
    second = workflow.approve(store, run_id, "colin", "cb-5")

    assert first == second
    assert len(workflow.get_run(store, run_id)["decisions"]) == 1


def test_reject_submits_nothing(store):
    run_id = start(store, "FIN-001")["run_id"]

    response = workflow.reject(store, run_id, "colin", "cb-r")

    assert response["state"] == "REJECTED_BY_APPROVER"
    run = workflow.get_run(store, run_id)
    assert run["decisions"] == []
    [approval] = run["approvals"]
    assert (approval["approver_id"], approval["role"], approval["decision"]) == ("colin", "COST_CENTRE_MANAGER", "REJECTED")


def test_wrong_role_is_refused(store):
    run_id = start(store, "FIN-003")["run_id"]

    with pytest.raises(WorkflowError):
        workflow.approve(store, run_id, "colin", "cb-3")

    run = workflow.get_run(store, run_id, with_events=True)
    assert run["state"] == "AWAITING_APPROVAL"
    assert run["decisions"] == []
    assert run["events"][-1]["type"] == "approval_refused"


def test_higher_role_may_approve(store):
    run_id = start(store, "FIN-001")["run_id"]

    response = workflow.approve(store, run_id, "cliff", "cb-1")

    assert response["state"] == "SUBMITTED"


def test_hold_is_approved_by_ap_manager(store):
    run_id = start(store, "FIN-003")["run_id"]

    response = workflow.approve(store, run_id, "alice", "cb-3")

    assert response["submitted"]["outcome"] == "HOLD_FOR_INFORMATION"


def test_unknown_approver_is_refused(store):
    run_id = start(store, "FIN-001")["run_id"]

    with pytest.raises(WorkflowError, match="not in the authority register"):
        workflow.approve(store, run_id, "mallory", "cb-1")
    assert workflow.get_run(store, run_id)["state"] == "AWAITING_APPROVAL"


def test_second_approval_with_new_callback_is_refused(store):
    run_id = start(store, "FIN-001")["run_id"]
    workflow.approve(store, run_id, "colin", "cb-a")

    with pytest.raises(WorkflowError):
        workflow.approve(store, run_id, "colin", "cb-b")
    assert len(workflow.get_run(store, run_id)["decisions"]) == 1


def test_submit_without_approval_is_refused(store):
    run_id = start(store, "FIN-001")["run_id"]

    with pytest.raises(WorkflowError):
        workflow.submit_finance_decision(store, run_id, "APPROVE_FOR_POSTING", f"{run_id}:APPROVE_FOR_POSTING", "cb-x")


def test_run_survives_a_new_process(tmp_path):
    run_id = start(ingested_store(tmp_path / "ap.db"), "FIN-001")["run_id"]

    reopened = Store(tmp_path / "ap.db")
    response = workflow.approve(reopened, run_id, "colin", "cb-1")

    assert response["state"] == "SUBMITTED"
