"""BM25 ranking over the ingested chunks, and the retrieve_finance_documents tool."""

import re
import time
from collections.abc import Callable

from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi

from ap_assistant.schemas import Chunk, RetrievedChunk
from ap_assistant.store import Store

TOKEN = re.compile(r"[a-z0-9]+")
# A superseded or untrusted chunk keeps half its score: still returned and labelled, but ranked below
# a current chunk of equal relevance (FIN-POL-003-OLD asks for this).
NOT_CURRENT_FACTOR = 0.5


class NoChunksError(Exception):
    def __init__(self) -> None:
        super().__init__("no policy chunks stored: run `ap_assistant ingest` first")


class RetrievalArgs(BaseModel):
    """The arguments of retrieve_finance_documents, validated before the search runs."""

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


def _tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


class Index:
    def __init__(self, chunks: list[Chunk]):
        if not chunks:
            raise NoChunksError()
        self.chunks = chunks
        self.by_id = {c.chunk_id: c for c in chunks}
        self.bm25 = BM25Okapi([_tokens(f"{c.document_id} {c.title} {c.heading} {c.text}") for c in chunks])

    def search(self, args: RetrievalArgs) -> list[RetrievedChunk]:
        scores = self.bm25.get_scores(_tokens(args.query))
        ranked = []
        for chunk, score in zip(self.chunks, scores):
            if chunk.status != "current":
                score *= NOT_CURRENT_FACTOR
            ranked.append(RetrievedChunk(**chunk.model_dump(), score=round(float(score), 4)))
        ranked.sort(key=lambda c: c.score, reverse=True)
        return ranked[: args.top_k]


def index_for(store: Store) -> Index:
    """Builds the index on the first retrieval for this store, from the chunks table. replace_chunks() clears it."""
    if store.chunk_index is None:
        store.chunk_index = Index(store.list_chunks())
    return store.chunk_index


def retrieve_finance_documents(
    store: Store, args: RetrievalArgs, on_event: Callable[[dict], None] | None = None
) -> list[RetrievedChunk]:
    """Returns the top_k chunks for the query, and emits a `retrieval` event with the chunk IDs and scores."""
    started = time.monotonic()
    results = index_for(store).search(args)
    if on_event is not None:
        on_event(
            {
                "type": "retrieval",
                "query": args.query,
                "top_k": args.top_k,
                "results": [{"chunk_id": r.chunk_id, "score": r.score, "status": r.status} for r in results],
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
    return results
