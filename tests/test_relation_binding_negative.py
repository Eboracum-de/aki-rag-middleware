import asyncio
import json
import rag.openai_provider as provider


def _run(monkeypatch, relation_binding, status="match", reason="checked", question=None, title="doc.pdf", text="2025"):
    async def fake_complete(*args, **kwargs):
        return json.dumps({
            "documents": [{
                "index": 1,
                "status": status,
                "reason": reason,
                "relation_binding": relation_binding,
            }],
            "reason": "checked",
        })
    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    result = provider.SearchResult(index=1, title=title, text=text, raw={})
    matches, uncertain, meta = asyncio.run(provider._verify_exhaustive_candidates(
        question or "Suche Dokumente aus 2025", [result]
    ))
    return result, matches, uncertain, meta


def test_direct_match_stays_match(monkeypatch):
    result, matches, uncertain, meta = _run(
        monkeypatch,
        "direct",
        question="Suche die Rechnungen der Nordstern GmbH an Example Logistics GmbH 2025",
        title="RG-EX-2025-001.odt",
        text="Nordstern GmbH\nExample Logistics GmbH\nRechnung EX-2025-001\n2025",
    )
    assert [r.title for r in matches] == ["RG-EX-2025-001.odt"]
    assert uncertain == []
    assert result.raw["verification_status"] == "match"


def test_reference_only_claimed_match_is_rejected(monkeypatch):
    result, matches, uncertain, meta = _run(
        monkeypatch,
        "reference_only",
        reason="document is to Doris Muster and only references RG-EX-2025-001",
        question="Suche die Rechnungen der Nordstern GmbH an Example Logistics GmbH 2025",
        title="RG-SAG-2025-001.pdf",
        text="Nordstern GmbH\nDoris Muster\n2025\nReferenz RG-EX-2025-001 Example Logistics GmbH",
    )
    assert matches == [] and uncertain == []
    assert meta["rejected"] == 1
    assert result.raw["verification_status"] == "reject"


def test_contradicted_claimed_match_is_rejected(monkeypatch):
    result, matches, uncertain, meta = _run(
        monkeypatch,
        "contradicted",
        reason="recipient is Doris Muster, not Muster Leasing",
        question="Suche die Rechnungen der Nordstern GmbH an Example Logistics GmbH 2025",
        title="RG-SAG-2025-001.pdf",
        text="Nordstern GmbH\nDoris Muster\nRechnung 2025\nExample Logistics GmbH nur als Referenz",
    )
    assert matches == [] and uncertain == []
    assert meta["rejected"] == 1
    assert result.raw["verification_status"] == "reject"
    assert "widersprechende" in result.raw["verification_reason"]


def test_unclear_claimed_match_becomes_uncertain(monkeypatch):
    result, matches, uncertain, meta = _run(monkeypatch, "unclear")
    assert matches == []
    assert [r.title for r in uncertain] == ["doc.pdf"]
    assert result.raw["verification_status"] == "uncertain"


def test_old_not_applicable_fails_closed_if_plain_json_backend_emits_it(monkeypatch):
    result, matches, uncertain, meta = _run(monkeypatch, "not_applicable")
    assert matches == []
    assert [r.title for r in uncertain] == ["doc.pdf"]
    assert result.raw["verification_status"] == "uncertain"
    assert result.raw["verification_relation_binding"] == "unclear"


def test_non_relational_direct_match_is_supported(monkeypatch):
    result, matches, uncertain, meta = _run(
        monkeypatch,
        "direct",
        question="Suche Dokumente aus 2025",
        title="Jahresbericht-2025.pdf",
        text="Jahresbericht 2025",
    )
    assert [r.title for r in matches] == ["Jahresbericht-2025.pdf"]
    assert uncertain == []


def test_schema_has_no_not_applicable_escape_hatch():
    item = provider.EXHAUSTIVE_VERIFY_RESPONSE_SCHEMA["properties"]["documents"]["items"]
    assert set(item["properties"]["relation_binding"]["enum"]) == {
        "direct", "reference_only", "contradicted", "unclear"
    }
