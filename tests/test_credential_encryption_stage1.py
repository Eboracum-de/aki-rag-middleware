from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from rag.credential_store import CredentialStore, scope_identity
from rag.secret_crypto import ENCRYPTED_PREFIX, generate_master_key


def _prepare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, mode: str = "required") -> tuple[Path, Path]:
    key = tmp_path / "master.key"
    generate_master_key(key, mode=0o600)
    monkeypatch.setenv("RAG_CREDENTIAL_MASTER_KEY_FILE", str(key))
    monkeypatch.setenv("RAG_CREDENTIAL_ENCRYPTION", mode)
    db = tmp_path / "users.sqlite"
    return db, key


def test_credentials_are_encrypted_at_rest_and_decrypted_for_callers(monkeypatch, tmp_path):
    db, _ = _prepare(monkeypatch, tmp_path)
    store = CredentialStore(db)
    store.set_credential("client::u1", "nextcloud", "u1", "top-secret", server="https://nc.example")
    with sqlite3.connect(db) as con:
        raw = con.execute("select secret from credentials").fetchone()[0]
    assert raw.startswith(ENCRYPTED_PREFIX)
    assert "top-secret" not in raw
    assert store.get_credential("client::u1", "nextcloud").secret == "top-secret"


def test_aad_prevents_ciphertext_copy_between_owners(monkeypatch, tmp_path):
    db, _ = _prepare(monkeypatch, tmp_path)
    store = CredentialStore(db)
    store.set_credential("client::u1", "nextcloud", "u1", "secret-one")
    store.set_credential("client::u2", "nextcloud", "u2", "secret-two")
    with sqlite3.connect(db) as con:
        one = con.execute("select secret from credentials where rag_user_id='client::u1'").fetchone()[0]
        con.execute("update credentials set secret=? where rag_user_id='client::u2'", (one,))
    with pytest.raises(RuntimeError, match="decryption/authentication"):
        store.get_credential("client::u2", "nextcloud")


def test_login_flow_poll_token_is_encrypted(monkeypatch, tmp_path):
    db, _ = _prepare(monkeypatch, tmp_path)
    store = CredentialStore(db)
    flow_id = store.create_nextcloud_flow("client::u1", "https://nc/poll", "poll-secret", "https://nc/login")
    with sqlite3.connect(db) as con:
        raw = con.execute("select poll_token from nextcloud_login_flows where flow_id=?", (flow_id,)).fetchone()[0]
    assert raw.startswith(ENCRYPTED_PREFIX)
    assert store.get_nextcloud_flow(flow_id)["poll_token"] == "poll-secret"


def test_plaintext_migration_is_in_place(monkeypatch, tmp_path):
    db = tmp_path / "users.sqlite"
    monkeypatch.setenv("RAG_CREDENTIAL_ENCRYPTION", "disabled")
    old = CredentialStore(db)
    old.set_credential("u1", "nextcloud", "u1", "legacy-secret")
    flow_id = old.create_nextcloud_flow("u1", "https://nc/poll", "legacy-token", "https://nc/login")

    key = tmp_path / "master.key"
    generate_master_key(key, mode=0o600)
    monkeypatch.setenv("RAG_CREDENTIAL_MASTER_KEY_FILE", str(key))
    monkeypatch.setenv("RAG_CREDENTIAL_ENCRYPTION", "required")
    secure = CredentialStore(db)
    changed = secure.migrate_plaintext_secrets()
    assert changed == {"credentials": 1, "flows": 1, "curation_sessions": 0}
    assert secure.get_credential("u1", "nextcloud").secret == "legacy-secret"
    assert secure.get_nextcloud_flow(flow_id)["poll_token"] == "legacy-token"
    assert secure.verify_secret_encryption()["ok"] is True


def test_required_mode_rejects_plaintext_reads_before_migration(monkeypatch, tmp_path):
    db = tmp_path / "users.sqlite"
    monkeypatch.setenv("RAG_CREDENTIAL_ENCRYPTION", "disabled")
    CredentialStore(db).set_credential("u1", "nextcloud", "u1", "legacy")
    key = tmp_path / "master.key"
    generate_master_key(key, mode=0o600)
    monkeypatch.setenv("RAG_CREDENTIAL_MASTER_KEY_FILE", str(key))
    monkeypatch.setenv("RAG_CREDENTIAL_ENCRYPTION", "required")
    with pytest.raises(RuntimeError, match="plaintext credential"):
        CredentialStore(db).get_credential("u1", "nextcloud")


def test_identity_migration_reencrypts_aad(monkeypatch, tmp_path):
    db, _ = _prepare(monkeypatch, tmp_path)
    store = CredentialStore(db)
    store.set_credential("legacy-user", "nextcloud", "legacy-user", "secret")
    flow_id = store.create_nextcloud_flow("legacy-user", "https://nc/poll", "token", "https://nc/login")
    assert store.migrate_legacy_identities("frontend") == 1
    assert store.get_credential("frontend::legacy-user", "nextcloud").secret == "secret"
    assert store.get_nextcloud_flow(flow_id)["rag_user_id"] == "frontend::legacy-user"
    assert store.get_nextcloud_flow(flow_id)["poll_token"] == "token"


