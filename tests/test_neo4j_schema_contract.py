from __future__ import annotations

import inspect
from pathlib import Path
import re

from rag.graph import (
    GraphStore,
    NEO4J_SCHEMA_CONSTRAINTS,
    NEO4J_SCHEMA_INDEXES,
)


def _schema_name(statement: str) -> str:
    match = re.search(r"CREATE (?:CONSTRAINT|INDEX) ([a-z0-9_]+) IF NOT EXISTS", statement)
    assert match, statement
    return match.group(1)


class SchemaSimulator:
    def __init__(self, existing: set[str] | None = None):
        self.objects = set(existing or set())
        self.queries: list[tuple[str, dict]] = []

    def __call__(self, query: str, **params):
        self.queries.append((query, params))
        if query.startswith(("CREATE CONSTRAINT", "CREATE INDEX")):
            self.objects.add(_schema_name(query))
        return []


def test_schema_contract_has_unique_idempotent_objects():
    statements = NEO4J_SCHEMA_CONSTRAINTS + NEO4J_SCHEMA_INDEXES
    names = [_schema_name(statement) for statement in statements]
    assert len(names) == len(set(names))
    assert all(" IF NOT EXISTS " in statement for statement in statements)
    assert {
        "entity_id",
        "document_id",
        "entity_observation_id",
        "relation_observation_id",
        "research_finding_id",
        "research_run_id",
        "canonical_user_id",
    }.issubset(names)
    assert {
        "entity_observation_document",
        "entity_observation_curator_status",
        "relation_observation_curator_status",
        "research_finding_curation_hash",
    }.issubset(names)


def test_runtime_schema_objects_are_named_in_the_canonical_reference():
    documentation = (
        Path(__file__).resolve().parents[1] / "docs" / "NEO4J-SCHEMA.md"
    ).read_text()
    for statement in NEO4J_SCHEMA_CONSTRAINTS + NEO4J_SCHEMA_INDEXES:
        assert f"`{_schema_name(statement)}`" in documentation


def test_fresh_partial_and_repeated_schema_initialization_are_safe():
    expected = {_schema_name(x) for x in NEO4J_SCHEMA_CONSTRAINTS + NEO4J_SCHEMA_INDEXES}
    preexisting = {"entity_id", "document_id", "research_finding_id"}
    simulator = SchemaSimulator(preexisting)
    graph = object.__new__(GraphStore)
    graph._run = simulator  # type: ignore[method-assign]

    graph.ensure_schema()
    assert simulator.objects == expected
    first_count = len(simulator.queries)

    graph.ensure_schema()
    assert simulator.objects == expected
    assert len(simulator.queries) == first_count * 2
    assert not any("RAGSchemaMarker" in query for query, _ in simulator.queries)


def test_upgrade_queries_do_not_overwrite_existing_manual_state():
    simulator = SchemaSimulator()
    graph = object.__new__(GraphStore)
    graph._run = simulator  # type: ignore[method-assign]
    graph.ensure_schema()

    historic = next(query for query, _ in simulator.queries if "historic_observation_backfill" in query)
    assert "MERGE (d:EntityFormDecision" in historic
    assert "ON CREATE SET" in historic
    assert "ON MATCH SET" not in historic

    entity_kind = next(query for query, _ in simulator.queries if "SET e.entity_kind" in query)
    assert "WHERE properties(e)['entity_kind'] IS NULL" in entity_kind


def test_optional_property_reads_are_warning_safe_and_no_dummy_tokens_remain():
    source = inspect.getsource(GraphStore)
    assert "RAGSchemaMarker" not in source
    assert "properties(c)['relation_text'] AS relation_text" in source
    assert "properties(c)['predicate_text'] AS predicate_text" in source
    assert "properties(r)['mention_count'] AS mention_count" in source
    assert "coalesce(properties(r)['method'],'')" in source
    assert "coalesce(properties(e)['identity_status'],'')" in source
    assert "c.relation_text AS relation_text" not in source
    assert "r.mention_count AS mention_count" not in source
    assert "coalesce(r.method,'')" not in source


def test_optional_relationship_reads_do_not_require_preexisting_type_tokens():
    """Sparse/legacy graphs must not warn merely because an optional relation never existed."""
    guarded_methods = {
        GraphStore.backfill_manual_confirmations: {"MERGED_INTO"},
        GraphStore.backfill_form_policies: {"HAS_NAME", "HAS_SEARCH_ALIAS"},
        GraphStore.entity_forms: {"HAS_NAME", "HAS_SEARCH_ALIAS"},
        GraphStore.name_forms: {"HAS_NAME", "HAS_SEARCH_ALIAS"},
        GraphStore.find_entities: {
            "HAS_NAME", "HAS_SEARCH_ALIAS", "MERGED_INTO", "MENTIONS", "RESOLVED_TO"
        },
        GraphStore.list_merges: {"MERGED_INTO"},
        GraphStore.entity_relation_observations: {"SUBJECT", "OBJECT", "HAS_RELATION_OBSERVATION"},
        GraphStore.list_relation_observations: {"SUBJECT", "OBJECT", "HAS_RELATION_OBSERVATION"},
        GraphStore.entity_observations: {"HAS_ENTITY_OBSERVATION"},
        GraphStore.list_observations: {"HAS_ENTITY_OBSERVATION"},
        GraphStore._observation_curation_summary: {"HAS_ENTITY_OBSERVATION"},
        GraphStore.entity_detail: {"MERGED_INTO"},
        GraphStore.list_merge_candidates: {"POSSIBLE_SAME_AS", "SAME_AS", "NOT_SAME_AS", "DESCRIBES"},
        GraphStore.stats: {
            "MENTIONS", "MENTIONS_NAME", "REPLIES_TO", "REPRESENTS_MAIL",
            "ATTACHMENT_OF", "NOT_SAME_AS",
        },
    }
    for method, relationship_types in guarded_methods.items():
        source = inspect.getsource(method)
        for relationship_type in relationship_types:
            assert f":{relationship_type}" not in source
            assert f"'{relationship_type}'" in source


def test_research_schema_subset_is_also_idempotent():
    simulator = SchemaSimulator({"research_finding_id"})
    graph = object.__new__(GraphStore)
    graph._run = simulator  # type: ignore[method-assign]

    graph.ensure_research_finding_schema()
    first = set(simulator.objects)
    graph.ensure_research_finding_schema()

    expected_research = {
        "research_finding_id",
        "research_run_id",
        "canonical_user_id",
        "research_finding_frame_hash",
        "research_finding_curation_hash",
        "research_finding_provenance",
        "research_run_user",
        "research_run_status",
    }
    assert first == expected_research
    assert simulator.objects == expected_research
