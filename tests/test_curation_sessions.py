from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from rag.credential_store import CredentialStore
from fastapi import HTTPException

from rag.acl import AclDecision
from rag.credential_store import CurationSession
from rag.curation_ui import _filter_findings_with_acl, cleanup_stale_curation_sessions
from rag.secret_crypto import generate_master_key


def _encrypted_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CredentialStore:
    key_path = tmp_path / "credential-master.key"
    generate_master_key(key_path, mode=0o600)
    monkeypatch.setenv("RAG_CREDENTIAL_MASTER_KEY_FILE", str(key_path))
    monkeypatch.setenv("RAG_CREDENTIAL_ENCRYPTION", "required")
    return CredentialStore(tmp_path / "users.sqlite")


def _enabled_user(store: CredentialStore):
    user = store.ensure_canonical_user("https://cloud.example", "alice")
    assert store.set_findings_curation_enabled(user.canonical_user_id, True)
    refreshed = store.get_canonical_user(user.canonical_user_id)
    assert refreshed is not None
    assert refreshed.findings_curation_enabled is True
    return refreshed


def test_curation_session_is_ephemeral_encrypted_and_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = _encrypted_store(tmp_path, monkeypatch)
    user = _enabled_user(store)

    token, session = store.create_curation_session(
        canonical_user_id=user.canonical_user_id,
        nextcloud_server=user.nextcloud_server,
        nextcloud_login=user.nextcloud_login,
        app_password="temporary-app-password",
        lifetime_seconds=7200,
    )

    assert 7199 <= session.expires_at - session.created_at <= 7201
    assert store.list_bindings(user.canonical_user_id) == []

    with sqlite3.connect(store.path) as con:
        row = con.execute(
            "SELECT app_password,expires_at FROM curation_sessions WHERE session_id_hash=?",
            (store.curation_session_hash(token),),
        ).fetchone()
    assert row is not None
    assert str(row[0]).startswith("enc:v1:")
    assert row[0] != "temporary-app-password"

    # Expiry is absolute: touching the session does not move expires_at.
    before = store.get_curation_session(token)
    after = store.get_curation_session(token)
    assert before is not None and after is not None
    assert before.expires_at == session.expires_at == after.expires_at

    with sqlite3.connect(store.path) as con:
        con.execute(
            "UPDATE curation_sessions SET expires_at=? WHERE session_id_hash=?",
            (time.time() - 1, store.curation_session_hash(token)),
        )
        con.commit()
    assert store.get_curation_session(token) is None
    assert store.get_curation_session_any(token) is not None


def test_user_permission_is_required_to_create_curation_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = _encrypted_store(tmp_path, monkeypatch)
    user = store.ensure_canonical_user("https://cloud.example", "alice")

    with pytest.raises(PermissionError):
        store.create_curation_session(
            canonical_user_id=user.canonical_user_id,
            nextcloud_server=user.nextcloud_server,
            nextcloud_login=user.nextcloud_login,
            app_password="temporary-app-password",
            lifetime_seconds=7200,
        )


def test_startup_cleanup_revokes_and_deletes_stale_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = _encrypted_store(tmp_path, monkeypatch)
    user = _enabled_user(store)
    _token, session = store.create_curation_session(
        canonical_user_id=user.canonical_user_id,
        nextcloud_server=user.nextcloud_server,
        nextcloud_login=user.nextcloud_login,
        app_password="temporary-app-password",
        lifetime_seconds=7200,
    )

    calls = []

    def fake_revoke(current, cfg):
        calls.append((current.nextcloud_login, current.app_password))
        return True

    monkeypatch.setattr("rag.curation_ui._revoke_app_password", fake_revoke)
    result = cleanup_stale_curation_sessions(
        {"auth": {"credential_store": str(store.path)}}
    )

    assert result == {"found": 1, "revoked": 1, "pending": 0}
    assert calls == [("alice", "temporary-app-password")]
    assert store.list_curation_sessions() == []


