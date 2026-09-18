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
