from rag.graph import GraphStore


def test_entity_kind_backfill_is_idempotent_without_schema_markers():
    store = object.__new__(GraphStore)
    calls = []

    def fake_run(query, **params):
        calls.append((query, params))
        if "RETURN count(e) AS updated" in query:
            return [{"updated": 3}]
        return []

    store._run = fake_run
    assert store.ensure_entity_kind_schema() == 3

    rendered = "\n".join(query for query, _ in calls)
    assert "RAGSchemaMarker" not in rendered
    assert "m.entity_kind=''" not in rendered
    assert "properties(e)['entity_kind'] IS NULL" in rendered
    assert "CASE WHEN e:Person THEN 'Person' ELSE '' END" in rendered


def test_carddav_created_entities_always_write_entity_kind():
    store = object.__new__(GraphStore)
    calls = []

    store._existing_entity_for_contact = lambda contact_id: None
    store._entities_by_email = lambda normalized, entity_type: []
    store._entities_by_phone = lambda normalized, entity_type: []
    store._entities_by_identity_key = lambda identity_key, entity_type: []
    store._entities_by_exact_name = lambda normalized, entity_type: []

    def fake_run(query, **params):
        calls.append((query, params))
        return []

    store._run = fake_run

    person_id, reason = store.resolve_or_create_entity(
        contact_id="c-person",
        entity_type="Person",
        display_name="Max Mustermann",
        names=[{"value": "Max Mustermann"}],
        emails=[],
        phones=[],
    )
    assert person_id
    assert reason == "created"
    person_create = next((q, p) for q, p in calls if "CREATE (e:Entity:Person" in q)
    assert "entity_kind:$entity_kind" in person_create[0]
    assert person_create[1]["entity_kind"] == "Person"

    calls.clear()
    org_id, reason = store.resolve_or_create_entity(
        contact_id="c-org",
        entity_type="Organization",
        display_name="Beispiel Organisation",
        names=[{"value": "Beispiel Organisation"}],
        emails=[],
        phones=[],
    )
    assert org_id
    assert reason == "created"
    org_create = next((q, p) for q, p in calls if "CREATE (e:Entity:Organization" in q)
    assert "entity_kind:$entity_kind" in org_create[0]
    assert org_create[1]["entity_kind"] == ""
