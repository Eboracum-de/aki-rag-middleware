import pytest

from rag.retrieval_policy import configured_internal_arms, load_retrieval_policy


def test_planner_may_drop_only_optional_arms():
    policy = load_retrieval_policy({
        "retrieval_policy": {
            "internal": {"files": "required", "vector": "optional", "graph": "optional"},
            "optional_default": "include",
        }
    })
    assert policy.planner_arms(["vector"], available={"files", "vector", "graph"}) == {"files", "vector"}
    assert policy.planner_arms([], available={"files", "vector", "graph"}) == {"files"}


def test_planner_failure_uses_deterministic_include_fallback():
    policy = load_retrieval_policy({
        "retrieval_policy": {
            "internal": {"files": "required", "vector": "optional", "graph": "optional"},
            "optional_default": "include",
        }
    })
    assert policy.planner_arms(None, valid=False, available={"files", "vector", "graph"}) == {"files", "vector", "graph"}


def test_policy_never_enables_unavailable_or_disabled_arm():
    policy = load_retrieval_policy({
        "retrieval_policy": {
            "internal": {"files": "required", "vector": "disabled", "graph": "optional"},
        }
    })
    assert policy.planner_arms(["vector", "graph"], available={"files", "graph"}) == {"files", "graph"}


def test_configured_arms_separate_graph_document_arm_from_neo4j_entity_expansion():
    cfg = {
        "elasticsearch": {"enabled": True},
        "qdrant": {"enabled": False},
        "neo4j": {"enabled": True},
        "graph_retrieval": {"enabled": False},
    }
    assert configured_internal_arms(cfg) == {"files"}


def test_invalid_policy_is_rejected():
    with pytest.raises(ValueError):
        load_retrieval_policy({"retrieval_policy": {"internal": {"vector": "maybe"}}})
