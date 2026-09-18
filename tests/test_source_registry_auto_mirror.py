from __future__ import annotations

import rag.source_registry as source_registry


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _reset_auto_state():
    source_registry._AUTO_MIRROR_STAMP = None
    source_registry._AUTO_MIRROR_MISSING = 0
    source_registry._AUTO_MIRROR_LAST_ATTEMPT = 0.0


def test_auto_mirror_repairs_registered_origins_before_retrieval(tmp_path, monkeypatch):
    db = tmp_path / "source_registry.sqlite"
    registry = source_registry.SourceRegistry(db)
    registry.set("files:1", "web_archive", source_path="Webarchiv/a.txt", classification_source="test")
    registry.set("files:2", "mail_archive", source_path="Mail/a/mail.txt", classification_source="test")
    registry.close()

    monkeypatch.setattr(source_registry, "registry_path", lambda: db)
    monkeypatch.setattr(
        source_registry,
        "_config",
        lambda: {"elasticsearch": {"url": "http://es:9200", "index": "my_index"}},
    )

    def fake_post(url, **kwargs):
        assert url == "http://es:9200/my_index/_search"
        assert set(kwargs["json"]["query"]["ids"]["values"]) == {"files:1", "files:2"}
        return _Response({
            "hits": {"hits": [
                {"_id": "files:1", "_source": {}},
                {"_id": "files:2", "_source": {"source_origin": "mail_archive"}},
            ]}
        })

    monkeypatch.setattr(source_registry.requests, "post", fake_post)
    updates = []

    def fake_bulk(es_url, index, rows, options):
        updates.extend(rows)
        return len(rows)

    monkeypatch.setattr(source_registry, "_bulk_update", fake_bulk)
    _reset_auto_state()

    result = source_registry.auto_mirror_registry_to_elasticsearch()
    assert result == {"checked": 2, "updated": 1, "missing": 0}
    assert updates == [("files:1", "web_archive")]

    # Unchanged registry + no pending missing ids: the hot path is a no-op.
    assert source_registry.auto_mirror_registry_to_elasticsearch() == {
        "checked": 0, "updated": 0, "missing": 0
    }


def test_auto_mirror_retries_documents_not_yet_indexed(tmp_path, monkeypatch):
    db = tmp_path / "source_registry.sqlite"
    registry = source_registry.SourceRegistry(db)
    registry.set("files:9", "chat_archive", source_path="AKI-Chats/x.html", classification_source="test")
    registry.close()

    monkeypatch.setattr(source_registry, "registry_path", lambda: db)
    monkeypatch.setattr(
        source_registry,
        "_config",
        lambda: {"elasticsearch": {"url": "http://es:9200", "index": "my_index"}},
    )
    monkeypatch.setattr(source_registry, "_bulk_update", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        source_registry.requests,
        "post",
        lambda *args, **kwargs: _Response({"hits": {"hits": []}}),
    )
    _reset_auto_state()

    first = source_registry.auto_mirror_registry_to_elasticsearch(retry_seconds=999)
    assert first == {"checked": 1, "updated": 0, "missing": 1}
    # Pending id is retained but immediate repeated queries are throttled.
    second = source_registry.auto_mirror_registry_to_elasticsearch(retry_seconds=999)
    assert second == {"checked": 0, "updated": 0, "missing": 1}
