from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import JSONResponse

import rag.api as api
import rag.openai_provider as provider
from rag.internal_auth import (
    HEADER_NAME,
    PROVIDER_HEADER_NAME,
    internal_api_headers,
    provider_api_headers,
)
from rag.runtime_validation import validate_security_config


def _request(path: str, headers: dict[str, str] | None = None) -> Request:
    raw = [
        (str(key).lower().encode("latin1"), str(value).encode("latin1"))
        for key, value in (headers or {}).items()
    ]
    return Request({
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": raw,
        "query_string": b"",
        "server": ("127.0.0.1", 8765),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
    })


def _machine_headers(monkeypatch) -> dict[str, str]:
    internal = "internal-" + "i" * 40
    provider_key = "provider-" + "p" * 40
    monkeypatch.setenv("RAG_INTERNAL_API_KEY", internal)
    monkeypatch.setenv("RAG_PROVIDER_INTERNAL_KEY", provider_key)
    return {
        HEADER_NAME: internal,
        PROVIDER_HEADER_NAME: provider_key,
    }


@pytest.mark.asyncio
async def test_internal_routes_fail_closed_without_runtime_key(monkeypatch):
    monkeypatch.delenv("RAG_INTERNAL_API_KEY", raising=False)
    called = False

    async def call_next(_request):
        nonlocal called
        called = True
        return JSONResponse({"ok": True})

    response = await api.require_internal_api_auth(_request("/graph/document"), call_next)
    assert response.status_code == 503
    assert called is False


@pytest.mark.asyncio
async def test_internal_routes_reject_missing_or_wrong_machine_key(monkeypatch):
    monkeypatch.setenv("RAG_INTERNAL_API_KEY", "correct-" + "x" * 40)

    async def call_next(_request):
        return JSONResponse({"ok": True})

    missing = await api.require_internal_api_auth(_request("/query-context"), call_next)
    wrong = await api.require_internal_api_auth(
        _request("/auth/nextcloud/status/flow", {HEADER_NAME: "wrong-" + "y" * 40}),
        call_next,
    )
    assert missing.status_code == 401
    assert wrong.status_code == 401


@pytest.mark.asyncio
async def test_baseline_internal_machine_key_allows_route_dependency_to_decide(monkeypatch):
    key = "correct-" + "x" * 40
    monkeypatch.setenv("RAG_INTERNAL_API_KEY", key)
    called: list[str] = []

    async def call_next(request):
        called.append(request.url.path)
        return JSONResponse({"ok": True})

    for path in (
        "/search",
        "/documents/resolve",
        "/plan",
        "/query-context",
        "/graph/document",
        "/graph/research-findings",
        "/auth/nextcloud/ensure",
    ):
        response = await api.require_internal_api_auth(
            _request(path, {HEADER_NAME: key}),
            call_next,
        )
        assert response.status_code == 200
    assert len(called) == 7


@pytest.mark.asyncio
async def test_live_admin_and_curation_keep_their_own_auth_models(monkeypatch):
    monkeypatch.delenv("RAG_INTERNAL_API_KEY", raising=False)
    called: list[str] = []

    async def call_next(request):
        called.append(request.url.path)
        return JSONResponse({"ok": True})

    for path in ("/live", "/rag-admin/", "/curation/"):
        response = await api.require_internal_api_auth(_request(path), call_next)
        assert response.status_code == 200
    assert called == ["/live", "/rag-admin/", "/curation/"]


def test_provider_headers_require_both_machine_credentials(monkeypatch):
    headers = _machine_headers(monkeypatch)
    assert internal_api_headers()[HEADER_NAME] == headers[HEADER_NAME]
    provider_headers = provider_api_headers()
    assert provider_headers[HEADER_NAME] == headers[HEADER_NAME]
    assert provider_headers[PROVIDER_HEADER_NAME] == headers[PROVIDER_HEADER_NAME]

    monkeypatch.delenv("RAG_PROVIDER_INTERNAL_KEY", raising=False)
    with pytest.raises(RuntimeError):
        provider_api_headers()


