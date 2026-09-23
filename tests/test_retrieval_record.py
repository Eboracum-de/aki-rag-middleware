import asyncio
import json
from pathlib import Path

import rag.openai_provider as provider
from rag.retrieval_planner import load_retrieval_planner_settings, normalize_query_frame


def _empty_evidence():
    return {"entities": [], "relations": [], "constraints": [], "concepts": [], "mentioned_entities": []}


def test_normal_candidate_limit_can_be_smaller_than_ten():
    settings = load_retrieval_planner_settings({
        "retrieval_planner": {
            "verification_candidate_limit": 4,
            "exhaustive_verification_candidate_limit": 30,
        }
    }, env={})
    assert settings.verification_candidate_limit == 4
    assert settings.exhaustive_verification_candidate_limit == 30


def test_query_frame_is_generic_and_relations_reference_known_entities():
    frame = normalize_query_frame({
        "intent": "find evidence",
        "entities": [
            {"id": "q1", "text": "Nordstern GmbH", "role": "source"},
            {"id": "q2", "text": "Example Logistics GmbH", "role": "target"},
        ],
        "relations": [
            {"source": "q1", "predicate": "stellt Rechnung an", "target": "q2"},
            {"source": "missing", "predicate": "ignored", "target": "q2"},
        ],
        "constraints": [{"kind": "time", "value": "2025"}],
        "concepts": ["Rechnung", "Rechnung"],
    })
    assert frame["relations"] == [
        {"source": "q1", "predicate": "stellt Rechnung an", "target": "q2"}
    ]
    assert frame["concepts"] == ["Rechnung"]


def test_candidate_verifier_stores_evidence_frame(monkeypatch):
    async def fake_complete(*args, **kwargs):
        return json.dumps({
            "documents": [{
                "index": 1,
                "status": "match",
                "reason": "direct evidence",
                "relation_binding": "direct",
                "evidence_frame": {
                    "entities": [
                        {"id": "d1", "text": "Nordstern GmbH", "role": "source"},
                        {"id": "d2", "text": "Example Logistics GmbH", "role": "target"},
                    ],
                    "relations": [
                        {"source": "d1", "predicate": "stellt Rechnung an", "target": "d2"}
                    ],
                    "constraints": [{"kind": "year", "value": "2025", "status": "match"}],
                    "concepts": ["Rechnung"],
                    "mentioned_entities": [],
                },
            }],
            "reason": "checked",
        })

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    result = provider.SearchResult(
        index=1,
        title="RG-EX-2025-001.odt",
        text="Nordstern GmbH Rechnung an Example Logistics GmbH 2025",
        raw={"document_id": "files:66732"},
    )
    frame = {
        "intent": "find evidence",
        "entities": [
            {"id": "q1", "text": "Nordstern GmbH", "role": "source"},
            {"id": "q2", "text": "Example Logistics GmbH", "role": "target"},
        ],
        "relations": [{"source": "q1", "predicate": "stellt Rechnung an", "target": "q2"}],
        "constraints": [{"kind": "year", "value": "2025"}],
        "concepts": ["Rechnung"],
    }
    matches, uncertain, meta = asyncio.run(provider._verify_exhaustive_candidates(
        "Suche die Rechnungen der Nordstern GmbH an Example Logistics GmbH 2025",
        [result],
        query_frame=frame,
        candidate_limit=1,
    ))
    assert [r.title for r in matches] == ["RG-EX-2025-001.odt"]
    assert uncertain == []
    assert meta["reviewed_documents"][0]["evidence_frame"]["relations"][0]["predicate"] == "stellt Rechnung an"


def test_retrieval_record_archive_is_atomic_and_contains_no_document_body(monkeypatch, tmp_path):
    monkeypatch.setattr(provider, "RETRIEVAL_RECORD_ENABLED", True)
    monkeypatch.setattr(provider, "RETRIEVAL_RECORD_DIRECTORY", tmp_path)
    record = {
        "schema_version": 1,
        "query_id": "chatcmpl-test",
        "query": {"original": "Telemall", "normalized": "Telemall"},
        "query_frame": normalize_query_frame({}),
        "documents": [{"document_id": "files:1", "title": "x.pdf", "status": "reject"}],
    }
    provider._write_retrieval_record(record)
    files = list(tmp_path.rglob("chatcmpl-test.json"))
    assert len(files) == 1
    stored = json.loads(files[0].read_text(encoding="utf-8"))
    assert stored["query"]["original"] == "Telemall"
    assert "text" not in stored["documents"][0]


def test_raw_documents_allowlists_research_log_metadata():
    result = provider.SearchResult(
        index=3,
        title="visible.pdf",
        text="ANSWER CONTEXT MUST NOT BE LOGGED",
        raw={
            "document_id": "files:42",
            "title": "visible.pdf",
            "path": "Documents/visible.pdf",
            "source_url": "https://nc.example/open/42",
            "es_rank": 2,
            "es_score": 0.75,
            "rrf": 0.125,
            "vector_rank": 4,
            "vector_score": 0.5,
            "reranker_score": 0.9,
            "document_date": "2026-09-22",
            "text": "SECRET RAW TEXT",
            "chunk": "SECRET RAW CHUNK",
            "context_text": "SECRET CONTEXT",
            "private_payload": {"body": "SECRET OBJECT"},
        },
    )

    document = provider._raw_documents([result])[0]

    assert document["document_id"] == "files:42"
    assert document["rank"] == 3
    assert document["elasticsearch_rank"] == 2
    assert document["elasticsearch_score"] == 0.75
    assert document["rrf_score"] == 0.125
    assert set(document) == {
        "document_id", "title", "path", "source_url", "rank", "rrf_rank",
        "elasticsearch_rank", "vector_rank", "chunk_no", "rrf_score",
        "elasticsearch_score", "vector_score", "reranker_score",
        "reranker_raw_score", "document_date",
    }
    assert all("SECRET" not in str(value) for value in document.values())
