# Design

## Context

The repo has the setup (`pyproject.toml`, Python 3.11) and `corpus/`. No code yet. See proposal.md.

## Decisions

### Modules

```
src/ap_assistant/
  schemas.py    pydantic models: request, tool results, finding, recommendation, run
  tools.py      the 3 simulated tools over fixtures/, plus call_tool(): timeout, 3 attempts, event
  reconcile.py  the checks → findings + calculations; recommend() picks outcome and role
  store.py      SQLite: runs, events, approvals, decisions
  workflow.py   start, approve, reject
  cli.py        typer commands, including eval
```

### Fixed sequence, no framework

`start` runs: look up → reconcile → recommend → save as `AWAITING_APPROVAL`. `approve` and `reject` load the run from SQLite and finish it. No agent framework is needed for a fixed sequence.

### Timeout

A tool call runs in a `ThreadPoolExecutor`; `future.result(timeout=1)` raises on a timeout. `tenacity` retries timeouts and transient errors, 3 attempts in total. The fixture file `faults.json` makes `PO-4004` hang.

### Idempotency

The `decisions` table has a unique `idempotency_key` (`<run_id>:<outcome>`). The `approvals` table has a unique `callback_id` and stores the response JSON. Approval runs in one `BEGIN IMMEDIATE` transaction: a known callback ID returns the stored response; otherwise it records the approval, inserts the decision (the simulated `submit_finance_decision`) and sets the run to `SUBMITTED`.

### Roles

Limits from FIN-POL-003 §2: `COST_CENTRE_MANAGER` 10,000, `DEPARTMENT_DIRECTOR` 50,000, `EXECUTIVE_DIRECTOR` 250,000, `CFO` 1,000,000, `CEO` above that. A higher role is accepted. `AP_MANAGER` approves non-posting outcomes; the corpus names no approver for a hold, so this is an assumption.

The role comes from a simulated authority register (FIN-POL-003 §4), `fixtures/approvers.json`, with one user per role:

| Approver ID | Role |
|---|---|
| `alice` | `AP_MANAGER` |
| `colin` | `COST_CENTRE_MANAGER` |
| `diana` | `DEPARTMENT_DIRECTOR` |
| `ethan` | `EXECUTIVE_DIRECTOR` |
| `cliff` | `CFO` |
| `celia` | `CEO` |

The approver ID itself is asserted on the command line, not authenticated. A production system takes it from the login.

### Fixtures

| Case | Invoice | Vendor (last 4) | PO | Key values |
|---|---|---|---|---|
| FIN-001 | INV-1001 | V-100 (4417) | PO-4001 goods | 40 × 45.20 (PO 45.00), 60 × 22.50; tax 315.80; gross 3,473.80; receipt GR-4001 |
| FIN-002 | INV-2002 | V-200 (7120) | PO-4002 services | gross 8,800.00; HIST-0091 `PAID` 8,800.00 |
| FIN-003 | INV-3003, remit-to 8842 | V-300 (2290) | PO-4003 services | gross 12,650.00; attachment with the ADV-001 text |
| FIN-004 | INV-4004 | V-400 (1133) | PO-4004 | gross 4,180.00; PO call hangs |
| FIN-005 | INV-5005 | V-100 (4417) | PO-4005 goods | 200 × 12.50; gross 2,750.00; receipt GR-4005 |

## Risks / Trade-offs

- [FIN-003 holds, it does not escalate] → Phase 3 adds the case-text classifier and the fraud-indicator count.
- [No crash recovery test] → State is saved before `start` exits, so `approve` in a new process works; crash points come later.
- [Rules in code drift from the corpus] → Each finding cites the policy version; a version check is a later step.
