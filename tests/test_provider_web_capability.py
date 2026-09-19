from starlette.requests import Request

from rag.openai_provider import (
    ChatCompletionRequest,
    SearchResult,
    _auxiliary_task_kind,
    _previous_source_map,
    _probable_followup,
    _short_acronym_continues_prior_user,
    _request_allows_web,
    _source_suffix,
)


def _request(headers=None):
    raw = []
    for key, value in (headers or {}).items():
        raw.append((key.lower().encode("latin1"), value.encode("latin1")))
    return Request({"type": "http", "method": "POST", "path": "/v1/chat/completions", "headers": raw})


def test_ui_search_web_function_does_not_grant_capability():
    body = ChatCompletionRequest(
        messages=[{"role": "user", "content": "Wer ist heute Vorstand?"}],
        tools=[{"type": "function", "function": {"name": "search_web", "parameters": {"type": "object"}}}],
    )
    assert _request_allows_web(body, _request()) is False


def test_native_web_search_tool_does_not_grant_capability():
    body = ChatCompletionRequest(
        messages=[{"role": "user", "content": "Test"}],
        tools=[{"type": "web_search"}],
    )
    assert _request_allows_web(body, _request()) is False


def test_unknown_tool_does_not_grant_web_capability():
    body = ChatCompletionRequest(
        messages=[{"role": "user", "content": "Test"}],
        tools=[{"type": "function", "function": {"name": "calculator"}}],
    )
    assert _request_allows_web(body, _request()) is False


def test_neutral_header_can_grant_web_capability():
    body = ChatCompletionRequest(messages=[{"role": "user", "content": "Test"}])
    assert _request_allows_web(body, _request({"x-rag-web-allowed": "true"})) is True


def test_web_query_generation_helper_is_auxiliary():
    prompt = '''### Task:\nAnalyze the chat history to determine the necessity of generating search queries.\nReturn JSON with a "queries" array.\n\nChat History:\nUSER: Frank Muster'''
    assert _auxiliary_task_kind(_request(), prompt) == "ui:web_query_generation"


def test_standalone_name_is_not_followup():
    assert _probable_followup("Frank Muster") is False


def test_pronoun_question_is_followup():
    assert _probable_followup("Was ist mit ihm?") is True


def test_web_acronym_can_continue_immediately_prior_user_entity():
    messages = [
        {"role": "user", "content": "Suche im Internet nach FLG Automation in Karben"},
        {"role": "assistant", "content": "Ergebnis zur FLG Automation AG."},
        {"role": "user", "content": "/web FLG"},
    ]
    assert _short_acronym_continues_prior_user(messages, "FLG") is True


def test_web_acronym_does_not_inherit_unrelated_or_exact_prior_query():
    unrelated = [
        {"role": "user", "content": "Suche aktuelle Informationen zu Acme Automation"},
        {"role": "assistant", "content": "Ergebnis."},
        {"role": "user", "content": "/web FLG"},
    ]
    exact = [
        {"role": "user", "content": "FLG"},
        {"role": "assistant", "content": "Mehrdeutig."},
        {"role": "user", "content": "/web FLG"},
    ]
    assert _short_acronym_continues_prior_user(unrelated, "FLG") is False
    assert _short_acronym_continues_prior_user(exact, "FLG") is False


def test_normal_source_suffix_contains_snippet():
    result = SearchResult(
        index=1,
        title="Test.pdf",
        text="Fallback text",
        raw={
            "path": "Ordner/Test.pdf",
            "document_id": "files:123",
            "vector_snippet": "Hier steht Greenwich AG als relevante Passage im Dokument.",
        },
    )
    rendered = _source_suffix("Antwort [1]", [result], query="Greenwich AG")
    assert "**Quellen:**" in rendered
    assert "> " in rendered
    assert "**Greenwich**" in rendered


def test_internal_sources_remain_resolvable_in_mixed_answer():
    messages = [
        {"role": "user", "content": "Frage"},
        {
            "role": "assistant",
            "content": (
                "Antwort\n\n**Interne Quellen:**\n"
                "- [1] [Test.pdf](https://cloud.example/index.php/f/123?openfile=123)\n"
                "  > Passage\n\n"
                "**Öffentliche Quellen:**\n"
                "- [W1] [Web](https://example.org)\n"
                "  Archiv: `Webarchiv/2026-08/x/01.txt`\n"
            ),
        },
        {"role": "user", "content": "/use:1 Prüfe"},
    ]
    assert _previous_source_map(messages) == {1: "files:123"}


def test_unbound_openwebui_user_gets_nextcloud_login_link(monkeypatch):
    import asyncio
    import rag.openai_provider as provider

    async def fake_ensure(user_id):
        assert user_id == "openwebui-local::owui-user-123"
        return {
            "status": "pending",
            "flow_id": "flow-1",
            "login_url": "https://cloud.example/index.php/login/flow/abc",
        }

    monkeypatch.setattr(provider, "_ensure_nextcloud_binding", fake_ensure)
    monkeypatch.setattr(provider, "_check_auth", lambda authorization: "openwebui-local")
    body = provider.ChatCompletionRequest(
        messages=[{"role": "user", "content": "Darlehensvertrag"}],
        stream=False,
    )
    response = asyncio.run(
        provider.chat_completions(
            body,
            _request({"x-openwebui-user-id": "owui-user-123"}),
            authorization=None,
        )
    )
    content = response["choices"][0]["message"]["content"]
    assert "Nextcloud-Anmeldung erforderlich" in content
    assert "https://cloud.example/index.php/login/flow/abc" in content


def test_same_external_user_id_is_isolated_by_provider_client(monkeypatch, tmp_path):
    import rag.openai_provider as provider
    from rag.credential_store import CredentialStore, scope_identity

    store = CredentialStore(tmp_path / "users.sqlite")
    store.register_client("frontend-a", "A" * 32, name="A")
    store.register_client("frontend-b", "B" * 32, name="B")
    monkeypatch.setattr(provider, "_PROVIDER_CLIENT_STORE", store)

    client_a = provider._check_auth("Bearer " + "A" * 32)
    client_b = provider._check_auth("Bearer " + "B" * 32)
    assert client_a == "frontend-a"
    assert client_b == "frontend-b"
    assert scope_identity(client_a, "same-user") != scope_identity(client_b, "same-user")


def test_followup_helper_signature_is_detected_for_server_side_suppression():
    prompt = "### Task: Suggest 3-5 relevant follow-up questions based on the chat history."
    assert _auxiliary_task_kind(_request(), prompt) == "ui:follow_ups"


def test_followup_helper_returns_empty_list_without_llm(monkeypatch):
    import asyncio
    from starlette.requests import Request
    import rag.openai_provider as provider

    monkeypatch.setattr(provider, "_check_auth", lambda authorization: "test-client")

    async def forbidden_llm(*args, **kwargs):
        raise AssertionError("follow-up helper must not invoke an LLM")

    monkeypatch.setattr(provider, "_ollama_complete", forbidden_llm)
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8766),
        "scheme": "http",
        "query_string": b"",
    })
    body = provider.ChatCompletionRequest(
        messages=[{
            "role": "user",
            "content": "### Task: Suggest 3-5 relevant follow-up questions based on the chat history.",
        }],
        stream=False,
    )
    response = asyncio.run(provider.chat_completions(body, request, authorization="Bearer ignored"))
    assert response["choices"][0]["message"]["content"] == '{"follow_ups":[]}'
