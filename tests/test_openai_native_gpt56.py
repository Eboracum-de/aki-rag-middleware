from rag.llm_backend import OpenAICompatibleBackend


def backend(base_url="https://api.openai.com/v1"):
    return OpenAICompatibleBackend(base_url=base_url, model="gpt-5.6-luna", api_key="test")


def test_native_gpt56_false_maps_to_none():
    b = backend()
    assert b._reasoning_effort(False, "gpt-5.6-luna") == "none"
    opts = b._payload_options(
        {"temperature": 0.0, "num_predict": 900},
        model="gpt-5.6-luna",
        reasoning_effort="none",
    )
    assert "temperature" not in opts
    assert opts["max_completion_tokens"] == 900
    assert "max_tokens" not in opts


def test_native_gpt56_reasoning_strips_sampling_controls():
    b = backend()
    assert b._reasoning_effort(True, "gpt-5.6-luna") == "medium"
    opts = b._payload_options(
        {"temperature": 0.0, "top_p": 0.8, "num_predict": 700},
        model="gpt-5.6-luna",
        reasoning_effort="medium",
    )
    assert "temperature" not in opts
    assert "top_p" not in opts
    assert opts["max_completion_tokens"] == 700


def test_third_party_openai_compatible_behavior_is_preserved():
    b = backend("http://localhost:8000/v1")
    assert b._reasoning_effort(False, "gpt-5.6-luna") is None
    opts = b._payload_options(
        {"temperature": 0.0, "num_predict": 900},
        model="gpt-5.6-luna",
        reasoning_effort=None,
    )
    assert opts["temperature"] == 0.0
    assert opts["max_tokens"] == 900
    assert "max_completion_tokens" not in opts
