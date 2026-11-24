# Design note

The design decisions and the architecture diagram are in the [README](../README.md#design-decisions). This note covers how the parts work and what a production version would change.

## Orchestration

An explicit state graph in plain Python, without an agent framework. A framework would add a runtime to learn and to audit, for a sequence that never branches on model output. The code enforces every control itself: the order of the steps, the budget, the validation and the approval gate.

```
start → RECEIVED → lookups → EVIDENCE_COLLECTED → reconcile + recommend → RECOMMENDED
      → grounding → AWAITING_APPROVAL ──approve──→ SUBMITTED
                  ↘ GROUNDING_FAILED     └reject──→ REJECTED_BY_APPROVER
FAILED: the invoice history is unavailable
```

- The run is saved after each step. `resume` continues from the last saved step and never repeats a finished lookup.
- The only loop is the grounding loop, bounded to 4 model calls and 6 retrievals.

## RAG design

- **Ingestion:** each Markdown document is split into one chunk per `## n.` section, with its front matter as metadata: document ID, title, version, status (`current`, `superseded`, `untrusted`), classification and section. 15 documents give 58 chunks. Chunk ID: `FIN-POL-002#2`.
- **Retrieval:** BM25 over the document ID, title, heading and text. A `superseded` or `untrusted` chunk keeps half its score: it is still returned and labelled, but ranks below current policy. Each result carries a citation such as `FIN-POL-002 v2.4 §2 Tolerances`.
- **Quality measure:** 8 fixed queries, each with its expected chunk, run in `eval`. All 8 rank their expected chunk in the top 3.
- **Limitations:** BM25 is lexical, so a query in other words can miss. Embeddings or a hybrid search are the next step. Sections are short, so no further splitting was needed.

## Model and tool contracts

| Contract | Input | Output | Enforced by |
|---|---|---|---|
| `check_invoice_history`, `get_vendor_record`, `get_purchase_order` | an ID | pydantic models | 1 s timeout, 3 attempts, one audit event per attempt; only the last 4 account digits leave the tool |
| `retrieve_finance_documents` | `query`, `top_k` 1 to 10 | ranked chunks with citation metadata | pydantic validation of the arguments; a `retrieval` event per call |
| The LLM | the recommendation (outcome, findings, calculations, required citations); never the case notes or attachments | `{"explanation", "citations": [{"chunk_id", "quote", "finding"}]}` | a schema that forbids extra keys, such as an `outcome` |
| `submit_finance_decision` | run ID, outcome, idempotency key, callback ID | the decision row | refuses without a recorded approval; the key is unique |

The code validates the model's answer: each cited chunk was retrieved in this run and is `current`; each quote appears verbatim in its chunk; each failed finding has a citation from the policy it names; each number in the explanation appears in the recommendation or in a quote. A rejected answer gets one repair call with the errors. After that, the run stops in `GROUNDING_FAILED`, because an approver must see source citations (FIN-POL-003 §5).

## Trust boundaries

| Source | Trust | Control |
|---|---|---|
| Code rules and the authority register | trusted | the only source of outcomes and roles |
| Simulated systems (fixtures) | trusted data, unreliable delivery | timeout, retry, "unavailable" becomes a hold |
| Case notes and attachments | untrusted | never read by a check, never sent to the model |
| Corpus documents | trusted only when `current` | status label in the prompt, `<document>` delimiters, untrusted and superseded chunks cannot be cited |
| Model output | untrusted | schema and citation validation; cannot change the outcome |
| Approver ID on the command line | asserted | role from the register; not authenticated |

## Persistence

One SQLite file, `data/ap.db`: `runs` (state, request, evidence, recommendation, grounding), `events` (the audit trail), `approvals` (one row per callback ID, with the stored response), `decisions` (unique idempotency key), `chunks`. An approval runs in one `BEGIN IMMEDIATE` transaction, so a crash rolls it back and two processes cannot handle the same callback.

## Failure handling

| Failure | Behaviour |
|---|---|
| Tool timeout | 3 attempts, then the evidence is unavailable and the run holds (FIN-004) |
| Transient tool error | retried like a timeout (not exercised by a fixture) |
| Malformed or invalid model output | one repair call, then `GROUNDING_FAILED`; `resume` retries |
| Model call error (network, key, rate limit) | `GROUNDING_FAILED` with the error |
| Crash between steps | `resume` continues from the last saved step |
| Duplicate approval callback | the stored response, no second decision (FIN-005) |
| Wrong role, unknown approver, run not waiting | refused, with an `approval_refused` event |

## Component and configuration manifest

| Component | Implementation | Configuration |
|---|---|---|
| Model | OpenAI chat completions with tool calling, or the offline model | `AP_LLM_MODEL`, `OPENAI_API_KEY` in `.env` |
| Agent runtime | plain Python state graph (`workflow.py`, `grounding.py`) | budget constants in `grounding.py` |
| Document store and index | `chunks` table, BM25 in memory (`rank-bm25`) | `ap_assistant ingest` |
| Persistence | SQLite | `data/ap.db` |
| Tools | `tools.py`, `financial_document_retrieval.py`, `submit_finance_decision` in `workflow.py` | `fixtures/`, `fixtures/faults.json` |
| API surface | CLI (`typer`) | see the README |

## Production changes

- **Identity and authority:** authenticated approvers; roles and delegations from the real authority register, with its version recorded on each approval (FIN-POL-003 §4, §5); the two-approver rule for higher-risk payments.
- **Rules and policy versions:** check at startup that the policy version each rule cites matches the ingested corpus, and refuse to run on a mismatch.
- **Integrations:** real ERP and vendor-master APIs behind the same tool contracts; a sandboxed posting API with idempotency keys that are unique across environments.
- **Infrastructure:** Postgres instead of SQLite; approval callbacks through a queue; secrets in a secrets manager; OpenTelemetry traces from the existing events.
- **Retrieval:** a hybrid of BM25 and embeddings, and access control by document classification.
- **Typed result:** separate fields for sourced facts, inferences, assumptions and actions taken, and a confidence value.
