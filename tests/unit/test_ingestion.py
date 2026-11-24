from pathlib import Path

import pytest

from ap_assistant.ingestion import IngestError, read_corpus
from ap_assistant.store import Store

CORPUS = Path(__file__).parents[2] / "corpus"


def test_supplied_corpus_is_chunked_by_section():
    chunks = {c.chunk_id: c for c in read_corpus(CORPUS)}

    assert len({c.document_id for c in chunks.values()}) == 15
    tolerances = chunks["FIN-POL-002#2"]
    assert (tolerances.version, tolerances.status, tolerances.heading) == ("2.4", "current", "Tolerances")
    assert tolerances.text.startswith("For goods, a line is within tolerance")
    assert chunks["ADV-001#0"].status == "untrusted"
    assert chunks["ADV-001#0"].document_type == "external"
    assert chunks["FIN-POL-003-OLD#0"].status == "superseded"


def test_file_without_document_id_leaves_the_old_chunks(tmp_path):
    store = Store(tmp_path / "ap.db")
    store.replace_chunks(read_corpus(CORPUS))
    before = len(store.list_chunks())
    bad = tmp_path / "corpus"
    bad.mkdir()
    (bad / "x.md").write_text("---\ntitle: No ID\n---\n\n# X\n\nText.\n")

    with pytest.raises(IngestError, match="no document_id"):
        store.replace_chunks(read_corpus(bad))

    assert len(store.list_chunks()) == before


def test_reingest_replaces_the_old_version(tmp_path):
    store = Store(tmp_path / "ap.db")
    store.replace_chunks(read_corpus(CORPUS))
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    text = (CORPUS / "02_three_way_matching_and_tolerances.md").read_text().replace("version: 2.4", "version: 2.5")
    (corpus / "02.md").write_text(text)

    store.replace_chunks(read_corpus(corpus))

    assert {c.version for c in store.list_chunks()} == {"2.5"}
