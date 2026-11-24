# Spec Delta

## MODIFIED Requirements

### Requirement: Start a run
`ap_assistant start <case.json>` SHALL validate the request (`case_id`, `invoice_ref`, `vendor_id`, `amount`, `currency`, optional `notes` and `attachments`), create a run with the next sequential ID (`RUN-001`, `RUN-002`, …), process it (look up, reconcile, recommend, ground), and print the run summary (see "Human-readable output"). An invalid request SHALL be refused with exit code 1 and no run.

#### Scenario: Valid case
- **WHEN** the operator runs `ap_assistant start fixtures/cases/FIN-001.json`
- **THEN** the run ends in state `AWAITING_APPROVAL` and the summary shows the recommendation and its citations

#### Scenario: Invalid case
- **WHEN** the request has `amount` `-5`
- **THEN** the system prints the error, exits with code 1 and creates no run

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

## ADDED Requirements

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
