import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ap_assistant.ingestion import read_corpus
from ap_assistant.financial_document_retrieval import Index, NoChunksError, RetrievalArgs, retrieve_finance_documents
from ap_assistant.store import Store

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def index():
    return Index(read_corpus(ROOT / "corpus"))


def ids(results):
    return [r.chunk_id for r in results]


def test_current_policy_ranks_above_the_superseded_one(index):
    results = ids(index.search(RetrievalArgs(query="approval limit cost centre manager", top_k=10)))

    assert results[0] == "FIN-POL-003#2"
    if "FIN-POL-003-OLD#0" in results:
        assert results.index("FIN-POL-003-OLD#0") > 0


def test_adversarial_document_is_returned_and_labelled(index):
    results = index.search(RetrievalArgs(query="bank account changed urgent payment", top_k=5))

    adversarial = [r for r in results if r.document_id == "ADV-001"]
    assert adversarial and adversarial[0].status == "untrusted"


def test_result_carries_citation_metadata(index):
    top = index.search(RetrievalArgs(query="price variance tolerance for goods and services", top_k=1))[0]

    assert top.citation == "FIN-POL-002 v2.4 §2 Tolerances"
    assert top.document_type == "policy"
    assert top.score > 0


@pytest.mark.parametrize("case", json.loads((ROOT / "fixtures" / "retrieval_eval.json").read_text()), ids=lambda c: c["expected"])
def test_fixed_query_finds_its_chunk_in_the_top_3(index, case):
    assert case["expected"] in ids(index.search(RetrievalArgs(query=case["query"], top_k=3)))


def test_no_chunks_gives_the_ingest_error(tmp_path):
    with pytest.raises(NoChunksError, match="ap_assistant ingest"):
        retrieve_finance_documents(Store(tmp_path / "ap.db"), RetrievalArgs(query="x"))


def test_retrieval_emits_an_event(tmp_path):
    store = Store(tmp_path / "ap.db")
    store.replace_chunks(read_corpus(ROOT / "corpus"))
    events = []

    retrieve_finance_documents(store, RetrievalArgs(query="duplicate invoice", top_k=2), events.append)

    assert events[0]["type"] == "retrieval"
    assert len(events[0]["results"]) == 2


def test_top_k_is_bounded():
    with pytest.raises(ValidationError):
        RetrievalArgs(query="x", top_k=11)
