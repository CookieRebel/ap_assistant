"""The fixed run sequence, saved after each step so that a stopped run can resume:

RECEIVED → lookups → EVIDENCE_COLLECTED → reconcile + recommend → RECOMMENDED → grounding → AWAITING_APPROVAL
                                                                                         ↘ GROUNDING_FAILED
Then approve or reject.
"""

import json

from ap_assistant import tools
from ap_assistant.grounding import GroundingFailed, ground
from ap_assistant.llm import ModelClient, model_from_env
from ap_assistant.recommendation import allowed_roles, recommend
from ap_assistant.reconciliation import reconcile
from ap_assistant.schemas import CaseRequest, Evidence, Outcome, Recommendation, RunState
from ap_assistant.store import Store

RESUMABLE = {RunState.RECEIVED, RunState.EVIDENCE_COLLECTED, RunState.RECOMMENDED, RunState.GROUNDING_FAILED}


class WorkflowError(Exception):
    """An operation the workflow refuses, such as an approval with the wrong role."""


class SimulatedCrash(Exception):
    """Raised right after a chosen state is saved, to test resume. The CLI sets it from AP_CRASH_AFTER."""

    def __init__(self, run_id: str, state: RunState):
        super().__init__(f"simulated crash of {run_id} after {state.value}")
        self.run_id = run_id


def start(store: Store, request: CaseRequest, model: ModelClient | None = None, crash_after: str | None = None) -> dict:
    """Creates a run and processes it until AWAITING_APPROVAL, GROUNDING_FAILED or FAILED."""
    if not store.has_chunks():
        raise WorkflowError("no policy chunks stored: run `ap_assistant ingest` first")
    run_id = store.create_run(request.case_id, RunState.RECEIVED, request.model_dump_json())
    store.add_event(run_id, "run_started", {"case_id": request.case_id})
    return _advance(store, run_id, model or model_from_env(), crash_after)


def resume(store: Store, run_id: str, model: ModelClient | None = None, crash_after: str | None = None) -> dict:
    """Continues a stopped run from its last saved step. Finished steps, and their tool calls, are not repeated."""
    run = store.get_run(run_id)
    if run is None:
        raise WorkflowError(f"run {run_id} not found")
    if run["state"] not in RESUMABLE:
        raise WorkflowError(f"run {run_id} is {run['state']}; only a run that stopped before AWAITING_APPROVAL can resume")
    store.add_event(run_id, "run_resumed", {"from_state": run["state"]})
    return _advance(store, run_id, model or model_from_env(), crash_after)


def _advance(store: Store, run_id: str, model: ModelClient, crash_after: str | None) -> dict:
    def emit(event: dict) -> None:
        store.add_event(run_id, event.pop("type"), event)

    def saved(state: RunState) -> None:
        if crash_after == state.value:
            raise SimulatedCrash(run_id, state)

    run = store.get_run(run_id)
    state = RunState(run["state"])

    if state == RunState.RECEIVED:
        request = CaseRequest.model_validate_json(run["request_json"])
        evidence = _collect_evidence(request, emit)
        if evidence.history is None:
            store.update_run(run_id, RunState.FAILED, error="invoice history unavailable")
            store.add_event(run_id, "run_failed", {"error": "invoice history unavailable"})
            return get_run(store, run_id)
        store.update_run(run_id, RunState.EVIDENCE_COLLECTED, evidence_json=evidence.model_dump_json())
        saved(RunState.EVIDENCE_COLLECTED)
        state = RunState.EVIDENCE_COLLECTED

    if state == RunState.EVIDENCE_COLLECTED:
        evidence = Evidence.model_validate_json(store.get_run(run_id)["evidence_json"])
        recommendation = recommend(evidence.history, *reconcile(evidence.history, evidence.vendor, evidence.po))
        store.update_run(run_id, RunState.RECOMMENDED, recommendation_json=recommendation.model_dump_json())
        store.add_event(
            run_id,
            "recommended",
            {"outcome": recommendation.outcome, "exceptions": recommendation.exceptions, "required_role": recommendation.required_role},
        )
        saved(RunState.RECOMMENDED)
        state = RunState.RECOMMENDED

    if state in (RunState.RECOMMENDED, RunState.GROUNDING_FAILED):
        recommendation = Recommendation.model_validate_json(store.get_run(run_id)["recommendation_json"])
        try:
            grounding = ground(store, recommendation, model, emit)
        except GroundingFailed as exc:
            store.update_run(run_id, RunState.GROUNDING_FAILED, error="; ".join(exc.errors))
            store.add_event(run_id, "grounding_failed", {"model": model.name, "errors": exc.errors})
            return get_run(store, run_id)
        store.update_run(run_id, RunState.AWAITING_APPROVAL, grounding_json=grounding.model_dump_json())
        store.add_event(run_id, "grounded", {"model": model.name, "citations": [c.chunk_id for c in grounding.citations]})
        saved(RunState.AWAITING_APPROVAL)

    return get_run(store, run_id)


