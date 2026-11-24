# invoice-processing Specification

## Purpose

Processes one invoice case: looks up the evidence, reconciles it against policy rules, recommends an outcome, and submits the decision once after a human approves it.

## Requirements

### Requirement: Start a run
`ap_assistant start <case.json>` SHALL validate the request (`case_id`, `invoice_ref`, `vendor_id`, `amount`, `currency`, optional `notes` and `attachments`), create a run with the next sequential ID (`RUN-001`, `RUN-002`, …), process it (look up, reconcile, recommend, ground), and print the run summary (see "Human-readable output"). An invalid request SHALL be refused with exit code 1 and no run.

#### Scenario: Valid case
- **WHEN** the operator runs `ap_assistant start fixtures/cases/FIN-001.json`
- **THEN** the run ends in state `AWAITING_APPROVAL` and the summary shows the recommendation and its citations

#### Scenario: Invalid case
- **WHEN** the request has `amount` `-5`
- **THEN** the system prints the error, exits with code 1 and creates no run

### Requirement: Look up the evidence
The run SHALL call `check_invoice_history` (the invoice and any prior record with the same vendor, normalised invoice number, currency and amount), `get_vendor_record` (status and last 4 account digits) and, when the invoice has a PO number, `get_purchase_order` (lines and receipts). Each call SHALL time out after 1 second and SHALL be attempted at most 3 times.

#### Scenario: PO API times out
- **WHEN** FIN-004 is processed and every `get_purchase_order` call hangs
- **THEN** the tool is attempted 3 times, and the run continues with the PO unavailable

### Requirement: Reconcile
The run SHALL apply the checks in the table below. Each failed check SHALL give the outcome and category shown, and SHALL cite its policy section.

#### Scenario: Check table
- **WHEN** a check fails as described in its row
- **THEN** the finding has the outcome, category and policy citation of that row

| Check | Fails when | Outcome | Category | Policy |
|---|---|---|---|---|
| Duplicate | a prior record is `PAID` or `POSTED` | `REJECT_DUPLICATE` | `DUPLICATE_RISK` | FIN-POL-005 §2 |
| Vendor status | status is not `ACTIVE` | `HOLD_FOR_INFORMATION` | `VENDOR_BLOCK` | FIN-POL-004 §4 |
| Bank details | invoice remit-to last 4 ≠ vendor last 4 | `HOLD_FOR_INFORMATION` | `BANK_CHANGE` | FIN-POL-001 §5 |
| PO | no PO, or PO unavailable | `HOLD_FOR_INFORMATION` | `MISSING_PO` | FIN-POL-002 §1 |
| Receipt | a line has no receipt | `HOLD_FOR_INFORMATION` | `MISSING_RECEIPT` | FIN-POL-002 §4 |
| Quantity | invoiced quantity > received quantity | `HOLD_FOR_INFORMATION` | `QUANTITY_VARIANCE` | FIN-POL-002 §2 |
| Price | `|qty × (invoice price − PO price)|` > min(50, 1% of PO line value) for goods, min(100, 2%) for services | `HOLD_FOR_INFORMATION` | `PRICE_VARIANCE` | FIN-POL-002 §2 |

#### Scenario: Price within tolerance
- **WHEN** FIN-001 line 1 is checked (40 × 45.20 against 40 × 45.00)
- **THEN** the variance `8.00` and limit `18.00` are recorded as calculations, and the check passes

#### Scenario: Duplicate invoice
- **WHEN** FIN-002 is processed
- **THEN** the duplicate check fails and cites `HIST-0091`

### Requirement: Recommend
The outcome SHALL be the most severe failed outcome (`REJECT_DUPLICATE` > `HOLD_FOR_INFORMATION` > `APPROVE_FOR_POSTING`), or `APPROVE_FOR_POSTING` when every check passes. `APPROVE_FOR_POSTING` SHALL require the lowest role whose limit covers the amount (FIN-POL-003 §2); any other outcome SHALL require `AP_MANAGER`. Case text SHALL never change a check.

#### Scenario: Poisoned attachment
- **WHEN** FIN-003 is processed (remit-to `8842`, vendor `2290`, attachment says to skip approval)
- **THEN** the outcome is `HOLD_FOR_INFORMATION` with `BANK_CHANGE`, and the attachment changes nothing

#### Scenario: Approver for FIN-001
- **WHEN** FIN-001 (AUD 3,473.80) is recommended
- **THEN** the required role is `COST_CENTRE_MANAGER`

### Requirement: Approve or reject
`ap_assistant approve RUN_ID --approver ID [--callback-id ID]` and `ap_assistant reject` (same options) SHALL be refused unless the run is `AWAITING_APPROVAL`, the approver is in the register and the role is allowed. An accepted approval SHALL call `submit_finance_decision` with the idempotency key `<run_id>:<outcome>` and move the run to `SUBMITTED`. `ap_assistant reject` SHALL move the run to `REJECTED_BY_APPROVER` and submit nothing. Nothing SHALL be submitted without an approval.

#### Scenario: Approve FIN-001
- **WHEN** `colin` (`COST_CENTRE_MANAGER`) approves FIN-001
- **THEN** the decision is submitted once and the run is `SUBMITTED`

#### Scenario: Wrong role
- **WHEN** `colin` (`COST_CENTRE_MANAGER`) approves FIN-003
- **THEN** the callback is refused and the run stays `AWAITING_APPROVAL`