def test_runtime_validation_requires_both_machine_keys(monkeypatch):
    monkeypatch.delenv("RAG_INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("RAG_PROVIDER_INTERNAL_KEY", raising=False)
    errors = validate_security_config({
        "acl": {"enabled": False, "identity_mode": "single_user"},
        "elasticsearch": {"enabled": False},
    })
    assert any("RAG_INTERNAL_API_KEY" in item for item in errors)
    assert any("RAG_PROVIDER_INTERNAL_KEY" in item for item in errors)


def test_provider_middleware_client_sets_both_machine_credentials(monkeypatch):
    headers = _machine_headers(monkeypatch)
    captured = {}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(provider.httpx, "AsyncClient", DummyClient)
    provider._middleware_client(timeout=12.0)
    assert captured["headers"][HEADER_NAME] == headers[HEADER_NAME]
    assert captured["headers"][PROVIDER_HEADER_NAME] == headers[PROVIDER_HEADER_NAME]
    assert captured["timeout"] == 12.0


def test_trusted_provider_requires_distinct_provider_secret(monkeypatch):
    headers = _machine_headers(monkeypatch)
    api.api_security.require_trusted_provider(_request("/plan", headers))

    with pytest.raises(HTTPException) as exc:
        api.api_security.require_trusted_provider(
            _request("/plan", {HEADER_NAME: headers[HEADER_NAME]})
        )
    assert exc.value.status_code == 401


def test_user_zone_requires_provider_and_bound_identity_in_multi_user(monkeypatch):
    headers = _machine_headers(monkeypatch)
    monkeypatch.setattr(api.live_acl, "enabled", True)
    monkeypatch.setattr(api.live_acl, "identity_mode", "credential_store")

    seen = []
    monkeypatch.setattr(
        api.live_acl,
        "credential_for_user",
        lambda user_id=None: seen.append(user_id) or object(),
    )

    with pytest.raises(HTTPException) as exc:
        api.api_security.require_current_user(_request("/search", headers))
    assert exc.value.status_code == 403

    scoped = dict(headers)
    scoped["X-RAG-User-ID"] = "client-a::alice"
    assert api.api_security.require_current_user(_request("/search", scoped)) == "client-a::alice"
    assert seen == ["client-a::alice"]


def test_user_zone_allows_server_side_identity_in_single_user(monkeypatch):
    headers = _machine_headers(monkeypatch)
    monkeypatch.setattr(api.live_acl, "enabled", True)
    monkeypatch.setattr(api.live_acl, "identity_mode", "single_user")
    monkeypatch.setattr(api.live_acl, "credential_for_user", lambda user_id=None: object())
    assert api.api_security.require_current_user(_request("/search", headers)) == ""


def test_admin_zone_requires_internal_key_and_basic_admin_auth(monkeypatch):
    headers = _machine_headers(monkeypatch)
    monkeypatch.setenv("RAG_ADMIN_USER", "admin")
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret-password")

    with pytest.raises(HTTPException) as exc:
        api.api_security.require_admin(_request("/graph/document", {
            HEADER_NAME: headers[HEADER_NAME],
        }))
    assert exc.value.status_code == 401

    basic = base64.b64encode(b"admin:secret-password").decode("ascii")
    api.api_security.require_admin(_request("/graph/document", {
        HEADER_NAME: headers[HEADER_NAME],
        "Authorization": "Basic " + basic,
    }))


def test_core_routes_declare_machine_readable_security_zones():
    expected = {
        ("/live", "GET"): "PUBLIC",
        ("/health", "GET"): "INTERNAL",
        ("/auth/nextcloud/start", "POST"): "TRUSTED_PROVIDER",
        ("/auth/nextcloud/ensure", "POST"): "TRUSTED_PROVIDER",
        ("/auth/nextcloud/status/{flow_id}", "GET"): "TRUSTED_PROVIDER",
        ("/auth/nextcloud/{rag_user_id}", "DELETE"): "ADMIN",
        ("/web/search", "POST"): "USER",
        ("/web/archive/finalize", "POST"): "USER",
        ("/query-context", "POST"): "TRUSTED_PROVIDER",
        ("/source-origin/register-chat", "POST"): "USER",
        ("/plan", "POST"): "TRUSTED_PROVIDER",
        ("/graph/stats", "GET"): "ADMIN",
        ("/graph/document", "POST"): "ADMIN",
        ("/graph/enqueue-evidence", "POST"): "INTERNAL",
        ("/graph/research-findings", "POST"): "INTERNAL",
        ("/graph/queue/stats", "GET"): "ADMIN",
        ("/graph/queue/jobs", "GET"): "ADMIN",
        ("/graph/index-evidence", "POST"): "INTERNAL",
        ("/documents/resolve", "POST"): "USER",
        ("/elastic/search", "POST"): "USER",
        ("/multi-search", "POST"): "USER",
        ("/search", "POST"): "USER",
    }

    dependency_for_zone = {
        "PUBLIC": None,
        "INTERNAL": "require_internal_client",
        "TRUSTED_PROVIDER": "require_trusted_provider",
        "USER": "require_current_user",
        "ADMIN": "require_admin",
    }
    actual = {}
    for route in api.app.routes:
        if not isinstance(route, APIRoute):
            continue
        zone = (route.openapi_extra or {}).get("x-aki-security-zone")
        if not zone:
            continue
        dependency_names = {
            getattr(item.call, "__name__", "")
            for item in route.dependant.dependencies
        }
        required_dependency = dependency_for_zone[zone]
        if required_dependency is not None:
            assert required_dependency in dependency_names, (route.path, zone, dependency_names)
        for method in route.methods or set():
            key = (route.path, method)
            if key in expected:
                actual[key] = zone

    assert actual == expected


@pytest.mark.asyncio
async def test_provider_chat_archive_registration_scopes_external_identity(monkeypatch):
    captured = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return DummyResponse()

    monkeypatch.setattr(provider, "_check_auth", lambda authorization: "client-a")

    def scoped(client_id, external_user_id):
        captured["scope"] = (client_id, external_user_id)
        return "client-a::alice"

    monkeypatch.setattr(provider, "scope_identity", scoped)
    monkeypatch.setattr(provider, "_middleware_client", lambda **kwargs: DummyClient())

    request = _request("/v1/archive/chat/register", {"X-RAG-User-ID": "alice"})
    body = provider.ChatArchiveRegisterRequest(
        document_id="files:42",
        path="AKI-Chats/example.md",
    )

    result = await provider.register_chat_archive(
        body,
        request,
        authorization="Bearer provider-key",
    )

    assert result == {"ok": True}
    assert captured["scope"] == ("client-a", "alice")
    assert captured["headers"]["X-RAG-User-ID"] == "client-a::alice"


@pytest.mark.asyncio
async def test_provider_chat_archive_registration_rejects_invalid_scoped_identity(monkeypatch):
    monkeypatch.setattr(provider, "_check_auth", lambda authorization: "client-a")
    monkeypatch.setattr(
        provider,
        "scope_identity",
        lambda client_id, external_user_id: (_ for _ in ()).throw(ValueError("invalid")),
    )

    request = _request("/v1/archive/chat/register", {"X-RAG-User-ID": "alice"})
    body = provider.ChatArchiveRegisterRequest(
        document_id="files:42",
        path="AKI-Chats/example.md",
    )

    with pytest.raises(HTTPException) as exc:
        await provider.register_chat_archive(
            body,
            request,
            authorization="Bearer provider-key",
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Invalid RAG user identity"
