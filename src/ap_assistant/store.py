"""SQLite persistence for runs, events, approvals and decisions."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ap_assistant.schemas import Chunk

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    state TEXT NOT NULL,
    request_json TEXT NOT NULL,
    evidence_json TEXT,
    recommendation_json TEXT,
    grounding_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    callback_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    approver_id TEXT NOT NULL,
    role TEXT NOT NULL,
    decision TEXT NOT NULL,
    response_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    callback_id TEXT NOT NULL REFERENCES approvals (callback_id),
    submitted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    chunk_json TEXT NOT NULL
);
"""

# Columns added after phase 1. A data/ap.db created by phase 1 gets them on open.
ADDED_RUN_COLUMNS = ["evidence_json", "grounding_json"]
RUN_JSON_COLUMNS = {"evidence_json", "recommendation_json", "grounding_json"}


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: autocommit, except inside transaction().
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.chunk_index = None  # the BM25 index, built by financial_document_retrieval.index_for() on first use
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(runs)")}
        for column in ADDED_RUN_COLUMNS:
            if column not in existing:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {column} TEXT")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """BEGIN IMMEDIATE takes the write lock at the start, so two processes cannot both resolve one callback."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # --- runs ---

    def create_run(self, case_id: str, state: str, request_json: str) -> str:
        """Inserts a run with the next sequential ID (RUN-001, RUN-002, …) and returns that ID.

        The transaction holds the write lock, so two processes cannot take the same number.
        """
        ts = now()
        with self.transaction():
            next_no = self.conn.execute("SELECT COALESCE(MAX(rowid), 0) + 1 FROM runs").fetchone()[0]
            run_id = f"RUN-{next_no:03d}"
            self.conn.execute(
                "INSERT INTO runs (run_id, case_id, state, request_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, case_id, state, request_json, ts, ts),
            )
        return run_id

    def update_run(self, run_id: str, state: str, error: str | None = None, **json_columns: str) -> None:
        """Sets the state and the error (None clears it), plus any of evidence_json, recommendation_json, grounding_json."""
        unknown = set(json_columns) - RUN_JSON_COLUMNS
        if unknown:
            raise ValueError(f"not a run JSON column: {unknown}")
        assignments = ", ".join(f"{column} = ?" for column in json_columns)
        self.conn.execute(
            f"UPDATE runs SET state = ?, error = ?, updated_at = ?{', ' if assignments else ''}{assignments} WHERE run_id = ?",
            (state, error, now(), *json_columns.values(), run_id),
        )

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()

    # --- chunks ---

    def replace_chunks(self, chunks: list[Chunk]) -> None:
        """Replaces all chunks in one transaction."""
        with self.transaction():
            self.conn.execute("DELETE FROM chunks")
            self.conn.executemany(
                "INSERT INTO chunks (chunk_id, chunk_json) VALUES (?, ?)",
                [(c.chunk_id, c.model_dump_json()) for c in chunks],
            )
        self.chunk_index = None

    def list_chunks(self) -> list[Chunk]:
        rows = self.conn.execute("SELECT chunk_json FROM chunks ORDER BY rowid").fetchall()
        return [Chunk.model_validate_json(r["chunk_json"]) for r in rows]

    def has_chunks(self) -> bool:
        return self.conn.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is not None

    # --- events ---

    def add_event(self, run_id: str, event_type: str, data: dict) -> None:
        self.conn.execute(
            "INSERT INTO events (run_id, ts, type, data_json) VALUES (?, ?, ?, ?)",
            (run_id, now(), event_type, json.dumps(data)),
        )

    def list_events(self, run_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM events WHERE run_id = ? ORDER BY event_id", (run_id,)).fetchall()
        return [{"ts": r["ts"], "type": r["type"], **json.loads(r["data_json"])} for r in rows]

    # --- approvals ---

    def get_approval(self, callback_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM approvals WHERE callback_id = ?", (callback_id,)).fetchone()

    def insert_approval(self, callback_id: str, run_id: str, approver_id: str, role: str, decision: str) -> None:
        self.conn.execute(
            "INSERT INTO approvals (callback_id, run_id, approver_id, role, decision, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (callback_id, run_id, approver_id, role, decision, now()),
        )

    def list_approvals(self, run_id: str) -> list[dict]:
        """The approvals and rejections of a run, without the stored response."""
        rows = self.conn.execute(
            "SELECT approver_id, role, decision, callback_id, created_at FROM approvals WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_approval_response(self, callback_id: str, response: dict) -> None:
        self.conn.execute(
            "UPDATE approvals SET response_json = ? WHERE callback_id = ?", (json.dumps(response), callback_id)
        )

    # --- decisions ---

    def insert_decision(self, idempotency_key: str, run_id: str, outcome: str, callback_id: str) -> dict:
        """Inserts the decision once. A repeated idempotency key returns the existing decision."""
        self.conn.execute(
            "INSERT OR IGNORE INTO decisions (idempotency_key, run_id, outcome, callback_id, submitted_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (idempotency_key, run_id, outcome, callback_id, now()),
        )
        row = self.conn.execute("SELECT * FROM decisions WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        return dict(row)

    def list_decisions(self, run_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM decisions WHERE run_id = ? ORDER BY decision_id", (run_id,)).fetchall()
        return [dict(r) for r in rows]