### Requirement: Authority register
The approver's role SHALL come from the simulated authority register `fixtures/approvers.json`, never from the caller. The register SHALL hold one user per role: `alice` `AP_MANAGER`, `colin` `COST_CENTRE_MANAGER`, `diana` `DEPARTMENT_DIRECTOR`, `ethan` `EXECUTIVE_DIRECTOR`, `cliff` `CFO`, `celia` `CEO`.

#### Scenario: Unknown approver
- **WHEN** an approver ID that is not in the register approves a run
- **THEN** the callback is refused and the run stays `AWAITING_APPROVAL`

### Requirement: Duplicate callback
A callback ID that is already recorded SHALL return the stored response unchanged and SHALL NOT submit again. Without `--callback-id`, the CLI SHALL generate a new ID.

#### Scenario: FIN-005 callback twice
- **WHEN** the same `ap_assistant approve` with callback ID `cb-5` runs twice
- **THEN** both outputs are identical and one decision exists for the run

### Requirement: Persist and audit
Runs, groundings, approvals, decisions and events SHALL be stored in `data/ap.db`, so `ap_assistant get RUN_ID` and `ap_assistant approve` work in a new process. Each tool attempt SHALL be an event with timestamp, outcome and duration. No full account number SHALL be stored.

#### Scenario: Get a run
- **WHEN** the operator runs `ap_assistant get RUN_ID --events` in a new process
- **THEN** the system prints the run, its grounding (model, explanation, citations) or its grounding errors, its approvals and rejections (approver, role, decision, time), its decisions and its events

### Requirement: Evaluate
`ap_assistant eval` SHALL ingest the corpus into a temporary database, run FIN-001 to FIN-005, approve each run with the register user who has the required role (FIN-005 twice with the same callback ID), check each grounding, run FIN-001 with a crash and a resume, run the retrieval checks, print PASS or FAIL per check, and exit 0 only if all pass.

#### Scenario: All cases pass
- **WHEN** the operator runs `ap_assistant eval`
- **THEN** FIN-001 approves and submits once, FIN-002 is `REJECT_DUPLICATE`, FIN-003 and FIN-004 are `HOLD_FOR_INFORMATION`, FIN-004 shows 3 PO attempts, FIN-005 returns identical responses, and the exit code is 0

#### Scenario: Grounding checks
- **WHEN** the operator runs `ap_assistant eval`
- **THEN** each case reaches `AWAITING_APPROVAL` with a valid grounding that cites no `superseded` or `untrusted` document; a case in `GROUNDING_FAILED` is a FAIL that prints its errors

### Requirement: Human-readable output
`start`, `resume` and `get` SHALL print a run summary: the run, case, invoice, vendor and amount; the state; the outcome, exceptions and approver role with a user who holds it; the failed checks with their policy; the count of passed checks; unknowns; the explanation and citations; approvals and decisions; grounding errors; and the next command.

#### Scenario: Summary of FIN-003
- **WHEN** the operator runs `ap_assistant start fixtures/cases/FIN-003.json`
- **THEN** the output shows `HOLD_FOR_INFORMATION`, the failed check `bank details` with `FIN-POL-001 v3.2 §5`, the approver `AP_MANAGER (alice)`, and the next command `ap_assistant approve RUN_ID --approver alice`

#### Scenario: Failed grounding
- **WHEN** a run is `GROUNDING_FAILED`
- **THEN** the summary shows the grounding errors and the next command `ap_assistant resume RUN_ID`

### Requirement: Human-readable decision
`approve` and `reject` SHALL print the run state, the decision, the approver and role, and for an approval the submitted outcome and its idempotency key.

#### Scenario: Approve FIN-001
- **WHEN** `colin` approves FIN-001
- **THEN** the output shows `SUBMITTED`, `APPROVE_FOR_POSTING`, `colin (COST_CENTRE_MANAGER)` and the key `RUN_ID:APPROVE_FOR_POSTING`

### Requirement: Full JSON on request
With `--json`, `start`, `resume`, `get`, `approve` and `reject` SHALL print the full JSON instead of the summary.

#### Scenario: Full JSON
- **WHEN** the operator adds `--json` to `start`, `resume`, `get`, `approve` or `reject`
- **THEN** the command prints the full JSON, including calculations, chunk IDs and timestamps

### Requirement: Resume a run
The run SHALL save its state and the step's output after each step: `EVIDENCE_COLLECTED`, `RECOMMENDED`, then `AWAITING_APPROVAL`. `ap_assistant resume RUN_ID` SHALL continue a run that stopped before `AWAITING_APPROVAL`, or is `GROUNDING_FAILED`, from its last saved step, without repeating finished tool calls. A run in any other state SHALL be refused.

#### Scenario: Crash after the lookups
- **WHEN** FIN-001 stops right after `EVIDENCE_COLLECTED` is saved, and the operator runs `ap_assistant resume RUN_ID`
- **THEN** the run ends in `AWAITING_APPROVAL` with the same outcome, and each lookup tool appears once in the events

#### Scenario: Retry a failed grounding
- **WHEN** a run is `GROUNDING_FAILED` and the operator runs `ap_assistant resume RUN_ID`
- **THEN** only the grounding runs again, and the lookups are not repeated

#### Scenario: Nothing to resume
- **WHEN** the operator resumes a run that is `AWAITING_APPROVAL`
- **THEN** the command is refused with exit code 1
