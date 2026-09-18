from rag.embeddings import EmbeddingBackend, build_embedding_backend_from_config
from rag.sync import build_index_signature, embed_chunks_resilient


class CaptureEmbedding(EmbeddingBackend):
    kind = "capture"

    def __post_init__(self):
        super().__post_init__()
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(i), 1.0] for i, _ in enumerate(texts)]


def test_explicit_prefixes_are_model_agnostic():
    backend = build_embedding_backend_from_config({
        "embedding": {
            "backend": "ollama",
            "url": "http://127.0.0.1:11434",
            "model": "future-embedding-model",
            "profile": "custom",
            "document_prefix": "passage: ",
            "query_prefix": "query: ",
        }
    })
    assert backend.profile == "custom"
    assert backend.document_prefix == "passage: "
    assert backend.query_prefix == "query: "


def test_auto_profile_no_longer_sniffs_model_name():
    for model in ("qwen3-embedding:4b", "nomic-embed-text", "unknown-model"):
        backend = build_embedding_backend_from_config({
            "embedding": {
                "backend": "ollama",
                "url": "http://127.0.0.1:11434",
                "model": model,
                "profile": "auto",
            }
        })
        assert backend.profile == "auto"
        assert backend.document_prefix == ""
        assert backend.query_prefix == ""


def test_profile_label_never_selects_behavior():
    for label in ("nomic_search", "qwen3_retrieval", "anything-else"):
        backend = build_embedding_backend_from_config({
            "embedding": {
                "backend": "ollama",
                "url": "http://127.0.0.1:11434",
                "model": "arbitrary-model-name",
                "profile": label,
            }
        })
        assert backend.profile == label
        assert backend.document_prefix == ""
        assert backend.query_prefix == ""


def test_document_and_query_roles_prefix_only_embedding_input():
    backend = CaptureEmbedding(
        "http://unused",
        "any-model",
        profile="custom",
        document_prefix="passage: ",
        query_prefix="query: ",
    )
    backend.embed_documents(["Dokumenttext"])
    backend.embed_query("Welche Funktion hatte Muster?")
    assert backend.calls == [
        ["passage: Dokumenttext"],
        ["query: Welche Funktion hatte Muster?"],
    ]


def test_resilient_sync_uses_document_role_but_returns_raw_chunk():
    backend = CaptureEmbedding(
        "http://unused",
        "any-model",
        profile="custom",
        document_prefix="passage: ",
        query_prefix="query: ",
    )
    result = embed_chunks_resilient(
        backend,
        ["Unveraenderter Payload-Text"],
        batch_size=8,
        document_id="files:1",
        title="test.pdf",
        overlap=400,
    )
    assert backend.calls == [["passage: Unveraenderter Payload-Text"]]
    assert result[0][0] == "Unveraenderter Payload-Text"


def test_index_signature_depends_on_document_input_not_profile_label():
    base = dict(
        embedding_backend="ollama",
        embedding_model="any-model",
        chunk_size=3000,
        chunk_overlap=400,
    )
    label_a = build_index_signature(
        **base,
        embedding_profile="one-label",
        embedding_document_prefix="passage: ",
    )
    label_b = build_index_signature(
        **base,
        embedding_profile="another-label",
        embedding_document_prefix="passage: ",
    )
    changed_document_input = build_index_signature(
        **base,
        embedding_profile="another-label",
        embedding_document_prefix="document: ",
    )
    assert label_a == label_b
    assert label_a != changed_document_input


def test_embedding_only_reindex_does_not_require_graph_discovery():
    from rag.sync import graph_reindex_needed
    existing_state = ("same-digest", 4, "doc.pdf", "old-signature")
    assert graph_reindex_needed(existing_state, content_unchanged=True) is False
    assert graph_reindex_needed(existing_state, content_unchanged=False) is True
    assert graph_reindex_needed(None, content_unchanged=False) is True
