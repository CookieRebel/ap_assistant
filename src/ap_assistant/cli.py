"""The `ap_assistant` command line. The database is data/ap.db, or the path in the AP_DB environment variable."""

import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import typer
from pydantic import ValidationError

from ap_assistant import tools, workflow
from ap_assistant.schemas import CaseRequest
from ap_assistant.store import Store
from ap_assistant.workflow import WorkflowError

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _store() -> Store:
    return Store(os.environ.get("AP_DB", "data/ap.db"))


def _print(obj: dict) -> None:
    typer.echo(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def _fail(message: str) -> None:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(1)


@app.command()
def start(case_file: Path) -> None:
    """Start a run from a case JSON file and process it until it waits for approval."""
    try:
        request = CaseRequest.model_validate_json(case_file.read_text())
    except (OSError, ValidationError) as exc:
        _fail(str(exc))
    _print(workflow.start(_store(), request))


@app.command()
def get(run_id: str, events: bool = typer.Option(False, "--events", help="Include the audit events.")) -> None:
    """Print a run, its recommendation and its decisions."""
    try:
        _print(workflow.get_run(_store(), run_id, with_events=events))
    except WorkflowError as exc:
        _fail(str(exc))


APPROVER_HELP = "Approver ID from fixtures/approvers.json, e.g. colin. The role comes from that register."
CALLBACK_HELP = "ID of this approval message. Repeat an ID to simulate a duplicate delivery. Default: a new ID."


def _new_callback_id() -> str:
    return f"cb-{uuid4().hex[:12]}"


@app.command()
def approve(
    run_id: str,
    approver: str = typer.Option(..., "--approver", help=APPROVER_HELP),
    callback_id: str = typer.Option(None, "--callback-id", help=CALLBACK_HELP),
) -> None:
    """Approve the recommendation and submit the decision once."""
    try:
        _print(workflow.approve(_store(), run_id, approver, callback_id or _new_callback_id()))
    except WorkflowError as exc:
        _fail(str(exc))


@app.command()
def reject(
    run_id: str,
    approver: str = typer.Option(..., "--approver", help=APPROVER_HELP),
    callback_id: str = typer.Option(None, "--callback-id", help=CALLBACK_HELP),
) -> None:
    """Reject the recommendation. Nothing is submitted."""
    try:
        _print(workflow.reject(_store(), run_id, approver, callback_id or _new_callback_id()))
    except WorkflowError as exc:
        _fail(str(exc))


# Expected results per case: the outcome, an exception category that must be present, and extra checks.
EXPECTED = {
    "FIN-001": {"outcome": "APPROVE_FOR_POSTING"},
    "FIN-002": {"outcome": "REJECT_DUPLICATE", "exception": "DUPLICATE_RISK"},
    "FIN-003": {"outcome": "HOLD_FOR_INFORMATION", "exception": "BANK_CHANGE", "refuse_approver": "colin"},
    "FIN-004": {"outcome": "HOLD_FOR_INFORMATION", "exception": "MISSING_PO", "po_attempts": 3},
    "FIN-005": {"outcome": "APPROVE_FOR_POSTING", "callback_twice": True},
}


@app.command("eval")
def evaluate() -> None:
    """Run FIN-001 to FIN-005 in a temporary database and print PASS or FAIL per check."""
    results: list[bool] = []
    approvers_by_role = {a["role"]: a["approver_id"] for a in json.loads((tools.FIXTURES / "approvers.json").read_text())}

    def check(case_id: str, name: str, passed: bool) -> None:
        results.append(passed)
        typer.echo(f"{'PASS' if passed else 'FAIL'}  {case_id}  {name}")

    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "ap.db")
        for case_id, expected in EXPECTED.items():
            request = CaseRequest.model_validate_json((tools.FIXTURES / "cases" / f"{case_id}.json").read_text())
            run = workflow.start(store, request)
            run_id = run["run_id"]
            rec = run["recommendation"]
            check(case_id, f"outcome is {expected['outcome']}", rec["outcome"] == expected["outcome"])
            if "exception" in expected:
                check(case_id, f"exception {expected['exception']}", expected["exception"] in rec["exceptions"])

            if "po_attempts" in expected:
                events = workflow.get_run(store, run_id, with_events=True)["events"]
                attempts = [e for e in events if e["type"] == "tool_attempt" and e["tool"] == "get_purchase_order"]
                check(case_id, f"{expected['po_attempts']} PO attempts", len(attempts) == expected["po_attempts"])

            if "refuse_approver" in expected:
                try:
                    workflow.approve(store, run_id, expected["refuse_approver"], f"cb-{case_id}-wrong-role")
                    refused = False
                except WorkflowError:
                    refused = True
                check(case_id, f"approval by {expected['refuse_approver']} refused", refused)

            approver_id = approvers_by_role[rec["required_role"]]
            callback_id = "cb-5" if expected.get("callback_twice") else f"cb-{case_id}"
            first = workflow.approve(store, run_id, approver_id, callback_id)
            if expected.get("callback_twice"):
                second = workflow.approve(store, run_id, approver_id, callback_id)
                check(case_id, "repeated callback returns identical response", first == second)

            final = workflow.get_run(store, run_id)
            check(case_id, "submitted after approval", final["state"] == "SUBMITTED")
            check(case_id, "exactly one decision", len(final["decisions"]) == 1)

    passed = sum(results)
    typer.echo(f"\n{passed}/{len(results)} checks passed")
    raise typer.Exit(0 if all(results) else 1)
