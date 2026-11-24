# Tasks

## 1. Deterministic core

- [x] 1.1 Write `schemas.py` and the fixtures in `fixtures/` (design.md table); verify each case file parses as a valid request
- [x] 1.2 Write `tools.py` with the timeout and 3 attempts; verify with a unit test that the PO-4004 call is attempted 3 times and that V-100 returns only `4417`
- [x] 1.3 Write `reconcile.py` with the checks and `recommend()`; verify with unit tests: FIN-001 variance `8.00` and limit `18.00` pass, FIN-002 gives `REJECT_DUPLICATE`, FIN-003 gives `HOLD_FOR_INFORMATION`, FIN-001 needs `COST_CENTRE_MANAGER`
- [x] 1.4 Write `store.py` and `workflow.py`; verify with unit tests: approve submits once, a repeated callback ID returns the same response, reject submits nothing, a wrong role is refused
- [x] 1.5 Write `cli.py` (`start`, `get`, `approve`, `reject`, `eval`); verify `uv run ap_assistant eval` passes every check and `uv run pytest` passes
