from pathlib import Path

import pytest

from ap_assistant import output, workflow
from ap_assistant.ingestion import read_corpus
from ap_assistant.llm import ModelReply
from ap_assistant.schemas import CaseRequest
from ap_assistant.store import Store

ROOT = Path(__file__).parents[2]


class BrokenModel:
    name = "broken"

    def complete(self, messages, tools):
        return ModelReply(text="not json")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "ap.db")
    s.replace_chunks(read_corpus(ROOT / "corpus"))
    return s


def start(store, case_id, **kwargs):
    request = CaseRequest.model_validate_json((ROOT / "fixtures" / "cases" / f"{case_id}.json").read_text())
    return workflow.start(store, request, **kwargs)


def test_summary_of_fin_003(store):
    text = output.format_run(start(store, "FIN-003"))

    assert text.startswith("RUN-001  FIN-003  invoice INV-3003  vendor V-300  AUD 12,650.00")
    assert "Outcome:      HOLD_FOR_INFORMATION" in text
    assert "Approver:     AP_MANAGER (alice)" in text
    assert "✗ bank details" in text and "(FIN-POL-001 v3.2 §5)" in text
    assert "[1] FIN-POL-001 Accounts Payable Core Policy, v3.2, §5 Required checks" in text
    assert text.endswith("Next: ap_assistant approve RUN-001 --approver alice")
    assert "calculations" not in text and "#" not in text


def test_summary_of_failed_grounding(store):
    text = output.format_run(start(store, "FIN-001", model=BrokenModel()))

    assert "State:        GROUNDING_FAILED" in text
    assert "Grounding errors\n  - the answer is not valid JSON\n  - the answer is not valid JSON" in text
    assert text.endswith("Next: ap_assistant resume RUN-001")


def test_table_quote_keeps_its_lines(store):
    text = output.format_run(start(store, "FIN-001"))

    assert "      > | Cost Centre Manager | AUD 10,000 |" in text


def test_decision_of_an_approval_and_a_rejection(store):
    start(store, "FIN-001")
    start(store, "FIN-002")

    approved = workflow.approve(store, "RUN-001", "colin", "cb-1")
    rejected = workflow.reject(store, "RUN-002", "alice", "cb-2")

    assert output.format_decision(approved, workflow.get_run(store, "RUN-001")) == (
        "RUN-001  SUBMITTED\n"
        "Decision APPROVE_FOR_POSTING submitted, approved by colin (COST_CENTRE_MANAGER)\n"
        "Idempotency key: RUN-001:APPROVE_FOR_POSTING"
    )
    assert output.format_decision(rejected, workflow.get_run(store, "RUN-002")) == (
        "RUN-002  REJECTED_BY_APPROVER\nRejected by alice (AP_MANAGER). Nothing submitted."
    )


def test_events_leave_out_empty_fields(store):
    start(store, "FIN-001")

    text = output.format_run(workflow.get_run(store, "RUN-001", with_events=True), with_events=True)

    assert "tool=check_invoice_history" in text
    assert "error=None" not in text
