import rag.search as search


class FakeResponse:
    is_error = False
    status_code = 200
    reason_phrase = "OK"
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_filename_lookup_uses_keyword_and_analyzed_fallback(monkeypatch):
    captured = {}

    def fake_post(endpoint, *, json, timeout):
        captured["body"] = json
        return FakeResponse({
            "hits": {
                "hits": [{
                    "_id": "files:123",
                    "_score": 1.0,
                    "_source": {
                        "title": "Ordner/Protokoll-Gesvers-braulab-09-04-20-final.pdf",
                        "attachment": {},
                    },
                }]
            }
        })

    monkeypatch.setattr(search, "_es_post", fake_post)
    results = search.strict_filename_lookup("Protokoll-Gesvers-braulab-09-04-20-final.pdf")
    assert [item["document_id"] for item in results] == ["files:123"]
    should = captured["body"]["query"]["bool"]["should"]
    assert any("title.keyword" in item.get("wildcard", {}) for item in should)
    assert any(item.get("match_phrase", {}).get("combined") for item in should)
    assert any(item.get("match", {}).get("combined") for item in should)
