from __future__ import annotations

import pytest

import rag.openai_provider as provider


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"enabled": True, "stored": 1}


class _Client:
    payload = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json):
        _Client.payload = json
        return _Response()


@pytest.mark.asyncio
async def test_research_finding_scope_guard_accepts_selected_mailarchive(monkeypatch):
    monkeypatch.setattr(provider, "RESEARCH_FINDINGS_ENABLED", True)
    monkeypatch.setattr(provider.httpx, "AsyncClient", _Client)
    result = provider.SearchResult(
        index=1,
        title="message.html",
        text="Ariane Seeger",
        raw={
            "document_id": "files:1",
            "source_origin": "mail_archive",
            "verification_status": "match",
            "verification_relation_binding": "direct",
            "verification_evidence_frame": {},
        },
    )

    await provider._store_positive_research_findings(
        query_id="q1",
        query_frame={
            "intent": "find person",
            "entities": [{"id": "e1", "text": "Ariane Seeger", "role": "person"}],
            "relations": [],
            "constraints": [],
            "concepts": [],
        },
        results=[result],
        source_scopes={"documents", "mailarchive"},
    )

    assert _Client.payload is not None
    assert _Client.payload["source_scopes"] == ["documents", "mailarchive"]
    assert _Client.payload["documents"][0]["source_origin"] == "mail_archive"


@pytest.mark.asyncio
async def test_research_finding_scope_guard_rejects_unselected_chatarchive(monkeypatch):
    monkeypatch.setattr(provider, "RESEARCH_FINDINGS_ENABLED", True)
    _Client.payload = None
    monkeypatch.setattr(provider.httpx, "AsyncClient", _Client)
    result = provider.SearchResult(
        index=1,
        title="old-chat.md",
        text="Ariane Seeger",
        raw={
            "document_id": "files:2",
            "source_origin": "chat_archive",
            "verification_status": "match",
            "verification_relation_binding": "direct",
            "verification_evidence_frame": {},
        },
    )

    await provider._store_positive_research_findings(
        query_id="q2",
        query_frame={
            "intent": "find person",
            "entities": [{"id": "e1", "text": "Ariane Seeger", "role": "person"}],
            "relations": [],
            "constraints": [],
            "concepts": [],
        },
        results=[result],
        source_scopes={"documents", "mailarchive"},
    )

    assert _Client.payload is None
