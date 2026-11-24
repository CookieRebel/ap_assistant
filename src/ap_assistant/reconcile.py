"""The reconciliation checks and the recommendation.

The rules are taken by hand from the current policies in corpus/. Each finding cites its document, version and section.
All arithmetic uses Decimal. Case text (notes and attachments) is never read here, so it cannot change a check.
"""

from decimal import ROUND_HALF_UP, Decimal

from ap_assistant.schemas import (
    Calculation,
    Finding,
    InvoiceHistory,
    Outcome,
    PurchaseOrder,
    Recommendation,
    VendorRecord,
)

POLICY = {
    "duplicate": "FIN-POL-005 v2.8 §2",
    "vendor": "FIN-POL-004 v5.1 §4",
    "bank": "FIN-POL-001 v3.2 §5",
    "po": "FIN-POL-002 v2.4 §1",
    "receipt": "FIN-POL-002 v2.4 §4",
    "tolerance": "FIN-POL-002 v2.4 §2",
}

# (absolute limit, percentage of the PO line value); the lower of the two applies. FIN-POL-002 §2.
TOLERANCE = {
    "goods": (Decimal("50"), Decimal("0.01")),
    "services": (Decimal("100"), Decimal("0.02")),
}

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

CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _hold(check: str, category: str, policy_key: str, detail: str, evidence: list[str]) -> Finding:
    return Finding(
        check=check,
        passed=False,
        outcome=Outcome.HOLD_FOR_INFORMATION,
        category=category,
        policy=POLICY[policy_key],
        detail=detail,
        evidence=evidence,
    )


def _passed(check: str, policy_key: str, detail: str, evidence: list[str]) -> Finding:
    return Finding(check=check, passed=True, policy=POLICY[policy_key], detail=detail, evidence=evidence)


def _check_duplicate(history: InvoiceHistory) -> Finding:
    settled = [m for m in history.matches if m.status in ("PAID", "POSTED")]
    if settled:
        return Finding(
            check="duplicate",
            passed=False,
            outcome=Outcome.REJECT_DUPLICATE,
            category="DUPLICATE_RISK",
            policy=POLICY["duplicate"],
            detail=f"exact match to a {settled[0].status} record",
            evidence=[m.history_id for m in settled],
        )
    return _passed("duplicate", "duplicate", "no paid or posted record matches", [history.invoice.invoice_ref])


def _check_vendor(vendor: VendorRecord | None, vendor_id: str) -> list[Finding]:
    if vendor is None:
        return [
            _hold("vendor status", "VENDOR_BLOCK", "vendor", "vendor record unavailable", [vendor_id]),
            _hold("bank details", "BANK_CHANGE", "bank", "vendor record unavailable", [vendor_id]),
        ]
    return [_check_vendor_status(vendor)]


def _check_vendor_status(vendor: VendorRecord) -> Finding:
    if vendor.status != "ACTIVE":
        return _hold("vendor status", "VENDOR_BLOCK", "vendor", f"vendor status is {vendor.status}", [vendor.vendor_id])
    return _passed("vendor status", "vendor", "vendor is ACTIVE", [vendor.vendor_id])


def _check_bank(history: InvoiceHistory, vendor: VendorRecord) -> Finding:
    invoice_last4 = history.invoice.remit_to_last4
    evidence = [history.invoice.invoice_ref, vendor.vendor_id]
    if invoice_last4 != vendor.bank_last4:
        return _hold(
            "bank details",
            "BANK_CHANGE",
            "bank",
            f"invoice remit-to account ends {invoice_last4}, vendor master ends {vendor.bank_last4}",
            evidence,
        )
    return _passed("bank details", "bank", f"remit-to account ends {invoice_last4}, as in vendor master", evidence)


