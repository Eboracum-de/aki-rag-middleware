import asyncio
import json
from dataclasses import replace

import httpx
import rag.openai_provider as provider


def _http_400():
    request = httpx.Request("POST", "http://ollama/api/chat")
    response = httpx.Response(400, request=request, text='{"error":"unsupported format"}')
    return httpx.HTTPStatusError("400", request=request, response=response)


def test_candidate_verifier_downgrades_schema_once_and_reuses_json(monkeypatch):
    monkeypatch.setattr(
        provider,
        "RETRIEVAL_PLANNER",
        replace(provider.RETRIEVAL_PLANNER, verification_batch_size=2),
    )
    calls = []

    async def fake_complete(messages, **kwargs):
        calls.append((kwargs.get("response_format"), kwargs.get("think")))
        # Reject only the schema-object request. Plain JSON is accepted.
        if isinstance(kwargs.get("response_format"), dict):
            raise _http_400()
        prompt = messages[-1]["content"]
        import re
        indexes = [int(x) for x in re.findall(r"\[DOKUMENT (\d+)\]", prompt)]
        return json.dumps({
            "documents": [
                {"index": i, "status": "match" if i == 1 else "reject", "reason": "test", "relation_binding": "direct" if i == 1 else "contradicted", "evidence_frame": {"entities": [], "relations": [], "constraints": [], "concepts": [], "mentioned_entities": []}}
                for i in indexes
            ],
            "reason": "checked",
        })

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    results = [
        provider.SearchResult(index=i, title=f"d{i}.pdf", text=f"document {i}", raw={})
        for i in range(1, 5)
    ]
    matches, uncertain, meta = asyncio.run(
        provider._verify_exhaustive_candidates("find documents", results)
    )

    # First batch: schema rejected, then JSON. Second batch: JSON directly.
    assert [type(fmt).__name__ if fmt is not None else None for fmt, _ in calls] == ["dict", "str", "str"]
    assert all(think is False for _, think in calls)
    assert meta["format_mode"] == "json"
    assert meta["batch_errors"] == []
    assert [r.title for r in matches] == ["d1.pdf"]
    assert uncertain == []


def test_candidate_verifier_can_fall_back_to_prompt_only_json(monkeypatch):
    monkeypatch.setattr(
        provider,
        "RETRIEVAL_PLANNER",
        replace(provider.RETRIEVAL_PLANNER, verification_batch_size=2),
    )
    formats = []

    async def fake_complete(messages, **kwargs):
        fmt = kwargs.get("response_format")
        formats.append(fmt)
        if fmt is not None:
            raise _http_400()
        return json.dumps({
            "documents": [
                {"index": 1, "status": "match", "reason": "test", "relation_binding": "direct", "evidence_frame": {"entities": [], "relations": [], "constraints": [], "concepts": [], "mentioned_entities": []}},
                {"index": 2, "status": "reject", "reason": "test", "relation_binding": "contradicted", "evidence_frame": {"entities": [], "relations": [], "constraints": [], "concepts": [], "mentioned_entities": []}},
            ],
            "reason": "checked",
        })

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    results = [
        provider.SearchResult(index=i, title=f"d{i}.pdf", text=f"document {i}", raw={})
        for i in range(1, 3)
    ]
    matches, uncertain, meta = asyncio.run(
        provider._verify_exhaustive_candidates("find documents", results)
    )
    assert isinstance(formats[0], dict)
    assert formats[1] == "json"
    assert formats[2] is None
    assert meta["format_mode"] == "prompt"
    assert [r.title for r in matches] == ["d1.pdf"]
    assert uncertain == []
