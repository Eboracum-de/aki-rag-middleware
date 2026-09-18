import asyncio
import json
import re
from dataclasses import replace

import rag.openai_provider as provider


def test_review_context_prefers_enriched_document_body_over_highlighter_snippet():
    result = provider.SearchResult(
        index=1,
        title="RG-EX-2025-001.pdf",
        text=(
            "Dokumentanfang:\nNordstern GmbH ... Example Logistics GmbH ... "
            "10. September 2025 ... Bereitstellung Nextcloud ... Zahlungsbetrag 1.428,00"
        ),
        raw={
            "context_enriched": True,
            "es_snippet": "alter unvollständiger Highlight-Ausschnitt aus 2022",
            "vector_snippet": "anderer Chunk",
        },
    )
    context, included = provider._build_review_context([result])
    assert included == [result]
    assert "Bereitstellung Nextcloud" in context
    assert "10. September 2025" in context
    assert "alter unvollständiger Highlight-Ausschnitt" not in context


def test_exhaustive_verifier_batches_documents_and_keeps_global_indexes(monkeypatch):
    monkeypatch.setattr(
        provider,
        "RETRIEVAL_PLANNER",
        replace(provider.RETRIEVAL_PLANNER, verification_batch_size=2),
    )
    calls = []

    async def fake_complete(messages, **kwargs):
        prompt = messages[-1]["content"]
        indexes = [int(x) for x in re.findall(r"\[DOKUMENT (\d+)\]", prompt)]
        calls.append(indexes)
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
        for i in range(1, 6)
    ]
    matches, uncertain, meta = asyncio.run(
        provider._verify_exhaustive_candidates("find documents", results)
    )
    assert calls == [[1, 2], [3, 4], [5]]
    assert [r.title for r in matches] == ["d1.pdf"]
    assert uncertain == []
    assert meta["batch_size"] == 2
    assert meta["rejected"] == 4
