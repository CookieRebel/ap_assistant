"""Pydantic models for the request, the tool results, the findings and the run."""

from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Outcome(str, Enum):
    APPROVE_FOR_POSTING = "APPROVE_FOR_POSTING"
    HOLD_FOR_INFORMATION = "HOLD_FOR_INFORMATION"
    REJECT_DUPLICATE = "REJECT_DUPLICATE"


class RunState(str, Enum):
    RECEIVED = "RECEIVED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    SUBMITTED = "SUBMITTED"
    REJECTED_BY_APPROVER = "REJECTED_BY_APPROVER"
    FAILED = "FAILED"


# --- Request -----------------------------------------------------------------


class Attachment(BaseModel):
    name: str
    text: str


class CaseRequest(BaseModel):
    case_id: str = Field(min_length=1)
    invoice_ref: str = Field(min_length=1)
    vendor_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    notes: str | None = None
    attachments: list[Attachment] = []


# --- Tool results --------------------------------------------------------------


class InvoiceLine(BaseModel):
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal


class Invoice(BaseModel):
    invoice_ref: str
    invoice_number: str
    vendor_id: str
    currency: str
    po_number: str | None
    remit_to_last4: str = Field(pattern=r"^\d{4}$")
    lines: list[InvoiceLine]
    tax: Decimal
    gross: Decimal


class HistoryRecord(BaseModel):
    history_id: str
    vendor_id: str
    invoice_number: str
    currency: str
    amount: Decimal
    status: str


class InvoiceHistory(BaseModel):
    invoice: Invoice
    matches: list[HistoryRecord]


class VendorRecord(BaseModel):
    vendor_id: str
    name: str
    status: str
    bank_last4: str = Field(pattern=r"^\d{4}$")
    risk_flags: list[str]
    last_updated: str


class POLine(BaseModel):
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal


class Receipt(BaseModel):
    receipt_id: str
    line_no: int
    quantity_received: Decimal


class PurchaseOrder(BaseModel):
    po_number: str
    vendor_id: str
    currency: str
    category: Literal["goods", "services"]
    approval_status: str
    lines: list[POLine]
    receipts: list[Receipt]


class Approver(BaseModel):
    approver_id: str
    name: str
    role: str


# --- Reconciliation and recommendation ------------------------------------------


class Calculation(BaseModel):
    name: str
    inputs: dict[str, str]
    formula: str
    result: str
    rounding: str = "ROUND_HALF_UP to 0.01"


class Finding(BaseModel):
    check: str
    passed: bool
    outcome: Outcome | None = None
    category: str | None = None
    policy: str
    detail: str
    evidence: list[str] = []


class Recommendation(BaseModel):
    outcome: Outcome
    exceptions: list[str]
    required_role: str
    amount: Decimal
    currency: str
    findings: list[Finding]
    calculations: list[Calculation]
    unknowns: list[str]
    next_action: str
