from __future__ import annotations

import pytest

import rag.reranker as rr


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_tei_scores_are_mapped_by_index_not_response_order(monkeypatch):
    calls = []

    def fake_post(url, *, json, timeout):
        calls.append((url, json, timeout))
        # TEI may return ranks in score order rather than input order.
        return FakeResponse([
            {"index": 1, "score": 0.9},
            {"index": 0, "score": 0.1},
        ])

    monkeypatch.setattr(rr.httpx, "post", fake_post)
    r = rr.Reranker(backend="tei", tei_url="http://tei:80", tei_batch_size=32)
    monkeypatch.setattr(r, "_load_local", lambda: (_ for _ in ()).throw(AssertionError("local must not load")))

    scores = r.score("q", ["a", "b"])

    assert scores == [
        {"raw_score": None, "score": 0.1},
        {"raw_score": None, "score": 0.9},
    ]
    assert calls[0][0] == "http://tei:80/rerank"
    assert calls[0][1]["truncate"] is True
    assert calls[0][1]["raw_scores"] is False
    assert calls[0][1]["return_text"] is False


def test_tei_batches_without_losing_global_input_order(monkeypatch):
    seen = []

    def fake_post(url, *, json, timeout):
        seen.append(list(json["texts"]))
        return FakeResponse([
            {"index": idx, "score": float(text[-1]) / 10.0}
            for idx, text in enumerate(json["texts"])
        ])

    monkeypatch.setattr(rr.httpx, "post", fake_post)
    r = rr.Reranker(backend="tei", tei_url="http://tei", tei_batch_size=2)
    scores = r.score("q", ["t0", "t1", "t2", "t3", "t4"])

    assert seen == [["t0", "t1"], ["t2", "t3"], ["t4"]]
    assert [x["score"] for x in scores] == [0.0, 0.1, 0.2, 0.3, 0.4]


def test_tei_failure_does_not_silently_load_cpu_fallback(monkeypatch):
    r = rr.Reranker(
        backend="tei",
        tei_url="http://tei",
        fallback_backend="none",
    )
    monkeypatch.setattr(r, "_score_tei", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(r, "_score_local", lambda *a, **k: (_ for _ in ()).throw(AssertionError("local must not run")))

    with pytest.raises(RuntimeError, match="down"):
        r.score("q", ["a"])


def test_explicit_local_fallback_is_used(monkeypatch):
    r = rr.Reranker(
        backend="tei",
        tei_url="http://tei",
        fallback_backend="local",
    )
    monkeypatch.setattr(r, "_score_tei", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(r, "_score_local", lambda *a, **k: [{"raw_score": 1.0, "score": 0.8}])

    assert r.score("q", ["a"]) == [{"raw_score": 1.0, "score": 0.8}]


def test_tei_rerank_preserves_existing_downstream_contract(monkeypatch):
    r = rr.Reranker(backend="tei", tei_url="http://tei")
    monkeypatch.setattr(
        r,
        "score",
        lambda query, texts: [
            {"raw_score": None, "score": 0.2},
            {"raw_score": None, "score": 0.95},
        ],
    )
    results = [
        {"title": "a.pdf", "text": "A", "rrf": 0.9},
        {"title": "b.pdf", "text": "B", "rrf": 0.1},
    ]

    reranked = r.rerank("q", results, candidate_limit=2, top_k=2)

    assert [x["title"] for x in reranked] == ["b.pdf", "a.pdf"]
    assert reranked[0]["reranker_score"] == 0.95
    assert reranked[0]["reranker_raw_score"] is None
