from __future__ import annotations

from rag.graph import GraphStore


def test_finding_list_derives_graph_lite_states():
    store = object.__new__(GraphStore)
    rows = [
        {"finding_id": "f0", "entity_texts": [], "curated_entities": [], "suppressed_entity_texts": [], "claim_count": 0},
        {"finding_id": "f1", "entity_texts": ["A"], "curated_entities": [], "suppressed_entity_texts": [], "claim_count": 0},
        {"finding_id": "f2", "entity_texts": ["A", "B"], "curated_entities": [{"text": "A", "entity_id": "e1"}, {"text": "B", "entity_id": "e2"}], "suppressed_entity_texts": [], "claim_count": 0},
        {"finding_id": "f3", "entity_texts": ["A", "B"], "curated_entities": [{"text": "A", "entity_id": "e1"}, {"text": "B", "entity_id": "e2"}], "suppressed_entity_texts": [], "claim_count": 1},
        {"finding_id": "f4", "entity_texts": ["A"], "curated_entities": [], "suppressed_entity_texts": [], "claim_count": 0, "curator_status": "suppressed"},
    ]
    store._run = lambda query, **params: rows  # type: ignore[method-assign]
    result = store.list_research_findings()
    assert [row["graph_state"] for row in result] == ["no_entity", "open", "entities_resolved", "claimed", "suppressed"]


def test_finding_entity_options_separates_auto_curated_and_suppressed():
    store = object.__new__(GraphStore)
    store.research_finding_detail = lambda finding_id: {  # type: ignore[method-assign]
        "finding": {"entity_texts": ["RAW", "B280", "Noise"], "entity_roles": ["source", "target", ""] , "suppressed_entity_texts": ["Noise"]},
        "curated_entities": [{"text": "RAW", "entity_id": "e1", "display_name": "R.A.w. Capital"}],
        "resolved_entities": [{"text": "B280", "entity_id": "e2", "display_name": "Beispiel 280 VV UG"}],
    }
    store.find_entities = lambda text, limit=6: [{"entity_id": f"s-{text}", "display_name": text}]  # type: ignore[method-assign]
    result = store.research_finding_entity_options("f")
    assert result[0]["curated"]["entity_id"] == "e1"
    assert result[1]["auto_resolved"]["entity_id"] == "e2"
    assert result[2]["suppressed"] is True


def test_claim_preview_requires_language_neutral_predicate_and_curated_endpoints():
    store = object.__new__(GraphStore)
    calls = []

    def fake_run(query: str, **params):
        calls.append((query, params))
        return [{"document_id": "files:1", "subject_name": "A", "object_name": "B", "intent": "A relationship B"}]

    store._run = fake_run  # type: ignore[method-assign]
    preview = store.research_finding_claim_preview(
        "f1", subject_entity_id="e1", predicate_id="shareholder_of", object_entity_id="e2", predicate_label="ist Gesellschafter von"
    )
    assert preview["predicate_id"] == "shareholder_of"
    assert preview["subject"]["display_name"] == "A"
    assert preview["object"]["display_name"] == "B"
    assert calls


def test_claim_creation_stays_document_grounded_relation_observation():
    store = object.__new__(GraphStore)
    calls = []
    store.research_finding_claim_preview = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "finding_id": "f1", "document_id": "files:1", "relation_id": "r1",
        "subject": {"entity_id": "e1", "display_name": "A"},
        "predicate_id": "invoiced", "predicate_label": "stellte Rechnung an",
        "object": {"entity_id": "e2", "display_name": "B"}, "claim_text": "", "effect": "x", "note": "x",
    }
    store.research_finding_detail = lambda finding_id: {"finding": {"intent": "invoice query"}}  # type: ignore[method-assign]
    store._run = lambda query, **params: calls.append((query, params)) or []  # type: ignore[method-assign]
    result = store.create_research_finding_claim(
        "f1", subject_entity_id="e1", predicate_id="invoiced", object_entity_id="e2", predicate_label="stellte Rechnung an"
    )
    assert result["status"] == "claim_created"
    query = calls[-1][0]
    assert "RelationObservation" in query
    assert "DERIVED_FROM_FINDING" in query
    assert "HAS_RELATION_OBSERVATION" in query


