import sys
from types import SimpleNamespace

import yaml

import rag.sync as sync


class DummyEmbeddingBackend:
    kind = "dummy"
    model = "dummy-model"
    profile = "plain"
    document_prefix = ""

    def embed(self, texts):
        return [[float(len(text)), 0.25] for text in texts]


def _response(status=200, text='{"status":"ok"}'):
    return SimpleNamespace(status_code=status, ok=200 <= status < 300, text=text)


def _hit(doc_id="files:1", title="Docs/test.txt", content="abcdefghij"):
    return {
        "_id": doc_id,
        "_source": {
            "title": title,
            "content": content,
            "hash": f"hash-{content}",
            "attachment": {"content_type": "text/plain"},
        },
    }


def _config(tmp_path, **sync_overrides):
    data = {
        "embedding": {"backend": "ollama", "model": "dummy"},
        "qdrant": {"url": "http://qdrant", "collection": "test"},
        "sync": {
            "state_db": str(tmp_path / "state.sqlite"),
            "chunk_size": 5,
            "chunk_overlap": 0,
            "embedding_batch_size": 2,
            "max_documents": 0,
            "graph_queue": {"enabled": False},
        },
    }
    data["sync"].update(sync_overrides)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_explicit_chunk_delete_uses_point_ids_not_filter(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _response()

    monkeypatch.setattr(sync.requests, "post", fake_post)
    deleted = sync.qdrant_delete_chunk_range(
        "http://qdrant", "test", "files:42", 2, 5, batch_size=2
    )

    assert deleted == 3
    assert len(calls) == 2
    payloads = [call[1]["json"] for call in calls]
    assert all("points" in payload for payload in payloads)
    assert all("filter" not in payload for payload in payloads)
    assert payloads[0]["points"] == [
        sync.point_id("files:42", 2),
        sync.point_id("files:42", 3),
    ]
    assert payloads[1]["points"] == [sync.point_id("files:42", 4)]


def test_new_document_upserts_without_delete(monkeypatch, tmp_path):
    cfg_path = _config(tmp_path)
    hit = _hit(content="abcdefghij")  # two 5-char chunks
    events = []

    monkeypatch.setattr(sync, "es_scroll", lambda *a, **k: iter([hit]))
    monkeypatch.setattr(sync, "build_embedding_backend_from_config", lambda cfg: DummyEmbeddingBackend())
    monkeypatch.setattr(sync, "ensure_qdrant_collection", lambda *a, **k: events.append(("ensure",)))
    monkeypatch.setattr(sync, "qdrant_upsert", lambda *a, **k: events.append(("upsert", a[2])))
    monkeypatch.setattr(sync, "qdrant_delete_chunk_range", lambda *a, **k: events.append(("delete", a[3], a[4])))
    monkeypatch.setattr(sys, "argv", ["sync", "--config", str(cfg_path), "--max-documents", "0"])

    assert sync.main() == 0
    assert [event[0] for event in events].count("upsert") == 1
    assert not any(event[0] == "delete" for event in events)


def test_shrinking_document_upserts_first_then_deletes_only_tail(monkeypatch, tmp_path):
    cfg_path = _config(tmp_path)

    # Seed committed state with four old chunks and a different content hash.
    state = sync.StateDB(str(tmp_path / "state.sqlite"))
    state.put("files:1", "old-hash", 4, "Docs/test.txt", "old-signature")
    state.close()

    hit = _hit(content="abcdefghi")  # chunk_size=5 -> two chunks
    events = []

    monkeypatch.setattr(sync, "es_scroll", lambda *a, **k: iter([hit]))
    monkeypatch.setattr(sync, "build_embedding_backend_from_config", lambda cfg: DummyEmbeddingBackend())
    monkeypatch.setattr(sync, "ensure_qdrant_collection", lambda *a, **k: None)
    monkeypatch.setattr(sync, "qdrant_upsert", lambda *a, **k: events.append(("upsert",)))
    monkeypatch.setattr(
        sync,
        "qdrant_delete_chunk_range",
        lambda _url, _collection, doc, start, end, **kwargs: events.append(("delete", doc, start, end)),
    )
    monkeypatch.setattr(sys, "argv", ["sync", "--config", str(cfg_path), "--max-documents", "0"])

    assert sync.main() == 0
    assert events[0][0] == "upsert"
    assert events[-1] == ("delete", "files:1", 2, 4)


def test_stale_document_deletes_committed_ids(monkeypatch, tmp_path):
    cfg_path = _config(tmp_path)
    state = sync.StateDB(str(tmp_path / "state.sqlite"))
    state.put("files:9", "hash", 3, "Old/deleted.txt", "sig")
    state.close()

    deleted = []
    monkeypatch.setattr(sync, "es_scroll", lambda *a, **k: iter([]))
    monkeypatch.setattr(sync, "build_embedding_backend_from_config", lambda cfg: DummyEmbeddingBackend())
    monkeypatch.setattr(
        sync,
        "qdrant_delete_chunk_range",
        lambda _url, _collection, doc, start, end, **kwargs: deleted.append((doc, start, end)),
    )
    monkeypatch.setattr(sys, "argv", ["sync", "--config", str(cfg_path), "--max-documents", "0"])

    assert sync.main() == 0
    assert deleted == [("files:9", 0, 3)]
    state = sync.StateDB(str(tmp_path / "state.sqlite"))
    assert state.get("files:9") is None
    state.close()
