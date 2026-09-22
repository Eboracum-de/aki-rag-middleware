from rag.config_check import check_config


def messages(cfg):
    return [(issue.level, issue.message) for issue in check_config(cfg)]


def test_rejects_no_document_retrieval_arm():
    found = messages({"elasticsearch": {"enabled": False}, "qdrant": {"enabled": False}, "reranker": {"backend": "none"}})
    assert any(level == "error" and "no document retrieval arm" in message for level, message in found)


def test_hybrid_without_reranker_is_warning_not_error():
    cfg = {
        "elasticsearch": {"enabled": True},
        "qdrant": {"enabled": True},
        "embedding": {"backend": "ollama", "model": "qwen3-embedding:4b"},
        "reranker": {"backend": "none"},
    }
    found = messages(cfg)
    assert any(level == "warning" and "supported via RRF" in message for level, message in found)
    assert not any(level == "error" for level, _ in found)


def test_super_light_profile_is_consistent():
    cfg = {
        "deployment": {"profile": "super-light", "mode": "dockerized"},
        "elasticsearch": {"enabled": True},
        "qdrant": {"enabled": False},
        "reranker": {"backend": "none"},
        "sync_worker": {"enabled": False},
        "graph_retrieval": {"enabled": False},
        "graph_indexer": {"enabled": False},
        "graph_entity_discovery": {"enabled": False},
        "graph_relation_discovery": {"enabled": False},
    }
    assert messages(cfg) == []


def test_super_light_rejects_accidental_heavy_components():
    cfg = {
        "deployment": {"profile": "super-light", "mode": "dockerized"},
        "elasticsearch": {"enabled": True},
        "qdrant": {"enabled": True},
        "embedding": {"backend": "ollama", "model": "x"},
        "reranker": {"backend": "local"},
    }
    found = messages(cfg)
    assert any(level == "error" and "qdrant.enabled=false" in message for level, message in found)
    assert any(level == "error" and "reranker.backend=none" in message for level, message in found)


def test_tei_requires_url():
    found = messages({
        "elasticsearch": {"enabled": True},
        "qdrant": {"enabled": False},
        "reranker": {"backend": "tei", "tei_url": ""},
    })
    assert any(level == "error" and "requires reranker.tei_url" in message for level, message in found)


def test_research_findings_without_neo4j_is_warning():
    found = messages({
        "elasticsearch": {"enabled": True},
        "qdrant": {"enabled": False},
        "reranker": {"backend": "none"},
        "neo4j": {"enabled": False},
        "research_findings": {"enabled": True},
    })
    assert any(level == "warning" and "will not be persisted" in message for level, message in found)


def test_required_policy_arm_must_have_enabled_capability():
    found = messages({
        "elasticsearch": {"enabled": True},
        "qdrant": {"enabled": False},
        "neo4j": {"enabled": False},
        "reranker": {"backend": "none"},
        "retrieval_policy": {
            "internal": {"files": "required", "vector": "required", "graph": "disabled"}
        },
    })
    assert any(level == "error" and "requires vector" in message for level, message in found)


def test_policy_may_disable_installed_optional_capability():
    found = messages({
        "elasticsearch": {"enabled": True},
        "qdrant": {"enabled": True},
        "embedding": {"backend": "ollama", "model": "x"},
        "neo4j": {"enabled": False},
        "reranker": {"backend": "local"},
        "retrieval_policy": {
            "internal": {"files": "required", "vector": "disabled", "graph": "disabled"},
            "optional_default": "include",
            "web": "explicit",
        },
    })
    assert not any(level == "error" for level, _ in found)


def test_rejects_unknown_evidence_control_mode():
    found = messages({
        "elasticsearch": {"enabled": True},
        "qdrant": {"enabled": False},
        "reranker": {"backend": "none"},
        "evidence_control": {"mode": "automatic"},
    })
    assert any(
        level == "error" and "evidence_control.mode must be off or review" in message
        for level, message in found
    )
