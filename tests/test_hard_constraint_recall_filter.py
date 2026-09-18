from types import SimpleNamespace

import rag.search as search


class _Response:
    def __init__(self, ids):
        self._ids = ids

    def raise_for_status(self):
        return None

    def json(self):
        return {"hits": {"hits": [{"_id": value} for value in self._ids]}}


def test_year_filter_removes_other_years_before_rrf(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs["json"])
        return _Response(["files:2025a", "files:2025b"])

    monkeypatch.setattr(search, "_es_post", fake_post)
    rankings = [
        ("probe", [
            {"document_id": "files:2024", "title": "RG-2024.pdf"},
            {"document_id": "files:2025a", "title": "RG-2025-01.pdf"},
            {"document_id": "files:2025b", "title": "RG-2025-02.pdf"},
        ])
    ]

    filtered, stats = search._filter_probe_rankings_by_hard_constraints(
        "Rechnungen von examplehost aus dem Jahr 2025", rankings
    )

    assert [item["document_id"] for item in filtered[0][1]] == ["files:2025a", "files:2025b"]
    assert stats["applied"] is True
    must = captured["query"]["bool"]["must"]
    assert any(clause.get("multi_match", {}).get("query") == "2025" for clause in must)


def test_hard_constraint_filter_fails_open_when_elasticsearch_audit_fails(monkeypatch):
    def fake_post(*args, **kwargs):
        raise RuntimeError("temporary ES error")

    monkeypatch.setattr(search, "_es_post", fake_post)
    rankings = [("probe", [{"document_id": "files:1", "title": "x"}])]
    filtered, stats = search._filter_probe_rankings_by_hard_constraints(
        "Rechnungen 2025", rankings
    )
    assert filtered == rankings
    assert stats["applied"] is False
    assert "error" in stats
