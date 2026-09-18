import asyncio
import json

import rag.openai_provider as provider


def test_exhaustive_verifier_keeps_semantic_match_without_literal_plural(monkeypatch):
    async def fake_complete(*args, **kwargs):
        return json.dumps({
            "documents": [
                {"index": 1, "status": "match", "reason": "invoice evidence", "relation_binding": "direct", "evidence_frame": {"entities": [], "relations": [], "constraints": [], "concepts": [], "mentioned_entities": []}},
                {"index": 2, "status": "reject", "reason": "wrong year", "relation_binding": "contradicted", "evidence_frame": {"entities": [], "relations": [], "constraints": [], "concepts": [], "mentioned_entities": []}},
            ],
            "reason": "checked",
        })

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    results = [
        provider.SearchResult(
            index=1,
            title="RG-EX-2025-001.pdf",
            text=(
                "Nordstern GmbH ... Example Logistics GmbH ... "
                "10. September 2025 ... Rechnung EX-2025-001 ... Zahlungsbetrag 1.428,00"
            ),
            raw={"document_id": "files:66732"},
        ),
        provider.SearchResult(
            index=2,
            title="Alt.pdf",
            text="Nordstern GmbH ... Rechnung aus 2023",
            raw={"document_id": "files:1"},
        ),
    ]

    matches, uncertain, meta = asyncio.run(
        provider._verify_exhaustive_candidates(
            "Suche die Rechnungen der Nordstern GmbH an Example Logistics GmbH 2025",
            results,
        )
    )

    assert [item.title for item in matches] == ["RG-EX-2025-001.pdf"]
    assert uncertain == []
    assert meta["matches"] == 1
    assert results[0].raw["verification_status"] == "match"


def test_exhaustive_verifier_fails_closed_to_uncertain(monkeypatch):
    async def failing_complete(*args, **kwargs):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(provider, "_ollama_complete", failing_complete)
    results = [
        provider.SearchResult(index=1, title="x.pdf", text="some text", raw={})
    ]
    matches, uncertain, meta = asyncio.run(
        provider._verify_exhaustive_candidates("find invoices 2025", results)
    )
    assert matches == []
    assert len(uncertain) == 1
    assert meta["uncertain"] == 1
    assert "error" in meta