def test_relink_restores_durable_research_finding_mention_even_without_extractor_mention():
    store = object.__new__(GraphStore)
    calls = []

    def fake_run(query: str, **params):
        calls.append((query, params))
        if "MATCH (o:EntityObservation {document_id:$document_id})" in query and "research_finding_entity" in query:
            return [{
                "observation_id": "o1",
                "curator_status": "research_finding_entity",
                "target_entity_id": "e1",
                "observed_text": "Beispiel GmbH",
                "normalized": "beispiel gmbh",
            }]
        return []

    store._run = fake_run  # type: ignore[method-assign]
    store.replace_document_mentions(document_id="files:1", mentions=[], content_hash="h", extractor="graph-v1")
    assert any("research_finding_curated=true" in query and params.get("entity_id") == "e1" for query, params in calls)


def test_relation_reindex_preserves_manual_research_finding_claims():
    store = object.__new__(GraphStore)
    calls = []
    store._run = lambda query, **params: calls.append((query, params)) or []  # type: ignore[method-assign]
    store.replace_document_relation_observations(document_id="files:1", observations=[], extractor="graph-v1")
    delete_query = calls[0][0]
    assert "curator_status" in delete_query
    assert "manual_claim" in delete_query
    assert "research_finding_curator" in delete_query


def test_entity_change_marks_manual_claim_for_review():
    store = object.__new__(GraphStore)
    calls = []
    store._run = lambda query, **params: calls.append((query, params)) or []  # type: ignore[method-assign]
    store._mark_research_finding_claims_for_review("f1", reason="finding_entity_reassigned")
    query, params = calls[0]
    assert "review_required" in query
    assert "DERIVED_FROM_FINDING" in query
    assert params["finding_id"] == "f1"


def test_bulk_no_entity_cleanup_suppresses_without_deleting_provenance():
    store = object.__new__(GraphStore)
    calls = []
    store._run = lambda query, **params: calls.append((query, params)) or [{"updated": 7}]  # type: ignore[method-assign]
    result = store.suppress_research_findings_without_entities()
    assert result["updated"] == 7
    query = calls[0][0]
    assert "size(coalesce(f.entity_texts,[])) = 0" in query
    assert "DETACH DELETE" not in query
    assert "curator_status='suppressed'" in query


def test_manual_claim_prefers_evidence_frame_over_query_intent():
    store = object.__new__(GraphStore)
    calls = []
    store.research_finding_claim_preview = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "finding_id": "f1", "document_id": "files:1", "relation_id": "r1",
        "subject": {"entity_id": "e1", "display_name": "A"},
        "predicate_id": "invoiced", "predicate_label": "stellte Rechnung an",
        "object": {"entity_id": "e2", "display_name": "B"}, "claim_text": "", "effect": "x", "note": "x",
    }
    store.research_finding_detail = lambda finding_id: {"finding": {  # type: ignore[method-assign]
        "intent": "search intent must not become evidence",
        "evidence_frame_json": '{"evidence":"invoice passage"}',
    }}
    store._run = lambda query, **params: calls.append((query, params)) or []  # type: ignore[method-assign]
    store.create_research_finding_claim(
        "f1", subject_entity_id="e1", predicate_id="invoiced", object_entity_id="e2"
    )
    assert calls[-1][1]["evidence_text"] == '{"evidence":"invoice passage"}'


def test_admin_findings_javascript_is_external_and_csp_allows_only_self_scripts():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    findings = (root / "rag/templates/admin/findings.html").read_text()
    entity = (root / "rag/templates/admin/entity.html").read_text()
    base = (root / "rag/templates/admin/base.html").read_text()
    admin_ui = (root / "rag/admin_ui.py").read_text()
    admin_js = (root / "rag/static/admin/admin.js").read_text()

    assert "<script>" not in findings
    assert "onsubmit=" not in findings
    assert "onsubmit=" not in entity
    assert "admin_js" in base
    assert "script-src 'self'" in admin_ui
    assert "script-src 'none'" not in admin_ui
    assert '.bulk-toggle' in admin_js
    assert 'input[name="finding_id"]' in admin_js
    assert "confirm-submit" in admin_js


def test_admin_js_asset_is_registered_and_backed_by_static_file():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    admin_ui = (root / "rag/admin_ui.py").read_text()
    assert 'JS_FILE = HERE / "static" / "admin" / "admin.js"' in admin_ui
    assert '@router.get("/assets/admin.js"' in admin_ui
    assert (root / "rag/static/admin/admin.js").is_file()
