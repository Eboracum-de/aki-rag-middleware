import sys
import types


# The neutral build container intentionally lacks the optional Neo4j driver.
# Stub only the import surface needed to unit-test the pure retrieval shaping.
if "neo4j" not in sys.modules:
    neo4j_stub = types.ModuleType("neo4j")
    neo4j_stub.GraphDatabase = object()
    sys.modules["neo4j"] = neo4j_stub

from rag.graph import GraphStore


def test_two_hop_chain_is_document_grounded_and_never_direct_relation():
    store = object.__new__(GraphStore)

    chain_row = {
        "document1": {"document_id": "files:101", "title": "hop-a-c.pdf"},
        "document2": {"document_id": "files:202", "title": "hop-c-b.pdf"},
        "query_entity_a_id": "A",
        "query_entity_a_name": "Alpha",
        "query_entity_b_id": "B",
        "query_entity_b_name": "Beta",
        "bridge_entity_id": "C",
        "bridge_entity_name": "Bridge GmbH",
        "hop1": {
            "relation_id": "r1",
            "subject_entity_id": "A",
            "subject_display_name": "Alpha",
            "predicate": "WORKS_WITH",
            "predicate_text": "arbeitet mit",
            "object_entity_id": "C",
            "object_display_name": "Bridge GmbH",
            "evidence_text": "Alpha arbeitet mit Bridge GmbH zusammen.",
            "confidence": 0.95,
            "stance": "asserted",
        },
        "hop2": {
            "relation_id": "r2",
            "subject_entity_id": "C",
            "subject_display_name": "Bridge GmbH",
            "predicate": "SUPPLIES",
            "predicate_text": "liefert an",
            "object_entity_id": "B",
            "object_display_name": "Beta",
            "evidence_text": "Bridge GmbH liefert an Beta.",
            "confidence": 0.90,
            "stance": "asserted",
        },
    }

    def fake_run(query, **params):
        if "type(r) IN $relation_types" in query:
            return []
        if "HAS_RELATION_OBSERVATION]->(c:RelationObservation)" in query:
            return []
        if "MATCH (d:Document)-[m:MENTIONS]->(e:Entity)" in query:
            return []
        if "HAS_RELATION_OBSERVATION]->(r1:RelationObservation)" in query:
            return [chain_row]
        raise AssertionError(f"unexpected Cypher in test: {query[:100]!r}")

    store._run = fake_run
    payload = store.retrieve_documents_for_entities(["A", "B"], limit=10)

    assert payload["mode"] == "indirect_relation_chain"
    assert payload["direct_relations"] == []
    assert len(payload["indirect_relation_chains"]) == 1
    chain = payload["indirect_relation_chains"][0]
    assert chain["direct_relation"] is False
    assert chain["query_entity_a_id"] == "A"
    assert chain["bridge_entity_id"] == "C"
    assert chain["query_entity_b_id"] == "B"
    assert chain["hop1"]["evidence_text"]
    assert chain["hop2"]["evidence_text"]

    docs = {item["document_id"]: item for item in payload["documents"]}
    assert set(docs) == {"files:101", "files:202"}
    assert docs["files:101"]["graph_reason"] == "indirect_relation_chain"
    assert docs["files:202"]["graph_reason"] == "indirect_relation_chain"
    assert docs["files:101"]["graph_relation_evidence"] == [
        "Alpha arbeitet mit Bridge GmbH zusammen."
    ]
    assert docs["files:202"]["graph_relation_evidence"] == [
        "Bridge GmbH liefert an Beta."
    ]
