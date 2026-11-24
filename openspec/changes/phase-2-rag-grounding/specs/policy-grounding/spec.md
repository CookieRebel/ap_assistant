# Spec Delta

## Purpose

Explains a recommendation with verbatim, validated quotes from current policy, using an LLM in a bounded loop, while the outcome stays decided by code.

## ADDED Requirements

### Requirement: Ground the recommendation
After the recommendation, the run SHALL give the model the outcome, required role, findings and calculations, and the model SHALL return an explanation with citations (chunk ID, verbatim quote, the finding it supports). The chunk ID is internal: it identifies the retrieved text for validation. The model SHALL NOT receive the case notes or attachments. The grounding SHALL NOT change the outcome, the exceptions or the required role.

#### Scenario: FIN-001 is grounded
- **WHEN** FIN-001 is processed
- **THEN** the grounding cites FIN-POL-003 version 4.0 §2 for the required role `COST_CENTRE_MANAGER`

#### Scenario: Outcome is unchanged
- **WHEN** the model's explanation argues for a different outcome
- **THEN** the recommended outcome and required role stay as `recommend` set them

### Requirement: Show citations by document
Each citation shown to the user SHALL give the document ID and title, the version, the section number and heading, the verbatim quote, and the finding it supports. The code SHALL fill these fields from the ingested chunk metadata, not from the model. The chunk ID SHALL be kept in the stored grounding for the audit trail.

#### Scenario: Citation for FIN-001
- **WHEN** the operator runs `ap_assistant get RUN_ID` for FIN-001
- **THEN** a citation shows `FIN-POL-003 Delegated Financial Authority Matrix`, version `4.0`, section `§2 Standard operating expenditure`, a quote from that section, and the finding it supports

### Requirement: Bound the loop
The grounding loop SHALL make at most 4 model calls and at most 6 retrieval calls per run. The model SHALL have one tool only: `retrieve_finance_documents`. When a limit is reached before a valid answer exists, the grounding SHALL fail with the error `budget exhausted`.

#### Scenario: Model keeps searching
- **WHEN** the model asks for a 7th retrieval
- **THEN** the loop stops, and the run is `GROUNDING_FAILED` with the error `budget exhausted`

### Requirement: Validate the model output
The run SHALL accept the model's answer only if it matches the output schema; each cited chunk was retrieved in this run and has status `current`; each quote appears verbatim in its chunk; each failed finding has a citation from the policy document it names, and an approval has one from FIN-POL-003; and each number in the explanation appears in the recommendation or in a cited quote.

#### Scenario: Citation of an untrusted document
- **WHEN** the model cites `ADV-001#0`
- **THEN** the answer is rejected with the error that the document is not current

#### Scenario: Invented quote
- **WHEN** a quote does not appear in its chunk
- **THEN** the answer is rejected

#### Scenario: Invented number
- **WHEN** the explanation says `AUD 5,000` and no recommendation value or cited quote contains `5,000`
- **THEN** the answer is rejected

### Requirement: Repair or fail
A rejected answer SHALL get one repair call that lists the errors. If the repaired answer is also rejected, the budget is exhausted, or the model call fails, the run SHALL stop in state `GROUNDING_FAILED` with the errors, and no grounding SHALL be stored. Each rejected answer SHALL be an event with its errors. Without a valid grounding, the run SHALL NOT reach `AWAITING_APPROVAL`, because the approver must see source citations (FIN-POL-003 §5).

#### Scenario: Malformed output twice
- **WHEN** the model returns invalid JSON twice
- **THEN** the run has two `model_output_invalid` events, the run is `GROUNDING_FAILED` with both errors, and `approve` is refused

#### Scenario: Repair succeeds
- **WHEN** the first answer is rejected and the repaired answer is valid
- **THEN** the grounding is stored and the run is `AWAITING_APPROVAL`

### Requirement: Configure the model outside the code
The provider is OpenAI. The model name, the API key and an optional endpoint SHALL come from the environment variables `AP_LLM_MODEL`, `OPENAI_API_KEY` and `AP_LLM_BASE_URL` (default: the OpenAI API). When `AP_LLM_MODEL` is unset or `offline`, a deterministic offline model SHALL run. The grounding SHALL record the model name used.

#### Scenario: No model configured
- **WHEN** `AP_LLM_MODEL` is unset
- **THEN** the run completes offline, and the grounding shows model `offline`

### Requirement: Treat retrieved text as data
Retrieved chunk text SHALL reach the model inside delimiters that label it as data with its document status. Instructions inside retrieved text SHALL NOT change the validation, the outcome or the approval.

#### Scenario: Adversarial chunk is retrieved
- **WHEN** FIN-003 is grounded and a retrieval returns `ADV-001`
- **THEN** the outcome stays `HOLD_FOR_INFORMATION`, no citation of `ADV-001` is accepted, and an approval is still required
