import asyncio
import json
import rag.openai_provider as provider


def test_verifier_rejects_reference_only_false_positive(monkeypatch):
    async def fake_complete(*args, **kwargs):
        return json.dumps({
            "documents": [
                {
                    "index": 1,
                    "status": "match",
                    "reason": "issuer Nordstern, recipient DL, invoice 2025",
                    "relation_binding": "direct",
                },
                {
                    "index": 2,
                    "status": "match",
                    "reason": "DL invoice number is mentioned, but recipient is Doris Muster",
                    "relation_binding": "reference_only",
                },
            ],
            "reason": "checked",
        })

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    results = [
        provider.SearchResult(
            index=1,
            title="RG-EX-2025-001.odt",
            text=(
                "Nordstern GmbH\nExample Logistics GmbH\n"
                "Rechnung EX-2025-001\n10. September 2025\n"
                "Bereitstellung Nextcloud"
            ),
            raw={"document_id": "files:66732"},
        ),
        provider.SearchResult(
            index=2,
            title="RG-SAG-2025-001.pdf",
            text=(
                "Nordstern GmbH\nDoris Muster\nRechnung RG-SAG-2025-001\n"
                "2025\nReferenz zum Vorgang RG-EX-2025-001 / Example Logistics GmbH"
            ),
            raw={"document_id": "files:66800"},
        ),
    ]

    matches, uncertain, meta = asyncio.run(
        provider._verify_exhaustive_candidates(
            "Suche die Rechnungen der Nordstern GmbH an Example Logistics GmbH 2025",
            results,
        )
    )

    assert [item.title for item in matches] == ["RG-EX-2025-001.odt"]
    assert uncertain == []
    assert meta["matches"] == 1
    assert meta["rejected"] == 1
    assert results[1].raw["verification_status"] == "reject"
    assert results[1].raw["verification_relation_binding"] == "reference_only"
    assert "nur referenziert" in results[1].raw["verification_reason"]


def test_match_with_unclear_role_binding_is_downgraded_to_uncertain(monkeypatch):
    async def fake_complete(*args, **kwargs):
        return json.dumps({
            "documents": [
                {
                    "index": 1,
                    "status": "match",
                    "reason": "all names occur but OCR layout is ambiguous",
                    "relation_binding": "unclear",
                }
            ],
            "reason": "checked",
        })

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    result = provider.SearchResult(
        index=1,
        title="scan.pdf",
        text="Nordstern GmbH Example Logistics GmbH Rechnung 2025",
        raw={},
    )

    matches, uncertain, meta = asyncio.run(
        provider._verify_exhaustive_candidates(
            "Suche Rechnungen der Nordstern GmbH an Example Logistics GmbH 2025",
            [result],
        )
    )

    assert matches == []
    assert [item.title for item in uncertain] == ["scan.pdf"]
    assert meta["uncertain"] == 1
    assert result.raw["verification_status"] == "uncertain"


def test_non_relational_match_uses_direct_binding(monkeypatch):
    async def fake_complete(*args, **kwargs):
        return json.dumps({
            "documents": [
                {
                    "index": 1,
                    "status": "match",
                    "reason": "document concerns requested year",
                    "relation_binding": "direct",
                }
            ],
            "reason": "checked",
        })

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    result = provider.SearchResult(
        index=1,
        title="Jahresbericht-2025.pdf",
        text="Jahresbericht 2025",
        raw={},
    )

    matches, uncertain, meta = asyncio.run(
        provider._verify_exhaustive_candidates("Suche Dokumente aus 2025", [result])
    )

    assert [item.title for item in matches] == ["Jahresbericht-2025.pdf"]
    assert uncertain == []
    assert meta["matches"] == 1


def test_verifier_schema_requires_relation_binding():
    item_schema = provider.EXHAUSTIVE_VERIFY_RESPONSE_SCHEMA["properties"]["documents"]["items"]
    assert "relation_binding" in item_schema["required"]
    assert set(item_schema["properties"]["relation_binding"]["enum"]) == {
        "direct", "reference_only", "contradicted", "unclear"
    }
