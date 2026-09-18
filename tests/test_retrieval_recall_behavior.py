import asyncio
import json
from dataclasses import replace

import rag.openai_provider as provider


def _result(index: int, title: str, text: str) -> provider.SearchResult:
    return provider.SearchResult(
        index=index,
        title=title,
        text=text,
        raw={"document_id": f"files:{index}", "context_enriched": True},
    )


def test_initial_planner_budget_is_additional_to_deterministic_arm_views(monkeypatch):
    original = provider.RETRIEVAL_PLANNER
    monkeypatch.setattr(
        provider,
        "RETRIEVAL_PLANNER",
        replace(original, thinking=False, max_queries_per_round=3, model=""),
    )
    monkeypatch.setattr(provider, "ANSWER_MODEL", "qwen3:8b")

    async def fake_complete(*args, **kwargs):
        assert kwargs["model"] == "qwen3:8b"
        return json.dumps({
            "stop": False,
            "reason": "expand",
            "exhaustive": True,
            "probes": [
                {"kind": "lexical", "query": "Nordstern Lombard 2025"},
                {"kind": "semantic", "query": "invoice Nordstern Lombard 2025"},
                {"kind": "lexical", "query": "DL Nordstern 2025"},
            ],
        })

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    value = asyncio.run(provider._retrieval_planner_decision(
        question="Suche Rechnungen Nordstern DL 2025",
        round_no=1,
        results=[],
        seen_probe_queries=["Suche Rechnungen Nordstern DL 2025"],
        retrieval_arms={"files", "vector", "graph"},
        initial=True,
        initial_probe_count=3,
    ))
    assert len(value["probes"]) == 3


def test_followup_planner_does_not_use_thinking(monkeypatch):
    original = provider.RETRIEVAL_PLANNER
    monkeypatch.setattr(provider, "RETRIEVAL_PLANNER", replace(original, thinking=True, model="qwen3:8b"))
    seen = []

    async def fake_complete(*args, **kwargs):
        seen.append(kwargs.get("think"))
        return json.dumps({"stop": True, "reason": "enough", "exhaustive": False, "probes": []})

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    asyncio.run(provider._retrieval_planner_decision(
        question="Frage",
        round_no=2,
        results=[],
        seen_probe_queries=["Frage"],
        retrieval_arms={"files", "vector", "graph"},
        initial=False,
    ))
    assert seen == [False]


def test_initial_planner_retries_without_thinking_on_empty_content(monkeypatch):
    original = provider.RETRIEVAL_PLANNER
    monkeypatch.setattr(provider, "RETRIEVAL_PLANNER", replace(original, thinking=True, model="qwen3:8b"))
    seen = []

    async def fake_complete(*args, **kwargs):
        seen.append(kwargs.get("think"))
        if len(seen) == 1:
            return ""
        return json.dumps({"stop": True, "reason": "retry ok", "exhaustive": False, "probes": []})

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    value = asyncio.run(provider._retrieval_planner_decision(
        question="Frage",
        round_no=1,
        results=[],
        seen_probe_queries=["Frage"],
        retrieval_arms={"files", "vector", "graph"},
        initial=True,
        initial_probe_count=3,
    ))
    assert value["reason"] == "retry ok"
    assert seen == [True, False]


def test_explicit_year_audit_downgrades_unproven_match(monkeypatch):
    async def fake_complete(*args, **kwargs):
        return json.dumps({
            "documents": [
                {"index": 1, "status": "match", "reason": "fits", "relation_binding": "direct", "evidence_frame": {"entities": [], "relations": [], "constraints": [], "concepts": [], "mentioned_entities": []}},
                {"index": 2, "status": "match", "reason": "too broad", "relation_binding": "direct", "evidence_frame": {"entities": [], "relations": [], "constraints": [], "concepts": [], "mentioned_entities": []}},
            ],
            "reason": "checked",
        })

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    results = [
        _result(1, "RG-EX-2025-001.odt", "10. September 2025 Rechnung EX-2025-001"),
        _result(2, "Auslagenabrechnung-2020.odt", "Auslagenabrechnung vom 6. Januar 2020"),
    ]
    matches, uncertain, meta = asyncio.run(provider._verify_exhaustive_candidates(
        "Suche die Rechnungen Nordstern an DL 2025", results
    ))
    assert [r.index for r in matches] == [1]
    assert [r.index for r in uncertain] == [2]
    assert results[1].raw["verification_status"] == "uncertain"
    assert "2025" in results[1].raw["verification_reason"]


def test_citation_repair_appends_only_selected_source_markers(monkeypatch):
    async def fake_complete(*args, **kwargs):
        return json.dumps({"indexes": [1], "reason": "source 1 supports the answer"})

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    results = [
        _result(1, "RG-EX-2025-001.odt", "Rechnung 2025 Betrag 1428 EUR"),
        _result(2, "Alt.odt", "Rechnung 2023"),
    ]
    repaired, selected = asyncio.run(provider._repair_missing_citations(
        "Die Rechnung beträgt 1.428 EUR.", results, question="Welche Rechnung 2025?"
    ))
    assert repaired.endswith("Belege: [1]")
    assert [r.index for r in selected] == [1]
    assert provider._cited_numbers(repaired, results) == {1}
