# Tasks

## 1. Retrieval, grounding and resume

- [ ] 1.1 Write `ingest.py`, the `chunks` table and `ap_assistant ingest`; verify with unit tests: 15 documents ingested, `FIN-POL-002#2` has version `2.4` and heading `Tolerances`, a file without `document_id` leaves the old chunks
- [ ] 1.2 Write `retrieval.py` and `fixtures/retrieval_eval.json`; verify with unit tests: `FIN-POL-003#2` ranks above `FIN-POL-003-OLD#0`, `ADV-001` is returned as `untrusted`, no chunks gives the "run ingest first" error, each fixed query finds its chunk in the top 3
- [ ] 1.3 Write `llm.py` (`OpenAIModel`, `OfflineModel`) and `grounding.py`; verify with a scripted fake model: a valid answer is accepted, a citation of `ADV-001`, an invented quote and an invented number are rejected, invalid output twice and an exhausted budget each give `GROUNDING_FAILED` with the errors, a valid repair is accepted, the outcome never changes
- [ ] 1.4 Split `start` into saved steps, add `resume` and the `AP_CRASH_AFTER` hook; verify with unit tests: a crash after `EVIDENCE_COLLECTED` resumes to the same outcome without repeated lookups, a `GROUNDING_FAILED` run resumes at the grounding step, resuming an `AWAITING_APPROVAL` run is refused
- [ ] 1.5 Extend `get` and `eval`; add the `live` test in `tests/integration/`; verify `uv run ap_assistant eval` passes every check offline and `uv run pytest` passes
