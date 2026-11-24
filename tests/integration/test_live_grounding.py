"""Model-dependent: grounds FIN-001 to FIN-005 with the configured OpenAI model.

Skipped by default (pyproject addopts: -m 'not live'). Run with:
    AP_LLM_MODEL=<model> OPENAI_API_KEY=<key> uv run pytest -m live
It sends the recommendations (no case notes, no attachments, no bank details) to OpenAI and costs a few cents.
"""

import os
from pathlib import Path

import pytest

from ap_assistant import workflow
from ap_assistant.ingest import read_corpus
from ap_assistant.llm import model_from_env
from ap_assistant.schemas import CaseRequest
from ap_assistant.store import Store

ROOT = Path(__file__).parents[2]

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("AP_LLM_MODEL", "offline") in ("", "offline") or not os.environ.get("OPENAI_API_KEY"),
        reason="needs AP_LLM_MODEL and OPENAI_API_KEY",
    ),
]


@pytest.mark.parametrize("case_id", ["FIN-001", "FIN-002", "FIN-003", "FIN-004", "FIN-005"])
def test_live_model_grounds_the_case(tmp_path, case_id):
    store = Store(tmp_path / "ap.db")
    store.replace_chunks(read_corpus(ROOT / "corpus"))
    request = CaseRequest.model_validate_json((ROOT / "fixtures" / "cases" / f"{case_id}.json").read_text())

    run = workflow.start(store, request, model=model_from_env())

    assert run["state"] == "AWAITING_APPROVAL", run["error"]
    assert run["grounding"]["model"] == os.environ["AP_LLM_MODEL"]
