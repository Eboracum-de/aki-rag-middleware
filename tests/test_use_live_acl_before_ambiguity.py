import asyncio

from starlette.requests import Request

import rag.api as api
from rag.acl import AclDecision


def _request(user_id="frontend-user"):
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/documents/resolve",
        "headers": [(b"x-rag-user-id", user_id.encode("latin1"))],
    })


def _item(document_id, path):
    filename = path.rsplit("/", 1)[-1]
    return {
        "document_id": document_id,
        "title": path,
        "path": "/" + path.lstrip("/"),
        "filename": filename,
        "source_url": f"https://cloud.example/{document_id}",
    }


def test_use_filename_applies_live_acl_before_ambiguity(monkeypatch):
    reference = "Protokoll-Gesvers-braulab-09-04-20-final.pdf"
    stale_a = _item("files:101", "Altlasten/A/" + reference)
    stale_b = _item("files:102", "Altlasten/B/" + reference)
    current = _item("files:777", "Gesellschaft/Protokolle/" + reference)

    monkeypatch.setattr(api.graph_queue, "mark_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api,
        "document_reference_candidates",
        lambda value, limit=50: [stale_a, stale_b, current] if value == reference else [],
    )

    def fake_authorize(results, *, rag_user_id=None):
        visible = [item for item in results if item.get("document_id") == "files:777"]
        return AclDecision(True, visible, len(results), len(visible))

    monkeypatch.setattr(api.live_acl, "authorize", fake_authorize)

    def fake_hydrate(refs, *, question=""):
        assert refs == ["files:777"]
        hydrated = dict(current)
        hydrated["context_text"] = "Dokumentinhalt"
        return {
            "references": list(refs),
            "results": [hydrated],
            "ambiguous": [],
            "not_found": [],
            "resolved_count": 1,
        }

    monkeypatch.setattr(api, "resolve_document_references", fake_hydrate)

    result = asyncio.run(api.documents_resolve(
        api.DocumentResolveRequest(query="Analysiere", references=[reference]),
        _request(),
    ))

    assert result["ambiguous"] == []
    assert result["not_found"] == []
    assert result["resolved_count"] == 1
    assert result["results"][0]["document_id"] == "files:777"


def test_use_filename_reports_only_acl_visible_ambiguity(monkeypatch):
    reference = "Bericht.pdf"
    denied = _item("files:1", "Altlasten/" + reference)
    visible_a = _item("files:2", "A/" + reference)
    visible_b = _item("files:3", "B/" + reference)

    monkeypatch.setattr(api.graph_queue, "mark_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api,
        "document_reference_candidates",
        lambda value, limit=50: [denied, visible_a, visible_b],
    )

    def fake_authorize(results, *, rag_user_id=None):
        visible = [item for item in results if item.get("document_id") in {"files:2", "files:3"}]
        return AclDecision(True, visible, len(results), len(visible))

    monkeypatch.setattr(api.live_acl, "authorize", fake_authorize)
    monkeypatch.setattr(
        api,
        "resolve_document_references",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ambiguous refs must not hydrate")),
    )

    result = asyncio.run(api.documents_resolve(
        api.DocumentResolveRequest(query="Vergleiche", references=[reference]),
        _request(),
    ))

    assert result["resolved_count"] == 0
    assert result["not_found"] == []
    assert len(result["ambiguous"]) == 1
    paths = {entry["path"] for entry in result["ambiguous"][0]["matches"]}
    assert paths == {"/A/Bericht.pdf", "/B/Bericht.pdf"}
