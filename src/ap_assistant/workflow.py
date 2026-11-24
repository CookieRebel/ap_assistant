"""The fixed run sequence: start (look up, reconcile, recommend, wait), then approve or reject."""

import json

from ap_assistant import tools
from ap_assistant.reconcile import allowed_roles, recommend, reconcile
from ap_assistant.schemas import CaseRequest, Outcome, Recommendation, RunState
from ap_assistant.store import Store


class WorkflowError(Exception):
    """An operation the workflow refuses, such as an approval with the wrong role."""


def start(store: Store, request: CaseRequest) -> dict:
    """Creates a run, looks up the evidence, reconciles it, and saves the recommendation as AWAITING_APPROVAL."""
    run_id = store.create_run(request.case_id, RunState.RECEIVED, request.model_dump_json())
    store.add_event(run_id, "run_started", {"case_id": request.case_id})

    def emit(event: dict) -> None:
        store.add_event(run_id, event.pop("type"), event)

    history = tools.call_tool(tools.check_invoice_history, request.invoice_ref, emit)
    if history is None:
        store.update_run(run_id, RunState.FAILED, error="invoice history unavailable")
        store.add_event(run_id, "run_failed", {"error": "invoice history unavailable"})
        return get_run(store, run_id)

    vendor = tools.call_tool(tools.get_vendor_record, request.vendor_id, emit)
    po_number = history.invoice.po_number
    po = tools.call_tool(tools.get_purchase_order, po_number, emit) if po_number else None

    recommendation = recommend(history, *reconcile(history, vendor, po))
    store.update_run(run_id, RunState.AWAITING_APPROVAL, recommendation_json=recommendation.model_dump_json())
    store.add_event(
        run_id,
        "recommended",
        {"outcome": recommendation.outcome, "exceptions": recommendation.exceptions, "required_role": recommendation.required_role},
    )
    return get_run(store, run_id)


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
        "approvals": store.list_approvals(run_id),
        "decisions": store.list_decisions(run_id),
        "created_at": run["created_at"],
        "updated_at": run["updated_at"],
    }
    if with_events:
        result["events"] = store.list_events(run_id)
    return result
