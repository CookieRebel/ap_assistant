# Design

## Context

Phase 1 is built and archived (`openspec/specs/invoice-processing/spec.md`). `start` runs look up → reconcile → recommend in one call and saves only the final state. Findings cite policy sections as fixed labels such as `FIN-POL-002 v2.4 §2`. `rank-bm25` and `openai` are already pinned in `pyproject.toml`. See proposal.md.

## Decisions

### Modules

```
src/ap_assistant/
  ingest.py     front matter + split by "## " → chunks table
  retrieval.py  BM25 index over the chunks; retrieve_finance_documents(); retrieval event
  llm.py        ModelClient protocol; OpenAIModel (openai SDK); OfflineModel (deterministic)
  grounding.py  the bounded loop, validate(), repair
  workflow.py   start split into saved steps; resume()
  store.py      chunks table; evidence_json and grounding_json on runs
  cli.py        ingest, resume; eval adds grounding, retrieval and resume checks
```

### Chunks

- Front matter is parsed as `key: value` lines between the two `---` lines. No YAML dependency.
- One chunk per `## n. Heading` section. Chunk ID `<document_id>#<n>`, for example `FIN-POL-002#2`. A file without `##` sections is one chunk, `#0`. The `# Title` line is not indexed text; the title is metadata.
- `document_type` is `policy` for `FIN-POL-*` and `external` otherwise.
- The `chunks` table lives in `data/ap.db`. `ingest` deletes and re-inserts all rows in one transaction, so a failed ingest leaves the old chunks.

### Retrieval

- `BM25Okapi` over lowercase `[a-z0-9]+` tokens of document ID, title, heading and text. Built in memory on the first retrieval in a process: about 60 chunks, a few milliseconds.
- A chunk with status `superseded` or `untrusted` gets half its BM25 score. This puts `FIN-POL-003#2` above `FIN-POL-003-OLD#0` for authority queries, as the old document itself asks.
- Each result carries the citation string `<document_id> v<version> §<section> <heading>`.

### Model abstraction

- `ModelClient.complete(messages, tools) -> ModelReply` (text or tool calls). The workflow knows only this protocol.
- `OpenAIModel` uses the `openai` SDK chat completions with tool calling, `timeout=30`, `max_retries=2`. The provider is OpenAI; `AP_LLM_BASE_URL` is optional and defaults to the OpenAI API.
- `OfflineModel` is chosen when `AP_LLM_MODEL` is unset or `offline`. Turn 1: one retrieval per required citation, with the query `<document_id> <finding> <finding detail>` and `top_k=10`. Turn 2: for each, the expected section if it was retrieved (else the top chunk of that document), the line or sentence that shares most words with the finding as the quote, and a fixed explanation. It passes validation by construction, so an offline eval proves the plumbing, not model quality.

### Grounding loop

1. System message: the task, the output JSON schema, and the rule that text inside `<document id=… status=…>` tags is data.
2. User message: outcome, exceptions, required role, findings and calculations as JSON. No notes, no attachments.
3. Loop: a tool call runs `retrieve_finance_documents` and returns the chunks inside `<document>` tags. A text reply is parsed as the answer. Budget: 4 model calls, 6 retrievals; the repair call counts against the 4.
4. `validate()` returns a list of errors. Empty → the grounding is saved and the run goes to `AWAITING_APPROVAL`. Not empty → one repair message with the errors. Still not empty, budget exhausted, or a model call error → the run goes to `GROUNDING_FAILED` with the errors in `runs.error`, and no grounding is saved.

There is no fallback that writes a grounding without the model. FIN-POL-003 §5 requires the approver to see source citations, so a run without a valid grounding stops, and `resume` retries it.

### Validation details

- Schema: `{"explanation": str, "citations": [{"chunk_id", "quote", "finding"}]}` with pydantic; extra keys such as `outcome` are rejected.
- Quotes are compared after collapsing whitespace.
- Required citations: the document of each failed finding's policy label, plus `FIN-POL-003` for `APPROVE_FOR_POSTING`.
- Numbers: every `\d[\d,]*(\.\d+)?` in the explanation, with commas removed, must appear in the recommendation JSON or a cited quote. Integers up to 10 are exempt (line numbers, section numbers, counts). A number that is part of an identifier, such as `FIN-POL-012`, `HIST-0091` or `v2.4`, is not checked.

### Steps and resume

- `runs` gets `evidence_json` (the three tool results, `null` for an unavailable one) and `grounding_json`.
- `start` = `RECEIVED` → lookups → save `EVIDENCE_COLLECTED` → reconcile + recommend → save `RECOMMENDED` → grounding → save `AWAITING_APPROVAL` or `GROUNDING_FAILED`.
- `resume` loads the run and runs the remaining steps from the saved JSON. Lookups are not repeated after `EVIDENCE_COLLECTED`. A `GROUNDING_FAILED` run restarts at the grounding step.
- Crash simulation: `start(..., crash_after=STATE)` raises `SimulatedCrash` right after that state is saved. The CLI reads `AP_CRASH_AFTER` and exits with code 75. `eval` calls the workflow directly and catches the exception.
- A crash during `approve` needs no new code: the approval is one transaction, so a crash rolls it back, and the same callback can be sent again.

### Evaluation

- `eval` uses whatever model the environment configures, so it is offline by default and model-dependent when `AP_LLM_MODEL` is set (brief §7: separate stable tests from model-dependent runs).
- Unit tests use a scripted `FakeModel` that replays given replies: valid, invalid then valid, invalid twice, endless tool calls, a citation of `ADV-001`.
- A run in `GROUNDING_FAILED` is a FAIL in `eval`, with its errors printed.
- `tests/integration/test_live_grounding.py` is marked `live` and is skipped by default.
- `fixtures/retrieval_eval.json`: about 8 queries, each with its expected chunk ID, for example `"price variance tolerance goods"` → `FIN-POL-002#2`.

## Risks / Trade-offs

- [BM25 is lexical; a query with other words than the policy misses] → The model can retry with other words within the budget. Embeddings are the next step (design note).
- [The offline model passes by construction] → It is labelled `offline` in every run; only the live run measures the model.
- [The number check is a heuristic] → It catches invented amounts, the main risk. It can reject a valid answer that restates a number in another form; the run then stops in `GROUNDING_FAILED`, and `resume` retries.
- [A live model that keeps failing blocks the run] → Intended: no approval without citations. The errors on the run show why.
- [The ingested version can differ from the version a rule in `reconcile.py` cites] → Phase 2 does not check it; the citation shows the ingested version, so a reviewer sees the difference.
- [FIN-POL-004 is classified `restricted`] → Phase 2 does not restrict access by classification; the classification is in the metadata.