def test_mail_secret_is_separate_from_account_configuration(monkeypatch, tmp_path):
    db, _ = _prepare(monkeypatch, tmp_path)
    store = CredentialStore(db)
    user = store.ensure_canonical_user("https://nc.example", "alice")
    account = store.save_mail_account(
        user.canonical_user_id, host="imap.example", username="alice", target_path="RAG/Mail"
    )
    assert account.has_secret is False
    account = store.set_mail_secret(account.account_id, "imap-secret")
    assert account.has_secret is True
    updated = store.save_mail_account(
        user.canonical_user_id, account_id=account.account_id, host="imap2.example", username="alice", target_path="RAG/Mail"
    )
    assert updated.has_secret is True
    assert store.get_mail_secret(updated).secret == "imap-secret"


def test_release_installer_provisions_encryption_contract():
    root = Path(__file__).resolve().parents[1]
    installer = (root / "install" / "profiles" / "install-standard.sh").read_text(encoding="utf-8")
    req = (root / "requirements.txt").read_text(encoding="utf-8")
    runtime_example = (root / "install" / "runtime.env.example").read_text(encoding="utf-8")
    assert "cryptography>=42,<47" in req
    assert "RAG_CREDENTIAL_MASTER_KEY_FILE" in installer
    assert "RAG_CREDENTIAL_ENCRYPTION=required" in installer
    assert "rag.secret_admin" in installer
    assert "RAG_CREDENTIAL_ENCRYPTION=required" in runtime_example


def test_admin_template_does_not_mix_mail_config_and_password():
    root = Path(__file__).resolve().parents[1]
    template = (root / "rag" / "templates" / "admin" / "user.html").read_text(encoding="utf-8")
    assert "admin_user_mail_credential" in template
    # Password input exists only in the dedicated credential form, not in the main mail config form.
    mail_form = template.split("admin_user_mail'", 1)[1].split("</form>", 1)[0]
    assert 'type="password"' not in mail_form
    assert "Credential ersetzen" in template


def test_security_page_never_renders_secret_values():
    root = Path(__file__).resolve().parents[1]
    template = (root / "rag" / "templates" / "admin" / "security.html").read_text(encoding="utf-8")
    assert "item.configured" in template
    assert "item.value" not in template
    assert "secret_status.master_key.path" in template


def test_curation_session_secret_is_encrypted_and_permission_scoped(monkeypatch, tmp_path):
    db, _ = _prepare(monkeypatch, tmp_path)
    store = CredentialStore(db)
    user = store.ensure_canonical_user("https://nc.example", "alice")
    with pytest.raises(PermissionError):
        store.create_curation_session(
            canonical_user_id=user.canonical_user_id,
            nextcloud_server="https://nc.example",
            nextcloud_login="alice",
            app_password="temporary-app-secret",
            lifetime_seconds=7200,
        )

    assert store.set_findings_curation_enabled(user.canonical_user_id, True)
    token, session = store.create_curation_session(
        canonical_user_id=user.canonical_user_id,
        nextcloud_server="https://nc.example",
        nextcloud_login="alice",
        app_password="temporary-app-secret",
        lifetime_seconds=7200,
    )
    assert session.app_password == "temporary-app-secret"
    assert session.csrf_token
    assert session.expires_at > session.created_at
    with sqlite3.connect(db) as con:
        raw = con.execute(
            "select session_id_hash,app_password from curation_sessions"
        ).fetchone()
    assert raw[0] != token
    assert raw[1].startswith(ENCRYPTED_PREFIX)
    assert "temporary-app-secret" not in raw[1]
    assert store.get_curation_session(token, touch=False).app_password == "temporary-app-secret"
    status = store.secret_security_status()
    assert status["curation_sessions_total"] == 1
    assert status["curation_sessions_plaintext"] == 0


def test_curation_session_absolute_expiry_does_not_slide(monkeypatch, tmp_path):
    db, _ = _prepare(monkeypatch, tmp_path)
    store = CredentialStore(db)
    user = store.ensure_canonical_user("https://nc.example", "alice")
    store.set_findings_curation_enabled(user.canonical_user_id, True)
    token, session = store.create_curation_session(
        canonical_user_id=user.canonical_user_id,
        nextcloud_server="https://nc.example",
        nextcloud_login="alice",
        app_password="temporary-app-secret",
        lifetime_seconds=7200,
    )
    expires = session.expires_at
    touched = store.get_curation_session(token, touch=True)
    assert touched is not None
    assert touched.expires_at == expires


def test_security_admin_lists_internal_trust_zone_keys_without_values():
    root = Path(__file__).resolve().parents[1]
    admin = (root / "rag" / "admin_ui.py").read_text(encoding="utf-8")
    template = (root / "rag" / "templates" / "admin" / "security.html").read_text(encoding="utf-8")
    assert '"RAG_INTERNAL_API_KEY"' in admin
    assert '"RAG_PROVIDER_INTERNAL_KEY"' in admin
    assert "{{ item.name }}" in template
    assert "{{ item.value }}" not in template
