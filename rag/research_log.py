from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS research_queries (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    conversation_id TEXT,
    user_id TEXT,
    user_groups TEXT,
    user_question TEXT NOT NULL,
    initial_retrieval_query TEXT,
    final_retrieval_query TEXT,
    model TEXT,
    model_parameters_json TEXT,
    auxiliary INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    answer_text TEXT
);

CREATE TABLE IF NOT EXISTS retrieval_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id TEXT NOT NULL,
    round_no INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    search_query TEXT NOT NULL,
    plan_json TEXT,
    statistics_json TEXT,
    timings_json TEXT,
    retrieval_mode TEXT,
    evidence_decision_json TEXT,
    FOREIGN KEY(query_id) REFERENCES research_queries(id)
);

CREATE TABLE IF NOT EXISTS retrieval_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    document_id TEXT,
    title TEXT,
    path TEXT,
    source_url TEXT,
    rank INTEGER,
    rrf_rank INTEGER,
    elasticsearch_rank INTEGER,
    vector_rank INTEGER,
    chunk_no INTEGER,
    rrf_score REAL,
    elasticsearch_score REAL,
    vector_score REAL,
    reranker_score REAL,
    reranker_raw_score REAL,
    document_date TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(round_id) REFERENCES retrieval_rounds(id)
);

CREATE INDEX IF NOT EXISTS idx_research_queries_created_at
    ON research_queries(created_at);
CREATE INDEX IF NOT EXISTS idx_retrieval_rounds_query_id
    ON retrieval_rounds(query_id, round_no);
CREATE INDEX IF NOT EXISTS idx_retrieval_documents_round_stage
    ON retrieval_documents(round_id, stage);
CREATE INDEX IF NOT EXISTS idx_retrieval_documents_document_id
    ON retrieval_documents(document_id);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class ResearchLog:
    """Small SQLite provenance store for RAG research sessions.

    A new SQLite connection is opened per operation. Together with WAL mode this
    keeps the implementation robust when FastAPI serves several requests in
    parallel without sharing sqlite3 connection objects across threads.
    """

    def __init__(self, database: str | Path, enabled: bool = True, store_answer: bool = False):
        self.enabled = bool(enabled)
        self.database = Path(database).expanduser()
        self.store_answer = bool(store_answer)

        if self.enabled:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def start_query(
        self,
        *,
        query_id: str,
        conversation_id: str | None,
        user_id: str | None,
        user_groups: str | None,
        user_question: str,
        initial_retrieval_query: str,
        model: str,
        model_parameters: dict[str, Any],
        auxiliary: bool,
    ) -> None:
        if not self.enabled:
            return

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO research_queries (
                    id, created_at, conversation_id, user_id, user_groups,
                    user_question, initial_retrieval_query, model,
                    model_parameters_json, auxiliary, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')
                """,
                (
                    query_id,
                    _utcnow(),
                    conversation_id,
                    user_id,
                    user_groups,
                    user_question,
                    initial_retrieval_query,
                    model,
                    _json(model_parameters),
                    1 if auxiliary else 0,
                ),
            )

    def start_round(
        self,
        *,
        query_id: str,
        round_no: int,
        search_query: str,
        payload: dict[str, Any],
    ) -> int | None:
        if not self.enabled:
            return None

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO retrieval_rounds (
                    query_id, round_no, created_at, search_query,
                    plan_json, statistics_json, timings_json, retrieval_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query_id,
                    round_no,
                    _utcnow(),
                    search_query,
                    _json(payload.get("plan")) if payload.get("plan") is not None else None,
                    _json(payload.get("statistics")) if payload.get("statistics") is not None else None,
                    _json(payload.get("timings")) if payload.get("timings") is not None else None,
                    payload.get("retrieval_mode"),
                ),
            )
            return int(cursor.lastrowid)

    def set_evidence_decision(self, round_id: int | None, decision: dict[str, Any]) -> None:
        if not self.enabled or round_id is None:
            return
        with self._connect() as connection:
            connection.execute(
                "UPDATE retrieval_rounds SET evidence_decision_json = ? WHERE id = ?",
                (_json(decision), round_id),
            )

    def log_documents(
        self,
        *,
        round_id: int | None,
        stage: str,
        documents: Iterable[dict[str, Any]],
    ) -> None:
        if not self.enabled or round_id is None:
            return

        rows = []
        now = _utcnow()
        for item in documents:
            rows.append(
                (
                    round_id,
                    stage,
                    str(item.get("document_id") or "") or None,
                    str(item.get("title") or "") or None,
                    str(item.get("path") or "") or None,
                    str(item.get("source_url") or "") or None,
                    _safe_int(item.get("rank")),
                    _safe_int(item.get("rrf_rank")),
                    _safe_int(item.get("elasticsearch_rank")),
                    _safe_int(item.get("vector_rank")),
                    _safe_int(item.get("chunk_no")),
                    _safe_float(item.get("rrf_score")),
                    _safe_float(item.get("elasticsearch_score")),
                    _safe_float(item.get("vector_score")),
                    _safe_float(item.get("reranker_score")),
                    _safe_float(item.get("reranker_raw_score")),
                    str(item.get("document_date") or "") or None,
                    now,
                )
            )

        if not rows:
            return

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO retrieval_documents (
                    round_id, stage, document_id, title, path, source_url,
                    rank, rrf_rank, elasticsearch_rank, vector_rank, chunk_no,
                    rrf_score, elasticsearch_score, vector_score,
                    reranker_score, reranker_raw_score, document_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def finish_query(
        self,
        *,
        query_id: str,
        status: str,
        final_retrieval_query: str | None,
        answer_text: str | None = None,
    ) -> None:
        if not self.enabled:
            return

        stored_answer = answer_text if self.store_answer else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE research_queries
                   SET finished_at = ?, status = ?, final_retrieval_query = ?, answer_text = ?
                 WHERE id = ?
                """,
                (_utcnow(), status, final_retrieval_query, stored_answer, query_id),
            )
