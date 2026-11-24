# Proposal

## Why

The brief (`docs/take_home_test.md` §2–§4) requires a RAG pipeline, an actual LLM, a bounded agent loop, validated model output and restart/resume. Phase 1 has none of these: its recommendation cites policy sections by hand-written labels, not by retrieved text. Phase 2 grounds each recommendation in retrieved, cited policy text and lets a run survive a crash.

## What Changes

- `ap_assistant ingest` reads `corpus/`, splits each document into one chunk per `##` section, and stores the chunks with their metadata (document ID, version, status, classification, section).
- A new tool `retrieve_finance_documents` ranks chunks with BM25 and returns them with citation metadata. Superseded and untrusted documents are returned, but labelled and ranked lower.
- A grounding step after the recommendation: an LLM, in a bounded loop, queries the retrieval tool and returns an explanation with verbatim quotes. Code validates every citation and every number. Invalid output gets one repair attempt; after that, or when the budget runs out, the run stops in `GROUNDING_FAILED` with the errors, because an approver must see source citations (FIN-POL-003 §5). The LLM never sets or changes the outcome.
- The provider is OpenAI, configured by environment variables only. Without a configured model, a deterministic offline model runs, and the run records that.
- Each step of `start` is saved. `ap_assistant resume RUN_ID` continues a run that stopped between steps, or retries a failed grounding, without repeating finished tool calls.
- `ap_assistant eval` adds grounding checks, a retrieval-quality check with fixed queries, and a crash-and-resume case.

Not in this phase (phase 3): the LLM case-text classifier, the fraud-indicator count and the FIN-003 escalation; a typed result with sourced facts, inferences, actions taken and a confidence value; a transient-failure fixture; access control by document classification; the README, design note and diagrams.

## Capabilities

### New Capabilities

- `policy-retrieval`: ingesting the policy corpus, chunking it, and ranking chunks for a query with citation metadata.
- `policy-grounding`: the bounded LLM loop that cites policy text for a recommendation, and the validation, repair and failure around it.

### Modified Capabilities

- `invoice-processing`: `start` adds the grounding step and saves each step; a new `resume` command; `get` shows the grounding; `eval` adds grounding, retrieval and resume checks.

## Impact

New modules `ingest.py`, `retrieval.py`, `grounding.py` and `llm.py` in `src/ap_assistant/`; changes to `workflow.py`, `store.py` and `cli.py`. A new table `chunks`, and new columns `evidence_json` and `grounding_json` on `runs`. Uses the already pinned `rank-bm25` and `openai` packages. A live model needs `OPENAI_API_KEY` and network access; unit tests and the offline eval do not.
