import types

import rag.graph_indexer as gi


def _bare_indexer():
    obj = object.__new__(gi.GraphEvidenceIndexer)
    obj.discovery_enabled = True
    obj.discovery_chunk_chars = 12000
    obj.discovery_overlap_chars = 600
    obj.discovery_max_chunks = 0
    obj.discovery_adaptive_split_min_chars = 3000
    obj.discovery_adaptive_split_max_depth = 2
    obj.discovery_max_entities_per_chunk = 40
    obj.relation_enabled = True
    obj.relation_chunk_chars = 12000
    obj.relation_overlap_chars = 600
    obj.relation_max_chunks = 0
    obj.relation_adaptive_split_min_chars = 3000
    obj.relation_adaptive_split_max_depth = 2
    obj.fuzzy_threshold = 92.0
    obj.fuzzy_max_candidates = 5
    return obj


def test_entity_discovery_splits_only_after_repeated_invalid_structured_output():
    idx = _bare_indexer()
    seen_lengths = []

    def fake_extract(self, chunk, *, title=""):
        seen_lengths.append(len(chunk))
        if len(chunk) > 5000:
            raise gi.StructuredOutputError(
                "invalid twice",
                stage="entity",
                first_done_reason="length",
                retry_done_reason="length",
                first_chars=3500,
                retry_chars=4000,
            )
        return {"entities": []}

    idx._llm_entity_extract = types.MethodType(fake_extract, idx)
    idx._validated_observations = types.MethodType(lambda self, payload, chunk: [], idx)

    observations, errors = idx.discover_entities("X" * 9000, title="dense.pdf")
    assert observations == []
    assert errors == []
    assert seen_lengths[0] == 9000
    assert any(length <= 5000 for length in seen_lengths[1:])


def test_entity_discovery_retries_invalid_json_once_before_success():
    idx = _bare_indexer()
    idx.discovery_prompt = "system"
    idx.discovery_num_predict = 100
    idx.discovery_num_ctx = 4096
    idx.discovery_think = False
    idx.discovery_timeout = 10

    class Backend:
        def __init__(self):
            self.calls = 0

        async def complete(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"content": '{"entities":[', "done_reason": "length"}
            return {"content": '{"entities":[]}', "done_reason": "stop"}

    backend = Backend()
    idx.discovery_backend = backend
    payload = idx._llm_entity_extract("Text", title="doc.pdf")
    assert payload == {"entities": []}
    assert backend.calls == 2


def test_relation_discovery_adaptive_split_after_structured_failure(monkeypatch):
    idx = _bare_indexer()
    seen_lengths = []

    candidates = [
        gi.MentionCandidate("e1", "PERSON", "Person", "Alice", "Alice", "name", 1.0, 1.0, 1.0),
        gi.MentionCandidate("e2", "ORGANIZATION", "Company", "Beta GmbH", "Beta GmbH", "name", 1.0, 1.0, 1.0),
    ]

    def fake_mentions(text, forms, **kwargs):
        return [
            gi.DetectedMention("Alice", "alice", "resolved_exact", candidates=[candidates[0]]),
            gi.DetectedMention("Beta GmbH", "beta gmbh", "resolved_exact", candidates=[candidates[1]]),
        ]

    monkeypatch.setattr(gi, "detect_document_mentions", fake_mentions)

    def fake_extract(self, chunk, *, title, allowed_entities):
        seen_lengths.append(len(chunk))
        if len(chunk) > 5000:
            raise gi.StructuredOutputError(
                "invalid twice",
                stage="relation",
                first_done_reason="length",
                retry_done_reason="length",
            )
        return {"relations": []}

    idx._llm_relation_extract = types.MethodType(fake_extract, idx)
    idx._validated_relations = types.MethodType(lambda self, payload, chunk, **kwargs: ([], []), idx)

    observations, diagnostics = idx.discover_relations("X" * 9000, forms=[], title="dense.pdf")
    assert observations == []
    assert any(item.get("kind") == "adaptive_split" for item in diagnostics)
    assert seen_lengths[0] == 9000
    assert any(length <= 5000 for length in seen_lengths[1:])