def test_failed_startup_revocation_leaves_only_pending_nonusable_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _encrypted_store(tmp_path, monkeypatch)
    user = _enabled_user(store)
    token, _session = store.create_curation_session(
        canonical_user_id=user.canonical_user_id,
        nextcloud_server=user.nextcloud_server,
        nextcloud_login=user.nextcloud_login,
        app_password="temporary-app-password",
        lifetime_seconds=7200,
    )

    monkeypatch.setattr("rag.curation_ui._revoke_app_password", lambda current, cfg: False)
    result = cleanup_stale_curation_sessions(
        {"auth": {"credential_store": str(store.path)}}
    )

    assert result == {"found": 1, "revoked": 0, "pending": 1}
    assert store.get_curation_session(token) is None
    stale = store.get_curation_session_any(token)
    assert stale is not None
    assert stale.state == "revocation_pending"


def _session() -> CurationSession:
    now = time.time()
    return CurationSession(
        session_id_hash="hash",
        canonical_user_id="user-id",
        nextcloud_server="https://cloud.example",
        nextcloud_login="alice",
        app_password="temporary-app-password",
        csrf_token="csrf",
        state="active",
        created_at=now,
        expires_at=now + 3600,
        last_seen_at=now,
    )


def test_self_service_finding_acl_fails_closed_when_live_acl_is_disabled():
    class DisabledAcl:
        enabled = False

        def authorize_with_credential(self, *args, **kwargs):
            raise AssertionError("disabled ACL must not authorize findings")

    with pytest.raises(HTTPException) as exc:
        _filter_findings_with_acl(
            DisabledAcl(),  # type: ignore[arg-type]
            _session(),
            [{"finding_id": "f1", "document_id": "files:1", "evidence": "secret"}],
        )
    assert exc.value.status_code == 503


def test_self_service_finding_acl_rejects_disabled_decision():
    class DisabledDecisionAcl:
        enabled = True

        def authorize_with_credential(self, results, **kwargs):
            return AclDecision(False, list(results), len(results), len(results))

    with pytest.raises(HTTPException) as exc:
        _filter_findings_with_acl(
            DisabledDecisionAcl(),  # type: ignore[arg-type]
            _session(),
            [{"finding_id": "f1", "document_id": "files:1", "evidence": "secret"}],
        )
    assert exc.value.status_code == 503


def test_self_service_finding_acl_returns_only_authorized_findings():
    class EnabledAcl:
        enabled = True

        def authorize_with_credential(self, results, **kwargs):
            allowed = [item for item in results if item["document_id"] == "files:2"]
            return AclDecision(True, allowed, len(results), len(allowed))

    rows = [
        {"finding_id": "f1", "document_id": "files:1"},
        {"finding_id": "f2", "document_id": "files:2"},
    ]
    assert _filter_findings_with_acl(EnabledAcl(), _session(), rows) == [rows[1]]  # type: ignore[arg-type]


def test_startup_cleanup_discards_undecryptable_session_but_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _encrypted_store(tmp_path, monkeypatch)
    user = _enabled_user(store)
    _bad_token, bad = store.create_curation_session(
        canonical_user_id=user.canonical_user_id,
        nextcloud_server=user.nextcloud_server,
        nextcloud_login=user.nextcloud_login,
        app_password="bad-session-secret",
        lifetime_seconds=7200,
    )
    _good_token, good = store.create_curation_session(
        canonical_user_id=user.canonical_user_id,
        nextcloud_server=user.nextcloud_server,
        nextcloud_login=user.nextcloud_login,
        app_password="good-session-secret",
        lifetime_seconds=7200,
    )
    with sqlite3.connect(store.path) as con:
        con.execute(
            "UPDATE curation_sessions SET app_password=? WHERE session_id_hash=?",
            ("enc:v1:not-valid-ciphertext", bad.session_id_hash),
        )
        con.commit()

    calls = []
    monkeypatch.setattr(
        "rag.curation_ui._revoke_app_password",
        lambda current, cfg: calls.append(current.app_password) or True,
    )
    result = cleanup_stale_curation_sessions(
        {"auth": {"credential_store": str(store.path)}}
    )

    assert result == {"found": 2, "revoked": 1, "pending": 0}
    assert calls == ["good-session-secret"]
    assert store.list_curation_sessions() == []
