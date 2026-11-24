from decimal import Decimal

from ap_assistant import tools
from ap_assistant.reconcile import allowed_roles, recommend, reconcile, required_role_for
from ap_assistant.schemas import Outcome


def run_case(invoice_ref, vendor_id, po_available=True):
    history = tools.check_invoice_history(invoice_ref)
    vendor = tools.get_vendor_record(vendor_id)
    po = tools.get_purchase_order(history.invoice.po_number) if po_available else None
    return recommend(history, *reconcile(history, vendor, po))


def test_fin_001_price_variance_is_within_tolerance():
    rec = run_case("INV-1001", "V-100")

    calcs = {c.name: c.result for c in rec.calculations}
    assert calcs["price variance line 1"] == "8.00"
    assert calcs["price tolerance line 1"] == "18.00"
    price = next(f for f in rec.findings if f.check == "price line 1")
    assert price.passed
    assert rec.outcome == Outcome.APPROVE_FOR_POSTING


def test_fin_001_needs_cost_centre_manager():
    rec = run_case("INV-1001", "V-100")

    assert rec.amount == Decimal("3473.80")
    assert rec.required_role == "COST_CENTRE_MANAGER"


def test_fin_002_is_a_duplicate():
    rec = run_case("INV-2002", "V-200")

    assert rec.outcome == Outcome.REJECT_DUPLICATE
    duplicate = next(f for f in rec.findings if f.check == "duplicate")
    assert duplicate.evidence == ["HIST-0091"]
    assert rec.required_role == "AP_MANAGER"


def test_fin_003_bank_mismatch_holds():
    rec = run_case("INV-3003", "V-300")

    assert rec.outcome == Outcome.HOLD_FOR_INFORMATION
    assert rec.exceptions == ["BANK_CHANGE"]


def test_fin_004_missing_po_holds():
    rec = run_case("INV-4004", "V-400", po_available=False)

    assert rec.outcome == Outcome.HOLD_FOR_INFORMATION
    assert rec.exceptions == ["MISSING_PO"]
    assert rec.unknowns


def test_required_role_by_amount():
    assert required_role_for(Decimal("10000")) == "COST_CENTRE_MANAGER"
    assert required_role_for(Decimal("10000.01")) == "DEPARTMENT_DIRECTOR"
    assert required_role_for(Decimal("2000000")) == "CEO"


def test_higher_role_may_approve_a_posting_but_only_ap_manager_a_hold():
    assert "CFO" in allowed_roles(Outcome.APPROVE_FOR_POSTING, "COST_CENTRE_MANAGER")
    assert "COST_CENTRE_MANAGER" not in allowed_roles(Outcome.APPROVE_FOR_POSTING, "DEPARTMENT_DIRECTOR")
    assert allowed_roles(Outcome.HOLD_FOR_INFORMATION, "AP_MANAGER") == {"AP_MANAGER"}
