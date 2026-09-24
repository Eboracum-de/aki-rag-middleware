from pathlib import Path

from starlette.requests import Request

from rag.credential_store import CredentialStore
import rag.api as api


def _request(headers=None):
    raw = []
    for key, value in (headers or {}).items():
        raw.append((key.lower().encode("latin1"), value.encode("latin1")))
    return Request({"type": "http", "method": "POST", "path": "/auth/nextcloud/ensure", "headers": raw})


def test_auth_ensure_starts_jit_flow_for_unknown_identity(monkeypatch, tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    monkeypatch.setattr(api, "credential_store", store)
    monkeypatch.setattr(api.live_acl, "enabled", True)
    monkeypatch.setattr(api.live_acl, "identity_mode", "credential_store")
    monkeypatch.setattr(api, "_start_nextcloud_flow_for_user", lambda user_id: {
        "status": "pending",
        "flow_id": "flow-1",
        "login_url": "https://cloud.example/login",
        "rag_user_id": user_id,
    })

    result = api.nextcloud_auth_ensure(
        api.NextcloudAuthEnsureRequest(),
        _request({"x-rag-user-id": "frontend-user"}),
    )
    assert result["status"] == "pending"
    assert result["rag_user_id"] == "frontend-user"


def test_auth_ensure_returns_connected_for_existing_binding(monkeypatch, tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    store.set_credential(
        "frontend-user", "nextcloud", "alice", "app-secret",
        server="https://cloud.example",
    )
    monkeypatch.setattr(api, "credential_store", store)
    monkeypatch.setattr(api.live_acl, "enabled", True)
    monkeypatch.setattr(api.live_acl, "identity_mode", "credential_store")

    result = api.nextcloud_auth_ensure(
        api.NextcloudAuthEnsureRequest(),
        _request({"x-rag-user-id": "frontend-user"}),
    )
    assert result["status"] == "connected"
    assert result["rag_user_id"] == "frontend-user"
    assert result["nextcloud_login"] == "alice"
    assert result["server"] == "https://cloud.example"
    assert result["canonical_user_id"]
    assert store.get_canonical_user_for_identity("frontend-user").nextcloud_login == "alice"


def test_auth_ensure_reports_missing_frontend_identity(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(api, "credential_store", CredentialStore(tmp_path / "users.sqlite"))
    monkeypatch.setattr(api.live_acl, "enabled", True)
    monkeypatch.setattr(api.live_acl, "identity_mode", "credential_store")
    result = api.nextcloud_auth_ensure(api.NextcloudAuthEnsureRequest(), _request())
    assert result == {"status": "identity_missing"}


def test_search_fails_before_retrieval_when_identity_has_no_binding(monkeypatch, tmp_path: Path):
    from fastapi import HTTPException

    store = CredentialStore(tmp_path / "users.sqlite")
    monkeypatch.setattr(api, "credential_store", store)
    monkeypatch.setattr(api.live_acl, "enabled", True)
    monkeypatch.setattr(api.live_acl, "identity_mode", "credential_store")
    monkeypatch.setattr(api.live_acl, "cfg", {
        "acl": {
            "enabled": True,
            "identity_mode": "credential_store",
            "credential_store": str(tmp_path / "users.sqlite"),
        }
    })

    def should_not_run(**kwargs):
        raise AssertionError("retrieval must not run before credential preflight")

    monkeypatch.setattr(api, "perform_search", should_not_run)
    try:
        api.search(
            api.SearchRequest(query="Darlehensvertrag"),
            _request({"x-rag-user-id": "unknown-user"}),
        )
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "Nextcloud credential" in str(exc.detail)
    else:
        raise AssertionError("missing binding must fail closed")


def test_login_flow_rejects_redirect_and_uses_named_user_agent(monkeypatch):
    class DummyResponse:
        status_code = 302
        headers = {"Location": "https://cloud.example/index.php/login/v2"}

    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return DummyResponse()

    monkeypatch.setattr(api.requests, "post", fake_post)
    try:
        api._nextcloud_flow_post("http://cloud.example/index.php/login/v2")
    except RuntimeError as exc:
        assert "canonical HTTPS URL" in str(exc)
    else:
        raise AssertionError("redirect must fail explicitly")

    assert captured["allow_redirects"] is False
    assert captured["headers"]["User-Agent"] == "SunaQ"
