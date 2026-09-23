from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from rag import api

def _request(user_id: str | None):
    headers = {}
    if user_id:
        headers["x-rag-user-id"] = user_id
    return SimpleNamespace(headers=headers)


def _body():
    return api.ChatArchiveRegisterRequest(
        document_id="files:42",
        path="SunaQ-Chats/2026-09-22 - Test - deadbeef.md",
    )


def test_chat_archive_registration_requires_user_identity(monkeypatch):
    monkeypatch.setattr(api, "chat_archive_roots", lambda: ("SunaQ-Chats", "AKI-Chats"))
    with pytest.raises(HTTPException) as exc:
        api.register_chat_archive_source(_body(), _request(None))
    assert exc.value.status_code == 403


def test_chat_archive_registration_denied_by_live_acl_never_writes_registry(monkeypatch):
    class FakeAcl:
        enabled = True

        def resolve_visible_file_path(self, document_id, *, rag_user_id=None):
            assert rag_user_id == "alice"
            assert document_id == "files:42"
            return None

    monkeypatch.setattr(api, "live_acl", FakeAcl())
    monkeypatch.setattr(api, "chat_archive_roots", lambda: ("SunaQ-Chats", "AKI-Chats"))
    monkeypatch.setattr(
        api,
        "register_document",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not register")),
    )

    with pytest.raises(HTTPException) as exc:
        api.register_chat_archive_source(_body(), _request("alice"))
    assert exc.value.status_code == 403


def test_chat_archive_registration_writes_only_after_live_acl_authorization(monkeypatch):
    class FakeAcl:
        enabled = True

        def resolve_visible_file_path(self, document_id, *, rag_user_id=None):
            assert rag_user_id == "alice"
            assert document_id == "files:42"
            return "SunaQ-Chats/2026-09-22 - Test - deadbeef.md"

    calls = []

    def register(document_id, source_origin, **kwargs):
        calls.append((document_id, source_origin, kwargs))
        return True

    monkeypatch.setattr(api, "live_acl", FakeAcl())
    monkeypatch.setattr(api, "chat_archive_roots", lambda: ("SunaQ-Chats", "AKI-Chats"))
    monkeypatch.setattr(api, "register_document", register)
    monkeypatch.setattr(
        api,
        "auto_mirror_registry_to_elasticsearch",
        lambda **kwargs: {"checked": 1, "updated": 1, "missing": 0},
    )

    result = api.register_chat_archive_source(_body(), _request("alice"))

    assert result["ok"] is True
    assert result["registered"] is True
    assert calls == [(
        "files:42",
        "chat_archive",
        {
            "source_path": "SunaQ-Chats/2026-09-22 - Test - deadbeef.md",
            "classification_source": "chat_archive_write",
        },
    )]


def test_chat_archive_registration_rejects_fabricated_client_path(monkeypatch):
    class FakeAcl:
        enabled = True

        def resolve_visible_file_path(self, document_id, *, rag_user_id=None):
            return "Documents/visible.pdf"

    monkeypatch.setattr(api, "live_acl", FakeAcl())
    monkeypatch.setattr(api, "chat_archive_roots", lambda: ("SunaQ-Chats", "AKI-Chats"))
    monkeypatch.setattr(
        api,
        "register_document",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not register")),
    )

    with pytest.raises(HTTPException) as exc:
        api.register_chat_archive_source(_body(), _request("alice"))
    assert exc.value.status_code == 400


def test_chat_archive_registration_rejects_path_mismatch(monkeypatch):
    class FakeAcl:
        enabled = True

        def resolve_visible_file_path(self, document_id, *, rag_user_id=None):
            return "SunaQ-Chats/server-derived.md"

    monkeypatch.setattr(api, "live_acl", FakeAcl())
    monkeypatch.setattr(api, "chat_archive_roots", lambda: ("SunaQ-Chats", "AKI-Chats"))

    with pytest.raises(HTTPException) as exc:
        api.register_chat_archive_source(_body(), _request("alice"))
    assert exc.value.status_code == 400
    assert "does not match Nextcloud" in str(exc.value.detail)


def test_chat_archive_registration_route_uses_user_zone():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "rag" / "api.py").read_text(encoding="utf-8")
    start = source.index('"/source-origin/register-chat"')
    block = source[start:start + 500]
    assert "**ZONE_USER" in block
    assert "**ZONE_TRUSTED_PROVIDER" not in block



def test_chat_archive_registration_still_accepts_legacy_aki_chat_root(monkeypatch):
    body = api.ChatArchiveRegisterRequest(
        document_id="files:77",
        path="AKI-Chats/legacy.md",
    )

    class FakeAcl:
        enabled = True

        def resolve_visible_file_path(self, document_id, *, rag_user_id=None):
            return "AKI-Chats/legacy.md"

    calls = []
    monkeypatch.setattr(api, "live_acl", FakeAcl())
    monkeypatch.setattr(api, "chat_archive_roots", lambda: ("SunaQ-Chats", "AKI-Chats"))
    monkeypatch.setattr(
        api,
        "register_document",
        lambda document_id, source_origin, **kwargs: calls.append(
            (document_id, source_origin, kwargs)
        ) or True,
    )
    monkeypatch.setattr(
        api,
        "auto_mirror_registry_to_elasticsearch",
        lambda **kwargs: {"checked": 1, "updated": 1, "missing": 0},
    )

    result = api.register_chat_archive_source(body, _request("alice"))
    assert result["ok"] is True
    assert calls[0][0:2] == ("files:77", "chat_archive")
