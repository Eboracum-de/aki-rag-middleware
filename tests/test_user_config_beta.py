from pathlib import Path

import yaml

from rag.credential_store import CredentialStore, scope_identity
from rag.runtime_validation import validate_security_config


def test_canonical_user_is_shared_across_trusted_frontend_bindings(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    a = scope_identity("frontend-a", "same-external-id")
    b = scope_identity("frontend-b", "other-external-id")
    ua = store.bind_identity(a, "https://cloud.example/", "alice")
    ub = store.bind_identity(b, "https://CLOUD.EXAMPLE", "alice")
    assert ua.canonical_user_id == ub.canonical_user_id
    assert len(store.list_bindings(ua.canonical_user_id)) == 2


def test_nextcloud_credentials_remain_frontend_scoped(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    a = scope_identity("frontend-a", "same-user")
    b = scope_identity("frontend-b", "same-user")
    canonical = store.bind_identity(a, "https://cloud.example", "alice")
    store.bind_identity(b, "https://cloud.example", "alice")
    store.set_credential(a, "nextcloud", "alice", "secret-a", server="https://cloud.example")
    assert store.get_credential(a, "nextcloud").secret == "secret-a"
    assert store.get_credential(b, "nextcloud") is None
    assert store.get_nextcloud_credential_for_canonical_user(canonical.canonical_user_id).secret == "secret-a"


def test_mail_schema_is_one_to_many_while_secrets_use_credential_store(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    user = store.ensure_canonical_user("https://cloud.example", "alice")
    first = store.save_mail_account(
        user.canonical_user_id,
        name="private",
        host="imap.example",
        username="alice@example.org",
        password="mail-secret-1",
        target_path="RAG/Mail/private",
        mailboxes=["INBOX", "Sent"],
    )
    second = store.save_mail_account(
        user.canonical_user_id,
        name="office",
        host="imap.office.example",
        username="alice@office.example",
        password="mail-secret-2",
        target_path="RAG/Mail/office",
    )
    rows = store.list_mail_accounts(user.canonical_user_id)
    assert {row.account_id for row in rows} == {first.account_id, second.account_id}
    assert store.get_mail_secret(first).secret == "mail-secret-1"
    assert store.get_mail_secret(second).secret == "mail-secret-2"


def test_web_target_is_canonical_user_setting(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    a = scope_identity("frontend-a", "u1")
    b = scope_identity("frontend-b", "u9")
    user = store.bind_identity(a, "https://cloud.example", "alice")
    store.bind_identity(b, "https://cloud.example", "alice")
    store.set_web_settings(user.canonical_user_id, enabled=True, archive_enabled=True, target_path="Research/Web")
    assert store.get_web_settings(store.get_canonical_user_for_identity(a).canonical_user_id).target_path == "Research/Web"
    assert store.get_web_settings(store.get_canonical_user_for_identity(b).canonical_user_id).target_path == "Research/Web"


def test_fresh_beta_config_is_secure_multiuser_default():
    cfg = yaml.safe_load(Path("config.yaml").read_text())
    assert cfg["acl"]["enabled"] is True
    assert cfg["acl"]["identity_mode"] == "credential_store"
    assert cfg["acl"]["verify_tls"] is True
    assert cfg["auth"]["verify_tls"] is True
    assert cfg["carddav"]["verify_tls"] is True
    assert cfg["security"]["allow_insecure_nextcloud"] is False
    assert validate_security_config(cfg) == []


def test_insecure_nextcloud_requires_explicit_escape_hatch(tmp_path: Path):
    cfg = yaml.safe_load(Path("config.yaml").read_text())
    cfg["auth"]["credential_store"] = str(tmp_path / "users.sqlite")
    cfg["acl"]["credential_store"] = str(tmp_path / "users.sqlite")
    cfg["nextcloud"]["base_url"] = "http://cloud.example"
    errors = validate_security_config(cfg)
    assert any("must use HTTPS" in error for error in errors)
    cfg["security"]["allow_insecure_nextcloud"] = True
    assert validate_security_config(cfg) == []


def test_mail_account_id_cannot_be_reassigned_between_canonical_users(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    alice = store.ensure_canonical_user("https://cloud.example", "alice")
    bob = store.ensure_canonical_user("https://cloud.example", "bob")
    account = store.save_mail_account(
        alice.canonical_user_id,
        name="primary",
        host="imap.example",
        username="alice@example.org",
        password="secret",
        target_path="RAG/Mail",
    )
    try:
        store.save_mail_account(
            bob.canonical_user_id,
            account_id=account.account_id,
            name="primary",
            host="imap.example",
            username="bob@example.org",
            password="other",
            target_path="RAG/Mail",
        )
    except ValueError as exc:
        assert "different canonical user" in str(exc)
    else:
        raise AssertionError("mail account ownership could be reassigned")
    assert store.get_mail_account(account.account_id).canonical_user_id == alice.canonical_user_id


def test_web_archive_root_history_survives_target_change(tmp_path: Path):
    import sqlite3
    store = CredentialStore(tmp_path / "users.sqlite")
    user = store.ensure_canonical_user("https://cloud.example", "alice")
    store.set_web_settings(user.canonical_user_id, enabled=True, archive_enabled=True, target_path="Research/Old-Web")
    store.set_web_settings(user.canonical_user_id, enabled=True, archive_enabled=True, target_path="Research/New-Web")
    con = sqlite3.connect(tmp_path / "users.sqlite")
    try:
        roots = {row[0] for row in con.execute("SELECT target_path FROM web_archive_roots")}
    finally:
        con.close()
    assert roots == {"Research/Old-Web", "Research/New-Web"}


def test_deleted_client_purges_frontend_state_but_keeps_canonical_user(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    store.register_client("frontend-a", "x" * 32)
    identity = scope_identity("frontend-a", "alice-ext")
    user = store.bind_identity(identity, "https://cloud.example", "alice")
    store.set_credential(identity, "nextcloud", "alice", "app-secret", server="https://cloud.example")
    store.set_web_settings(user.canonical_user_id, enabled=True, archive_enabled=True, target_path="Research/Web")
    assert store.delete_client("frontend-a") is True
    assert store.get_canonical_user(user.canonical_user_id) is not None
    assert store.get_canonical_user_for_identity(identity) is None
    assert store.get_credential(identity, "nextcloud") is None
    assert store.get_web_settings(user.canonical_user_id).target_path == "Research/Web"


def test_reauth_clears_nextcloud_secret_but_retains_binding(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    identity = scope_identity("frontend-a", "alice-ext")
    user = store.bind_identity(identity, "https://cloud.example", "alice")
    store.set_credential(identity, "nextcloud", "alice", "app-secret", server="https://cloud.example")
    result = store.clear_nextcloud_credentials_for_canonical_user(user.canonical_user_id)
    assert result["credentials_deleted"] == 1
    assert store.get_canonical_user_for_identity(identity).canonical_user_id == user.canonical_user_id
    assert store.get_credential(identity, "nextcloud") is None


def test_contact_seed_settings_are_nextcloud_user_settings(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    a = scope_identity("frontend-a", "u1")
    b = scope_identity("frontend-b", "u9")
    user = store.bind_identity(a, "https://cloud.example", "alice")
    store.bind_identity(b, "https://cloud.example", "alice")

    settings = store.set_contact_sync_settings(
        user.canonical_user_id,
        enabled=True,
        include_addressbooks=["Kontakte", "Geschaeftlich", "Kontakte"],
        exclude_addressbooks=["Privat"],
    )
    assert settings.include_addressbooks == ("Kontakte", "Geschaeftlich")
    assert settings.exclude_addressbooks == ("Privat",)
    assert store.get_contact_sync_settings(
        store.get_canonical_user_for_identity(b).canonical_user_id
    ).include_addressbooks == ("Kontakte", "Geschaeftlich")

    status = store.record_contact_sync_result(
        user.canonical_user_id,
        status="completed",
        contacts_seen=76,
        contacts_written=76,
    )
    assert status.last_status == "completed"
    assert status.contacts_seen == 76
    assert status.contacts_written == 76
    assert status.last_sync_at is not None


def test_contact_seed_lookup_uses_human_nextcloud_login(tmp_path: Path):
    from rag.carddav_sync import resolve_nextcloud_user

    store = CredentialStore(tmp_path / "users.sqlite")
    first = store.ensure_canonical_user("https://cloud-a.example", "alice")
    assert resolve_nextcloud_user(store, "alice").canonical_user_id == first.canonical_user_id
    store.ensure_canonical_user("https://cloud-b.example", "alice")
    try:
        resolve_nextcloud_user(store, "alice")
    except ValueError as exc:
        assert "--server" in str(exc)
    else:
        raise AssertionError("ambiguous Nextcloud login must require --server")
    resolved = resolve_nextcloud_user(store, "alice", server="https://cloud-b.example")
    assert resolved.nextcloud_server == "https://cloud-b.example"


def test_contact_sync_without_login_flow_credential_is_clean_noop(tmp_path: Path):
    from rag.carddav_sync import sync_for_canonical_user

    store = CredentialStore(tmp_path / "users.sqlite")
    user = store.ensure_canonical_user("https://cloud.example", "alice")
    summary = sync_for_canonical_user({}, store, user)
    assert summary["status"] == "skipped"
    assert summary["reason"] == "nextcloud_credential_missing"
    assert summary["contacts_written"] == 0
