import asyncio
import json

import rag.openai_provider as provider


def test_after_web_query_normalization_deduplicates_and_caps(monkeypatch):
    monkeypatch.setattr(provider, "WEB_AFTER_MAX_QUERIES", 3)
    value = {
        "queries": [
            "Cornelius Muster Berlin",
            " cornelius   muster berlin ",
            '"Cornelius Muster" "R.A.W. Capital GmbH"',
            '"Cornelius Muster" "Musterhof 280 VV UG"',
            "ignored fourth query",
        ]
    }
    queries = provider._normalize_after_web_queries(value, "fallback")
    assert queries == [
        "Cornelius Muster Berlin",
        '"Cornelius Muster" "R.A.W. Capital GmbH"',
        '"Cornelius Muster" "Musterhof 280 VV UG"',
    ]


def test_after_web_query_derivation_sees_internal_evidence_and_uses_closed_schema(monkeypatch):
    captured = {}

    async def fake_complete(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return json.dumps({
            "queries": [
                "Cornelius Muster Rechtsanwaltsgesellschaft mbH & Co. KG Berlin",
                '"Cornelius Muster" "R.A.W. Capital GmbH"',
            ]
        })

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    queries = asyncio.run(provider._derive_after_web_queries(
        instruction="Nutze das erste Dokument und suche anschliessend im Web nach weiteren Informationen",
        question="Analysiere und suche dann im Web nach erkannten Sachverhalten",
        initial_web_query="weitere Informationen",
        internal_context=(
            "[1] DATEI: Schreiben.pdf\n"
            "Cornelius Muster Rechtsanwaltsgesellschaft mbH & Co. KG vertritt die R.A.W. Capital GmbH."
        ),
    ))
    assert queries[0].startswith("Cornelius Muster Rechtsanwaltsgesellschaft")
    assert captured["kwargs"]["response_format"] is provider.WEB_AFTER_QUERY_RESPONSE_SCHEMA
    prompt = captured["messages"][1]["content"]
    assert "Cornelius Muster Rechtsanwaltsgesellschaft" in prompt
    assert "erkannten Sachverhalten" in prompt


def test_web_search_many_merges_queries_and_deduplicates_urls(monkeypatch):
    async def fake_search(query, user_id, request_id=None):
        if "first" in query:
            return {
                "enabled": True,
                "searched": 5,
                "fetched": 2,
                "archive_run_path": "Webarchiv/run1",
                "sources": [
                    {"title": "A", "final_url": "https://a.example", "evidence_text": "A"},
                    {"title": "Shared", "final_url": "https://shared.example", "evidence_text": "S"},
                ],
            }
        return {
            "enabled": True,
            "searched": 4,
            "fetched": 2,
            "archive_run_path": "Webarchiv/run2",
            "sources": [
                {"title": "Shared again", "final_url": "https://shared.example", "evidence_text": "S2"},
                {"title": "B", "final_url": "https://b.example", "evidence_text": "B"},
            ],
        }

    monkeypatch.setattr(provider, "_web_search", fake_search)
    payload = asyncio.run(provider._web_search_many(["first query", "second query"], "u", "r"))
    assert payload["queries"] == ["first query", "second query"]
    assert payload["searched"] == 9
    assert payload["fetched"] == 4
    assert payload["archive_run_paths"] == ["Webarchiv/run1", "Webarchiv/run2"]
    assert [s["final_url"] for s in payload["sources"]] == [
        "https://a.example", "https://shared.example", "https://b.example"
    ]


def test_hybrid_prompt_does_not_treat_missing_web_evidence_as_fiction():
    prompt = provider.HYBRID_WEB_ANSWER_SYSTEM_PROMPT
    assert "KEIN Beleg" in prompt
    assert "fiktiv" in prompt
    assert "Loese den Konflikt nicht spekulativ" in prompt


def test_web_search_many_preserves_disabled_state(monkeypatch):
    async def fake_search(query, user_id, request_id=None):
        return {"enabled": False, "sources": [], "searched": 0, "fetched": 0}

    monkeypatch.setattr(provider, "_web_search", fake_search)
    payload = asyncio.run(provider._web_search_many(["one", "two"], "u", "r"))
    assert payload["enabled"] is False
    assert payload["sources"] == []