def _check_lines(history: InvoiceHistory, po: PurchaseOrder) -> tuple[list[Finding], list[Calculation]]:
    findings: list[Finding] = []
    calculations: list[Calculation] = []
    po_lines = {line.line_no: line for line in po.lines}
    absolute, percent = TOLERANCE[po.category]

    for line in history.invoice.lines:
        n = line.line_no
        receipts = [r for r in po.receipts if r.line_no == n]
        if not receipts:
            findings.append(_hold(f"receipt line {n}", "MISSING_RECEIPT", "receipt", "no receipt recorded", [po.po_number]))
        else:
            received = sum((r.quantity_received for r in receipts), Decimal("0"))
            receipt_ids = sorted({r.receipt_id for r in receipts})
            findings.append(_passed(f"receipt line {n}", "receipt", f"received {received}", receipt_ids))
            if line.quantity > received:
                findings.append(
                    _hold(
                        f"quantity line {n}",
                        "QUANTITY_VARIANCE",
                        "tolerance",
                        f"invoiced {line.quantity} > received {received}",
                        receipt_ids,
                    )
                )
            else:
                findings.append(
                    _passed(f"quantity line {n}", "tolerance", f"invoiced {line.quantity} <= received {received}", receipt_ids)
                )

        po_line = po_lines.get(n)
        if po_line is None:
            findings.append(_hold(f"price line {n}", "PRICE_VARIANCE", "tolerance", "line is not on the PO", [po.po_number]))
            continue
        variance = _money(abs(line.quantity * (line.unit_price - po_line.unit_price)))
        po_line_value = po_line.quantity * po_line.unit_price
        limit = _money(min(absolute, po_line_value * percent))
        calculations.append(
            Calculation(
                name=f"price variance line {n}",
                inputs={
                    "invoice_quantity": str(line.quantity),
                    "invoice_unit_price": str(line.unit_price),
                    "po_unit_price": str(po_line.unit_price),
                },
                formula="|invoice_quantity × (invoice_unit_price − po_unit_price)|",
                result=str(variance),
            )
        )
        calculations.append(
            Calculation(
                name=f"price tolerance line {n}",
                inputs={
                    "po_quantity": str(po_line.quantity),
                    "po_unit_price": str(po_line.unit_price),
                    "absolute_limit": str(absolute),
                    "percent_limit": str(percent),
                    "category": po.category,
                },
                formula="min(absolute_limit, po_quantity × po_unit_price × percent_limit)",
                result=str(limit),
            )
        )
        detail = f"variance {variance}, limit {limit}"
        if variance > limit:
            findings.append(_hold(f"price line {n}", "PRICE_VARIANCE", "tolerance", detail, [po.po_number]))
        else:
            findings.append(_passed(f"price line {n}", "tolerance", detail, [po.po_number]))
    return findings, calculations


def reconcile(
    history: InvoiceHistory, vendor: VendorRecord | None, po: PurchaseOrder | None
) -> tuple[list[Finding], list[Calculation], list[str]]:
    """Runs every check. Returns the findings (passed and failed), the calculations and the unknowns."""
    findings = [_check_duplicate(history)]
    calculations: list[Calculation] = []
    unknowns: list[str] = []
    invoice = history.invoice

    findings += _check_vendor(vendor, invoice.vendor_id)
    if vendor is None:
        unknowns.append("vendor status and bank details: vendor record unavailable")
    else:
        findings.append(_check_bank(history, vendor))

    if po is None:
        reason = "invoice has no PO number" if invoice.po_number is None else f"{invoice.po_number} unavailable"
        findings.append(_hold("purchase order", "MISSING_PO", "po", reason, [invoice.po_number or invoice.invoice_ref]))
        unknowns.append(f"PO lines and receipts: {reason}")
    else:
        findings.append(_passed("purchase order", "po", f"{po.po_number} retrieved", [po.po_number]))
        line_findings, calculations = _check_lines(history, po)
        findings += line_findings

    return findings, calculations, unknowns


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


NEXT_ACTION = {
    Outcome.APPROVE_FOR_POSTING: "Approve to post the invoice for payment.",
    Outcome.HOLD_FOR_INFORMATION: "Approve to place the invoice on hold and request the missing information.",
    Outcome.REJECT_DUPLICATE: "Approve to reject the invoice as a duplicate.",
}


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
