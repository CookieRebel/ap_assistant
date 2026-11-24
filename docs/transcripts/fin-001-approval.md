# Transcript: FIN-001, a valid three-way match

Captured with the live model `gpt-5.4` on 2026-11-24, after `uv run ap_assistant ingest`. The case is approved and submitted once. The same approval callback (`cb-1001`) is then delivered again and returns the stored response without a second submission. A new callback for the finished run is refused.

```
$ uv run ap_assistant start fixtures/cases/FIN-001.json
RUN-001  FIN-001  invoice INV-1001  vendor V-100  AUD 3,473.80
State:        AWAITING_APPROVAL

Outcome:      APPROVE_FOR_POSTING
Exceptions:   none
Approver:     COST_CENTRE_MANAGER (colin)
Passed checks: 10

Explanation (model: gpt-5.4)
  Approve for posting. The required approver is the COST_CENTRE_MANAGER because the amount is AUD
  3473.80 and FIN-POL-003 section 2 sets the Cost Centre Manager approval limit at AUD 10,000. The
  recommendation remains APPROVE_FOR_POSTING with no exceptions.

Citations
  [1] FIN-POL-003 Delegated Financial Authority Matrix, v4.0, §2 Standard operating expenditure
      > | Role | Maximum approval |
      > | --- | ---: |
      > | Cost Centre Manager | AUD 10,000 |
      > | Department Director | AUD 50,000 |
      > …
      supports: required role COST_CENTRE_MANAGER

Next: ap_assistant approve RUN-001 --approver colin
(exit code 0)

$ uv run ap_assistant approve RUN-001 --approver colin --callback-id cb-1001
RUN-001  SUBMITTED
Decision APPROVE_FOR_POSTING submitted, approved by colin (COST_CENTRE_MANAGER)
Idempotency key: RUN-001:APPROVE_FOR_POSTING
(exit code 0)

$ uv run ap_assistant approve RUN-001 --approver colin --callback-id cb-1001
RUN-001  SUBMITTED
Decision APPROVE_FOR_POSTING submitted, approved by colin (COST_CENTRE_MANAGER)
Idempotency key: RUN-001:APPROVE_FOR_POSTING
(exit code 0)

$ uv run ap_assistant approve RUN-001 --approver colin --callback-id cb-1002
error: run RUN-001 is SUBMITTED, not AWAITING_APPROVAL
(exit code 1)

```
