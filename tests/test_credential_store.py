from pathlib import Path
from rag.credential_store import CredentialStore


def test_credential_store_roundtrip(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    store.set_credential("u1", "nextcloud", "alice", "app-secret", server="https://cloud.example")
    row = store.get_credential("u1", "nextcloud")
    assert row is not None
    assert row.username == "alice"
    assert row.secret == "app-secret"
    assert row.server == "https://cloud.example"
    assert store.delete_credential("u1", "nextcloud") is True
    assert store.get_credential("u1", "nextcloud") is None


def test_nextcloud_flow_storage(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    flow_id = store.create_nextcloud_flow("u1", "https://cloud/poll", "tok", "https://cloud/login")
    row = store.get_nextcloud_flow(flow_id)
    assert row is not None
    assert row["rag_user_id"] == "u1"
    assert row["poll_token"] == "tok"
    store.delete_nextcloud_flow(flow_id)
    assert store.get_nextcloud_flow(flow_id) is None


def test_recent_nextcloud_flow_is_reused_per_identity(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    first = store.create_nextcloud_flow("u1", "https://cloud/poll1", "tok1", "https://cloud/login1")
    second = store.create_nextcloud_flow("u1", "https://cloud/poll2", "tok2", "https://cloud/login2")
    store.create_nextcloud_flow("u2", "https://cloud/poll3", "tok3", "https://cloud/login3")

    row = store.get_recent_nextcloud_flow("u1", max_age_seconds=3600)
    assert row is not None
    assert row["flow_id"] == second
    assert row["flow_id"] != first

    assert store.delete_nextcloud_flows_for_user("u1") == 2
    assert store.get_recent_nextcloud_flow("u1", max_age_seconds=3600) is None


def test_provider_client_registry_and_scoped_identity(tmp_path: Path):
    from rag.credential_store import scope_identity
    store = CredentialStore(tmp_path / "users.sqlite")
    key = store.create_client("openwebui-local", name="Local OpenWebUI")
    assert store.authenticate_client(key, touch=False).client_id == "openwebui-local"
    assert store.authenticate_client("wrong-key", touch=False) is None
    assert scope_identity("openwebui-local", "u-123") == "openwebui-local::u-123"


def test_legacy_bindings_migrate_once_to_client_scope(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    store.set_credential("legacy-user", "nextcloud", "alice", "secret")
    assert store.migrate_legacy_identities("openwebui-local") == 1
    assert store.get_credential("legacy-user", "nextcloud") is None
    migrated = store.get_credential("openwebui-local::legacy-user", "nextcloud")
    assert migrated is not None and migrated.username == "alice"
    assert store.migrate_legacy_identities("openwebui-local") == 0


def test_client_scopes_cannot_reuse_each_others_nextcloud_binding(tmp_path: Path):
    from rag.credential_store import scope_identity
    store = CredentialStore(tmp_path / "users.sqlite")
    a = scope_identity("frontend-a", "same-user")
    b = scope_identity("frontend-b", "same-user")
    store.set_credential(a, "nextcloud", "alice", "app-secret")
    assert store.get_credential(a, "nextcloud") is not None
    assert store.get_credential(b, "nextcloud") is None


def test_user_sunaq_model_settings_roundtrip_and_validate_default(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    user = store.ensure_canonical_user("https://cloud.example", "alice")

    assert store.get_model_settings(user.canonical_user_id) is None

    settings = store.set_model_settings(
        user.canonical_user_id,
        default_model_id="sunaq-standard",
        allowed_model_ids=["sunaq-standard", "sunaq-thorough", "sunaq-standard"],
    )
    assert settings.default_model_id == "sunaq-standard"
    assert settings.allowed_model_ids == ("sunaq-standard", "sunaq-thorough")

    loaded = store.get_model_settings(user.canonical_user_id)
    assert loaded is not None
    assert loaded.default_model_id == "sunaq-standard"
    assert loaded.allowed_model_ids == ("sunaq-standard", "sunaq-thorough")

    try:
        store.set_model_settings(
            user.canonical_user_id,
            default_model_id="sunaq-thorough",
            allowed_model_ids=["sunaq-standard"],
        )
        assert False, "disallowed default must fail"
    except ValueError as exc:
        assert "default SunaQ model" in str(exc)

    assert store.clear_model_settings(user.canonical_user_id) is True
    assert store.get_model_settings(user.canonical_user_id) is None


def test_user_chat_archive_settings_are_single_path_and_validated(tmp_path: Path):
    store = CredentialStore(tmp_path / "users.sqlite")
    user = store.ensure_canonical_user("https://cloud.example", "alice")

    assert store.get_chat_settings(user.canonical_user_id) is None

    settings = store.set_chat_settings(
        user.canonical_user_id,
        target_path="Archiv/SunaQ",
    )
    assert settings.enabled is True
    assert settings.target_path == "Archiv/SunaQ"
    assert store.get_chat_settings(user.canonical_user_id).target_path == "Archiv/SunaQ"

    disabled = store.set_chat_settings(
        user.canonical_user_id,
        enabled=False,
        target_path="Archiv/SunaQ",
    )
    assert disabled.enabled is False

    defaulted = store.set_chat_settings(user.canonical_user_id, target_path="")
    assert defaulted.target_path == "SunaQ-Chats"

    with store._connect() as con:
        roots = {
            row[0]
            for row in con.execute(
                "SELECT target_path FROM chat_archive_roots ORDER BY target_path"
            ).fetchall()
        }
    assert roots == {"Archiv/SunaQ", "SunaQ-Chats"}

    for invalid in ("../AKI-Chats", "foo/../bar", "foo\\bar", "foo//bar"):
        try:
            store.set_chat_settings(user.canonical_user_id, target_path=invalid)
            assert False, f"invalid chat archive path accepted: {invalid}"
        except ValueError:
            pass

def test_chat_settings_schema_migrates_existing_rows_enabled_by_default(tmp_path: Path):
    import sqlite3

    db = tmp_path / "users.sqlite"
    con = sqlite3.connect(db)
    try:
        con.execute(
            "CREATE TABLE user_chat_settings ("
            "canonical_user_id TEXT PRIMARY KEY,"
            "target_path TEXT NOT NULL DEFAULT 'SunaQ-Chats',"
            "updated_at REAL NOT NULL)"
        )
        con.execute(
            "INSERT INTO user_chat_settings(canonical_user_id,target_path,updated_at) VALUES(?,?,?)",
            ("legacy-user", "AKI-Chats", 1.0),
        )
        con.commit()
    finally:
        con.close()

    store = CredentialStore(db)
    settings = store.get_chat_settings("legacy-user")
    assert settings is not None
    assert settings.enabled is True
    assert settings.target_path == "AKI-Chats"

