from types import SimpleNamespace

import rag.search as search


def test_broad_entity_guard_stops_before_vector_rerank(monkeypatch):
    entity_context = {
        "enabled": True,
        "entities": [{
            "status": "resolved",
            "entity_id": "person-1",
            "mention": "Frank Muster",
            "display_name": "Frank Muster",
        }],
        "elastic_phrase_expansion": [],
        "error": None,
    }
    monkeypatch.setattr(search, "prepare_entity_context", lambda question: entity_context)
    monkeypatch.setattr(search, "create_plan", lambda *a, **k: SimpleNamespace())

    def fake_es(question, plan, diagnostics):
        diagnostics.update({"total_hits": search.ES_LIMIT + 400, "total_relation": "eq"})
        return [{"document_id": f"files:{i}", "score": 1.0, "title": f"d{i}.pdf"} for i in range(search.ES_LIMIT)]

    monkeypatch.setattr(search, "elastic_search", fake_es)

    def fake_graph(entity_ctx, diagnostics):
        diagnostics.update({"enabled": True, "available": True, "mode": "single_entity_documents", "count": 2})
        return [
            {"document_id": "files:9001", "title": "a.pdf", "path": "/a.pdf"},
            {"document_id": "files:9002", "title": "b.pdf", "path": "/b.pdf"},
        ]

    monkeypatch.setattr(search, "graph_search", fake_graph)
    monkeypatch.setattr(search, "vector_search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("vector search must not run")))
    monkeypatch.setattr(search, "rerank_results", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reranker must not run")))

    result = search.perform_search("Frank Muster", limit=8)

    assert result["retrieval_mode"] == "too_unspecific"
    assert result["results"] == []
    assert [x["document_id"] for x in result["orientation_candidates"]] == ["files:9001", "files:9002"]
    assert result["timings"]["embedding"] == 0.0
    assert result["timings"]["qdrant"] == 0.0


def test_specific_entity_query_keeps_normal_pipeline(monkeypatch):
    entity_context = {
        "enabled": True,
        "entities": [{
            "status": "resolved",
            "entity_id": "person-1",
            "mention": "Frank Muster",
            "display_name": "Frank Muster",
        }],
        "elastic_phrase_expansion": [],
        "error": None,
    }
    assert search.is_broad_entity_query("Frank Muster Musterhof", entity_context) is False
