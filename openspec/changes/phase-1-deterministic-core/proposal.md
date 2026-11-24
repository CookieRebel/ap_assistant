# Proposal

## Why

The brief (`docs/take_home_test.md`) asks for an accounts-payable assistant that reconciles invoice evidence, recommends an outcome and waits for human approval before it submits a decision. Phase 1 builds the smallest deterministic version that passes FIN-001 to FIN-005, with no RAG and no LLM.

## What Changes

- A CLI `ap` with `start`, `get`, `approve`, `reject` and `eval`.
- Three simulated tools over JSON fixtures: `check_invoice_history`, `get_vendor_record`, `get_purchase_order`, each with a timeout and 3 attempts.
- A reconciler with rules taken from the current policies, and a recommendation that picks the most severe outcome.
- An approval step before an idempotent `submit_finance_decision`.
- One SQLite file for runs, events, approvals and decisions.

Later phases: RAG and LLM grounding (phase 2); LLM case-text classifier and docs (phase 3). Not built: resume after a crash, fraud-indicator count, fuzzy duplicates, policy version check, co-approval, budgets.

## Capabilities

### New Capabilities

- `invoice-processing`: processing one invoice case from the request to an approved, submitted decision, and the evaluation of the five cases.

### Modified Capabilities

None.

## Impact

New code in `src/ap_assistant/`, fixtures in `fixtures/`, tests in `tests/unit/`. New runtime file `data/ap.db` (ignored by git). No new dependency.
