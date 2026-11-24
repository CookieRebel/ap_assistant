"""The recommendation and the approval authority.

recommend() turns the findings of reconcile() into one outcome and the role that must approve it.
required_role_for() and allowed_roles() apply the authority limits of FIN-POL-003 §2, at recommendation time
and again when an approver decides.
"""

from decimal import Decimal

from ap_assistant.schemas import Calculation, Finding, InvoiceHistory, Outcome, Recommendation

# Roles in ascending order of authority, with their maximum approval in AUD. FIN-POL-003 §2. None = no upper limit.
ROLE_LIMITS: list[tuple[str, Decimal | None]] = [
    ("COST_CENTRE_MANAGER", Decimal("10000")),
    ("DEPARTMENT_DIRECTOR", Decimal("50000")),
    ("EXECUTIVE_DIRECTOR", Decimal("250000")),
    ("CFO", Decimal("1000000")),
    ("CEO", None),
]
# Approves an outcome that does not post. The corpus names no approver for a hold or a rejection: an assumption.
NON_POSTING_APPROVER = "AP_MANAGER"

SEVERITY = [Outcome.APPROVE_FOR_POSTING, Outcome.HOLD_FOR_INFORMATION, Outcome.REJECT_DUPLICATE]

NEXT_ACTION = {
    Outcome.APPROVE_FOR_POSTING: "Approve to post the invoice for payment.",
    Outcome.HOLD_FOR_INFORMATION: "Approve to place the invoice on hold and request the missing information.",
    Outcome.REJECT_DUPLICATE: "Approve to reject the invoice as a duplicate.",
}


def required_role_for(amount: Decimal) -> str:
    """The lowest role whose limit covers the amount. FIN-POL-003 §2."""
    for role, limit in ROLE_LIMITS:
        if limit is None or amount <= limit:
            return role
    raise AssertionError("ROLE_LIMITS ends with an unlimited role")


def allowed_roles(outcome: Outcome, required_role: str) -> set[str]:
    """The roles that may approve: the required role or a higher one for a posting, else only AP_MANAGER."""
    if outcome != Outcome.APPROVE_FOR_POSTING:
        return {NON_POSTING_APPROVER}
    names = [role for role, _ in ROLE_LIMITS]
    return set(names[names.index(required_role) :])


def recommend(history: InvoiceHistory, findings: list[Finding], calculations: list[Calculation], unknowns: list[str]) -> Recommendation:
    """Picks the most severe failed outcome and the role that must approve it."""
    failed = [f for f in findings if not f.passed]
    outcome = max((f.outcome for f in failed), key=SEVERITY.index, default=Outcome.APPROVE_FOR_POSTING)
    amount = history.invoice.gross
    required_role = required_role_for(amount) if outcome == Outcome.APPROVE_FOR_POSTING else NON_POSTING_APPROVER
    exceptions = list(dict.fromkeys(f.category for f in failed))
    return Recommendation(
        outcome=outcome,
        exceptions=exceptions,
        required_role=required_role,
        amount=amount,
        currency=history.invoice.currency,
        findings=findings,
        calculations=calculations,
        unknowns=unknowns,
        next_action=NEXT_ACTION[outcome],
    )
