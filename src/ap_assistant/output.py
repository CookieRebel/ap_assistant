"""Human-readable text for the CLI: the run summary, the decision of an approval or rejection, and the event list.

Each function takes the JSON dict that workflow returns, so --json and the summary show the same data.
"""

import textwrap
from decimal import Decimal

from ap_assistant import tools

WIDTH = 100
QUOTE_LENGTH = 110
QUOTE_LINES = 4
RESUMABLE_STATES = {"RECEIVED", "EVIDENCE_COLLECTED", "RECOMMENDED", "GROUNDING_FAILED"}


def _money(amount: str) -> str:
    return f"{Decimal(amount):,.2f}"


def _indented(text: str) -> str:
    return textwrap.fill(text, WIDTH, initial_indent="  ", subsequent_indent="  ")


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= QUOTE_LENGTH else text[: QUOTE_LENGTH - 1] + "…"


def _quote_lines(quote: str) -> list[str]:
    """A quote keeps its line breaks (a table stays a table), shown with at most QUOTE_LINES lines."""
    lines = [_short(line) for line in quote.strip().splitlines() if line.strip()]
    if len(lines) > QUOTE_LINES:
        lines = lines[:QUOTE_LINES] + ["…"]
    return [f"      > {line}" for line in lines]


def _approver_for(role: str) -> str:
    """The first user in the register who holds the role, for the 'Next:' line."""
    return next((a.approver_id for a in tools.list_approvers() if a.role == role), "<approver>")


def format_run(run: dict, with_events: bool = False) -> str:
    request, rec, grounding = run["request"], run["recommendation"], run["grounding"]
    amount, currency = (rec["amount"], rec["currency"]) if rec else (request["amount"], request["currency"])
    lines = [
        f"{run['run_id']}  {run['case_id']}  invoice {request['invoice_ref']}  vendor {request['vendor_id']}  {currency} {_money(amount)}",
        f"State:        {run['state']}",
    ]

    if rec:
        failed = [f for f in rec["findings"] if not f["passed"]]
        lines += [
            "",
            f"Outcome:      {rec['outcome']}",
            f"Exceptions:   {', '.join(rec['exceptions']) or 'none'}",
            f"Approver:     {rec['required_role']} ({_approver_for(rec['required_role'])})",
        ]
        if failed:
            lines += ["", "Failed checks"]
            lines += [f"  ✗ {f['check']}  {f['detail']}  ({f['policy']})" for f in failed]
        lines.append(f"Passed checks: {len(rec['findings']) - len(failed)}")
        if rec["unknowns"]:
            lines += ["", "Unknowns"] + [f"  ? {u}" for u in rec["unknowns"]]

    if grounding:
        lines += ["", f"Explanation (model: {grounding['model']})", _indented(grounding["explanation"]), "", "Citations"]
        for i, c in enumerate(grounding["citations"], 1):
            lines.append(f"  [{i}] {c['document_id']} {c['title']}, v{c['version']}, §{c['section']} {c['heading']}".rstrip())
            lines += _quote_lines(c["quote"])
            lines.append(f"      supports: {c['finding']}")

    if run["error"]:
        label = "Grounding errors" if run["state"] == "GROUNDING_FAILED" else "Error"
        lines += ["", label] + [f"  - {e}" for e in run["error"].split("; ")]

    for a in run["approvals"]:
        verb = "Approved" if a["decision"] == "APPROVED" else "Rejected"
        lines += ["", f"{verb} by {a['approver_id']} ({a['role']}) at {a['created_at'][:19].replace('T', ' ')} UTC"]
    for d in run["decisions"]:
        lines.append(f"Submitted {d['outcome']}, idempotency key {d['idempotency_key']}")

    if run["state"] == "AWAITING_APPROVAL" and rec:
        lines += ["", f"Next: ap_assistant approve {run['run_id']} --approver {_approver_for(rec['required_role'])}"]
    elif run["state"] in RESUMABLE_STATES:
        lines += ["", f"Next: ap_assistant resume {run['run_id']}"]

    if with_events:
        lines += ["", "Events"] + [f"  {_event_line(e)}" for e in run["events"]]
    return "\n".join(lines)


def format_decision(response: dict, run: dict) -> str:
    """The result of approve or reject. The approver comes from the run's approval with the same callback ID."""
    approval = next(a for a in run["approvals"] if a["callback_id"] == response["callback_id"])
    who = f"{approval['approver_id']} ({approval['role']})"
    if response["decision"] == "REJECTED":
        return f"{response['run_id']}  {response['state']}\nRejected by {who}. Nothing submitted."
    submitted = response["submitted"]
    return "\n".join(
        [
            f"{response['run_id']}  {response['state']}",
            f"Decision {submitted['outcome']} submitted, approved by {who}",
            f"Idempotency key: {submitted['idempotency_key']}",
        ]
    )


def _event_line(event: dict) -> str:
    """One line per event: the time, the type, then the remaining fields as key=value, lists shown by length."""
    details = []
    for key, value in event.items():
        if key in ("ts", "type") or value is None:
            continue
        if isinstance(value, (list, dict)):
            value = f"[{len(value)}]"
        details.append(f"{key}={value}")
    return f"{event['ts'][11:19]}  {event['type']:<20} {_short(' '.join(details))}"
