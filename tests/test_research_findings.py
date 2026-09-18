from __future__ import annotations

from rag.graph import GraphStore
from rag.research_findings import (
    PROVENANCE_LABEL,
    canonical_query_frame,
    finding_id,
    query_frame_hash,
    query_frame_has_structure,
)


def _frame_a():
    return {
        "intent": "find invoices",
        "entities": [
            {"id": "e1", "text": "Eboracum GmbH", "role": "issuer"},
            {"id": "e2", "text": "Muster Leasing GmbH", "role": "recipient"},
        ],
        "relations": [
            {"source": "e1", "predicate": "invoice to", "target": "e2"},
        ],
        "constraints": [{"kind": "year", "value": "2025"}],
        "concepts": ["Rechnung"],
    }


def _frame_same_semantics_other_ids():
    return {
        "intent": "find invoices",
        "entities": [
            {"id": "z9", "text": "Muster Leasing GmbH", "role": "recipient"},
            {"id": "x4", "text": "Eboracum GmbH", "role": "issuer"},
        ],
        "relations": [
            {"source": "x4", "predicate": "invoice to", "target": "z9"},
        ],
        "constraints": [{"value": "2025", "kind": "year"}],
        "concepts": ["Rechnung"],
    }


def test_query_frame_hash_ignores_local_entity_ids_and_order():
    assert canonical_query_frame(_frame_a()) == canonical_query_frame(_frame_same_semantics_other_ids())
    assert query_frame_hash(_frame_a()) == query_frame_hash(_frame_same_semantics_other_ids())
    assert finding_id("files:66732", _frame_a()) == finding_id(
        "files:66732", _frame_same_semantics_other_ids()
    )


def test_query_frame_requires_reusable_structure():
    assert query_frame_has_structure(_frame_a()) is True
    assert query_frame_has_structure({"intent": "find documents"}) is False


def test_store_research_findings_persists_only_positive_direct_matches():
    store = object.__new__(GraphStore)
    calls: list[tuple[str, dict]] = []

    def fake_run(query: str, **params):
        calls.append((query, params))
        if "RETURN DISTINCT e.entity_id AS entity_id" in query:
            normalized = params.get("normalized")
            if normalized == "eboracum gmbh":
                return [{"entity_id": "org-eb", "display_name": "Eboracum GmbH", "labels": ["Entity", "Organization"]}]
            if normalized == "muster leasing gmbh":
                return [{"entity_id": "org-ex", "display_name": "Muster Leasing GmbH", "labels": ["Entity", "Organization"]}]
            return []
        return []

    store._run = fake_run  # type: ignore[method-assign]

    result = store.store_research_findings(
        query_id="q-test",
        query_frame=_frame_a(),
        documents=[
            {
                "document_id": "files:66732",
                "title": "RG-EX-2025-001.pdf",
                "verification_status": "match",
                "relation_binding": "direct",
                "evidence_frame": {
                    "constraints": [{"kind": "year", "value": "2025", "status": "match"}],
                },
            },
            {
                "document_id": "files:old",
                "title": "Old.pdf",
                "verification_status": "reject",
                "relation_binding": "direct",
            },
            {
                "document_id": "files:unclear",
                "title": "Unclear.pdf",
                "verification_status": "match",
                "relation_binding": "unclear",
            },
        ],
        software_version="0.8.3-rc11",
        planner_model="planner",
        verifier_model="verifier",
    )

    assert result["stored"] == 1
    assert result["skipped"] == 2
    assert result["provenance"] == PROVENANCE_LABEL
    assert result["resolved_query_entities"] == 2

    write_calls = [params for query, params in calls if "MERGE (f:ResearchFinding:AKIResearchFinding" in query]
    assert len(write_calls) == 1
    assert len(write_calls[0]["rows"]) == 1
    assert write_calls[0]["rows"][0]["document_id"] == "files:66732"
    assert write_calls[0]["provenance_label"] == "AKI Recherche"
    assert write_calls[0]["query_id"] == "q-test"
    assert "user_query" not in write_calls[0]

    entity_links = [params for query, params in calls if "MERGE (f)-[r:QUERY_ENTITY" in query]
    assert len(entity_links) == 1
    assert {item["entity_id"] for item in entity_links[0]["links"]} == {"org-eb", "org-ex"}