def _collect_evidence(request: CaseRequest, emit) -> Evidence:
    history = tools.call_tool(tools.check_invoice_history, request.invoice_ref, emit)
    if history is None:
        return Evidence(history=None, vendor=None, po=None)
    vendor = tools.call_tool(tools.get_vendor_record, request.vendor_id, emit)
    po_number = history.invoice.po_number
    po = tools.call_tool(tools.get_purchase_order, po_number, emit) if po_number else None
    return Evidence(history=history, vendor=vendor, po=po)


def submit_finance_decision(store: Store, run_id: str, outcome: Outcome, idempotency_key: str, callback_id: str) -> dict:
    """Simulated posting/hold/rejection API. Deny by default: it refuses a decision that has no recorded approval."""
    approval = store.get_approval(callback_id)
    if approval is None or approval["run_id"] != run_id or approval["decision"] != "APPROVED":
        raise WorkflowError(f"no approval recorded for run {run_id}")
    return store.insert_decision(idempotency_key, run_id, outcome, callback_id)


def approve(store: Store, run_id: str, approver_id: str, callback_id: str) -> dict:
    """Records the approval and submits the decision once. A known callback ID returns the stored response."""
    return _resolve(store, run_id, approver_id, callback_id, "APPROVED")


def reject(store: Store, run_id: str, approver_id: str, callback_id: str) -> dict:
    """Records the rejection. Nothing is submitted. A known callback ID returns the stored response."""
    return _resolve(store, run_id, approver_id, callback_id, "REJECTED")


def _resolve(store: Store, run_id: str, approver_id: str, callback_id: str, decision: str) -> dict:
    """The role comes from the authority register (tools.get_approver), never from the caller."""
    role = None
    try:
        with store.transaction():
            stored = store.get_approval(callback_id)
            if stored is not None:
                return json.loads(stored["response_json"])

            recommendation = _awaiting_recommendation(store, run_id)
            approver = tools.get_approver(approver_id)
            if approver is None:
                raise WorkflowError(f"approver {approver_id} is not in the authority register")
            role = approver.role
            if role not in allowed_roles(recommendation.outcome, recommendation.required_role):
                raise WorkflowError(
                    f"{approver_id} has role {role}, which may not decide {recommendation.outcome.value};"
                    f" required: {recommendation.required_role}"
                )

            store.insert_approval(callback_id, run_id, approver_id, role, decision)
            response: dict = {"run_id": run_id, "callback_id": callback_id, "decision": decision}
            if decision == "APPROVED":
                key = f"{run_id}:{recommendation.outcome.value}"
                submitted = submit_finance_decision(store, run_id, recommendation.outcome, key, callback_id)
                store.update_run(run_id, RunState.SUBMITTED)
                response |= {"state": RunState.SUBMITTED.value, "submitted": submitted}
            else:
                store.update_run(run_id, RunState.REJECTED_BY_APPROVER)
                response |= {"state": RunState.REJECTED_BY_APPROVER.value, "submitted": None}

            store.set_approval_response(callback_id, response)
            store.add_event(run_id, "approval_recorded", {"callback_id": callback_id, "approver_id": approver_id, "role": role, "decision": decision})
            return response
    except WorkflowError as exc:
        if store.get_run(run_id) is not None:
            store.add_event(
                run_id,
                "approval_refused",
                {"callback_id": callback_id, "approver_id": approver_id, "role": role, "error": str(exc)},
            )
        raise


def _awaiting_recommendation(store: Store, run_id: str) -> Recommendation:
    run = store.get_run(run_id)
    if run is None:
        raise WorkflowError(f"run {run_id} not found")
    if run["state"] != RunState.AWAITING_APPROVAL:
        raise WorkflowError(f"run {run_id} is {run['state']}, not AWAITING_APPROVAL")
    return Recommendation.model_validate_json(run["recommendation_json"])


def get_run(store: Store, run_id: str, with_events: bool = False) -> dict:
    run = store.get_run(run_id)
    if run is None:
        raise WorkflowError(f"run {run_id} not found")
    result = {
        "run_id": run["run_id"],
        "case_id": run["case_id"],
        "state": run["state"],
        "error": run["error"],
        "recommendation": json.loads(run["recommendation_json"]) if run["recommendation_json"] else None,
        "grounding": json.loads(run["grounding_json"]) if run["grounding_json"] else None,
        "approvals": store.list_approvals(run_id),
        "decisions": store.list_decisions(run_id),
        "created_at": run["created_at"],
        "updated_at": run["updated_at"],
    }
    if with_events:
        result["events"] = store.list_events(run_id)
    return result
