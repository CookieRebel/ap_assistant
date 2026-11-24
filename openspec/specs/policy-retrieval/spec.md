# policy-retrieval Specification

## Purpose


Turns the finance-policy corpus into citable chunks and ranks them for a query, so that every policy statement in a recommendation can point to retrieved source text.

## Requirements

### Requirement: Ingest the corpus
`ap_assistant ingest [CORPUS_DIR]` (default `corpus/`) SHALL read each Markdown file's front matter, split its body into one chunk per `##` section (a file without sections is one chunk), replace all previously ingested chunks, and print the chunk count per document. A file without a `document_id` SHALL stop the ingest with exit code 1 and leave the previous chunks unchanged.

#### Scenario: Ingest the supplied corpus
- **WHEN** the operator runs `ap_assistant ingest`
- **THEN** all 15 documents are stored, and the chunk `FIN-POL-002#2` has version `2.4`, status `current` and heading `Tolerances`

#### Scenario: Corpus changes
- **WHEN** a policy file gets a new version and the operator runs `ap_assistant ingest` again
- **THEN** retrieval returns only the new version's chunks

### Requirement: Retrieve finance documents
The tool `retrieve_finance_documents(query, top_k)` (`top_k` 1 to 10, default 5) SHALL return chunks ranked by relevance, each with chunk ID, document ID, document type, title, version, status, classification, section, relevance score, text and a citation such as `FIN-POL-002 v2.4 §2 Tolerances`. Documents with status `superseded` or `untrusted` SHALL be returned with that status and ranked below a current document of equal relevance.

#### Scenario: Current policy ranks above the superseded one
- **WHEN** the query is `approval limit cost centre manager`
- **THEN** `FIN-POL-003#2` ranks above `FIN-POL-003-OLD`, and `FIN-POL-003-OLD` is labelled `superseded`

#### Scenario: Adversarial document is labelled
- **WHEN** the query is `bank account changed urgent payment`
- **THEN** the results include `ADV-001` labelled `untrusted`

#### Scenario: Nothing ingested
- **WHEN** a run needs retrieval and no chunks exist
- **THEN** the command stops with exit code 1 and the message to run `ap_assistant ingest` first

### Requirement: Audit retrieval
Each retrieval during a run SHALL be an event with the query, the returned chunk IDs and scores, and the duration.

#### Scenario: Retrieval event
- **WHEN** a run retrieves policy text
- **THEN** `ap_assistant get RUN_ID --events` shows a `retrieval` event with the query and the chunk IDs

### Requirement: Measure retrieval quality
`ap_assistant eval` SHALL run the fixed queries in `fixtures/retrieval_eval.json`, each with its expected chunk ID, and report PASS when the expected chunk is in the top 3.

#### Scenario: Retrieval checks
- **WHEN** the operator runs `ap_assistant eval`
- **THEN** each retrieval query prints PASS or FAIL, and the hit rate at 3 is printed
