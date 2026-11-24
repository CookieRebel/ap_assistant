"""The three simulated read-only tools over fixtures/, the approver lookup, and call_tool(), which adds the timeout and retry.

All tools are simulated: they read JSON files. fixtures/faults.json makes a call hang, to test the timeout.
"""

import json
import os
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

from pydantic import BaseModel
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt

from ap_assistant.schemas import Approver, HistoryRecord, Invoice, InvoiceHistory, PurchaseOrder, VendorRecord

FIXTURES = Path(os.environ.get("AP_FIXTURES", Path(__file__).parents[2] / "fixtures"))
TIMEOUT_SECONDS = 1.0
MAX_ATTEMPTS = 3
HANG_SECONDS = 1.5


class ToolTimeout(Exception):
    pass


class TransientToolError(Exception):
    pass


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


def _apply_fault(tool: str, key: str) -> None:
    fault = _load("faults.json").get(tool, {}).get(key)
    if fault == "hang":
        time.sleep(HANG_SECONDS)


def _normalise_invoice_number(number: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", number.upper())


def check_invoice_history(invoice_ref: str) -> InvoiceHistory:
    """Returns the invoice and every prior record with the same vendor, normalised invoice number, currency and amount."""
    _apply_fault("check_invoice_history", invoice_ref)
    data = _load("invoices.json")
    invoice = Invoice.model_validate(next(i for i in data["invoices"] if i["invoice_ref"] == invoice_ref))
    records = [HistoryRecord.model_validate(h) for h in data["history"]]
    matches = [
        r
        for r in records
        if r.vendor_id == invoice.vendor_id
        and _normalise_invoice_number(r.invoice_number) == _normalise_invoice_number(invoice.invoice_number)
        and r.currency == invoice.currency
        and r.amount == invoice.gross
    ]
    return InvoiceHistory(invoice=invoice, matches=matches)


def get_vendor_record(vendor_id: str) -> VendorRecord:
    """Returns the vendor master record. The bank account is reduced to its last 4 digits here, so no caller sees it."""
    _apply_fault("get_vendor_record", vendor_id)
    raw = next(v for v in _load("vendors.json") if v["vendor_id"] == vendor_id)
    return VendorRecord(
        vendor_id=raw["vendor_id"],
        name=raw["name"],
        status=raw["status"],
        bank_last4=raw["bank_account"][-4:],
        risk_flags=raw["risk_flags"],
        last_updated=raw["last_updated"],
    )


def get_purchase_order(po_number: str) -> PurchaseOrder:
    """Returns the PO lines and its goods or service receipts."""
    _apply_fault("get_purchase_order", po_number)
    raw = next(p for p in _load("purchase_orders.json") if p["po_number"] == po_number)
    return PurchaseOrder.model_validate(raw)


def list_approvers() -> list[Approver]:
    """Every user in the simulated authority register."""
    return [Approver.model_validate(a) for a in _load("approvers.json")]


def get_approver(approver_id: str) -> Approver | None:
    """Looks up the approver's role in the simulated authority register. Returns None for an unknown approver."""
    raw = next((a for a in _load("approvers.json") if a["approver_id"] == approver_id), None)
    return Approver.model_validate(raw) if raw else None


def _run_with_timeout(fn: Callable[[str], BaseModel], arg: str, timeout: float) -> BaseModel:
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(fn, arg).result(timeout=timeout)
    except FutureTimeout as exc:
        raise ToolTimeout(f"no answer after {timeout}s") from exc
    finally:
        executor.shutdown(wait=False)


def call_tool(
    fn: Callable[[str], BaseModel],
    arg: str,
    on_event: Callable[[dict], None],
    timeout: float = TIMEOUT_SECONDS,
) -> BaseModel | None:
    """Calls a tool with a timeout and at most MAX_ATTEMPTS attempts, and emits one `tool_attempt` event per attempt.

    Retries only a timeout or a TransientToolError. Returns None when the tool gives no valid result,
    so the caller treats the evidence as unavailable.
    """
    attempt_no = 0

    def attempt() -> BaseModel:
        nonlocal attempt_no
        attempt_no += 1
        started = time.monotonic()
        try:
            result = _run_with_timeout(fn, arg, timeout)
            outcome, error = "ok", None
            return result
        except ToolTimeout as exc:
            outcome, error = "timeout", str(exc)
            raise
        except Exception as exc:
            outcome, error = "error", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            on_event(
                {
                    "type": "tool_attempt",
                    "tool": fn.__name__,
                    "arg": arg,
                    "attempt": attempt_no,
                    "outcome": outcome,
                    "error": error,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                }
            )

    retrying = Retrying(
        stop=stop_after_attempt(MAX_ATTEMPTS),
        retry=retry_if_exception_type((ToolTimeout, TransientToolError)),
        reraise=True,
    )
    try:
        return retrying(attempt)
    except Exception:
        return None
