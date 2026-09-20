from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parent.parent


def _standard_installer_text() -> str:
    return (ROOT / "install/profiles/install-standard.sh").read_text()




def test_unified_installer_dispatches_profiles():
    installer = (ROOT / "install/install.sh").read_text()
    assert '--profile' in installer
    assert 'install-standard.sh' in installer
    assert 'install-super-light.sh' in installer
    super_impl = (ROOT / "install/profiles/install-super-light.sh").read_text()
    assert 'Host Python required:    no' in super_impl
    assert 'WITH_OPENWEBUI=0' in super_impl
    assert 'WITH_PROXY=0' in super_impl


def test_super_light_compose_is_legacy_compatible_shape():
    cfg = yaml.safe_load((ROOT / "install/super-light/docker-compose.yml").read_text())
    assert cfg["version"] == "2.4"
    services = cfg["services"]
    assert "proxy" not in services
    assert "openwebui" not in services
    assert services["provider"]["depends_on"] == ["api"]


def test_super_light_container_build_does_not_require_root_provider_example():
    dockerfile = (ROOT / "install/super-light/Dockerfile.provider").read_text()
    assert "COPY provider.env.example" not in dockerfile
    assert "PIP_ROOT_USER_ACTION=ignore" in dockerfile


def test_super_light_plan_reports_disk_and_keeps_openwebui_opt_in():
    installer = (ROOT / "install/profiles/install-super-light.sh").read_text()
    assert "Estimated disk use:" in installer
    assert "not pulled/not started" in installer
    assert '[[ $WITH_OPENWEBUI -eq 1 ]] && SERVICES+=(openwebui)' in installer

def test_compose_minimal_default_is_proxy_only():
    cfg = yaml.safe_load((ROOT / "install/docker-compose.yml").read_text())
    services = cfg["services"]
    default_services = [name for name, spec in services.items() if not spec.get("profiles")]
    assert default_services == ["proxy"]
    assert services["qdrant"]["profiles"] == ["qdrant"]
    assert services["neo4j"]["profiles"] == ["neo4j"]


def test_bind_mounts_are_selinux_relabelled():
    cfg = yaml.safe_load((ROOT / "install/docker-compose.yml").read_text())
    proxy_mounts = cfg["services"]["proxy"]["volumes"]
    assert all(m.endswith(":ro,z") for m in proxy_mounts)



def test_optional_external_services_are_not_bundled():
    cfg = yaml.safe_load((ROOT / "install/docker-compose.yml").read_text())
    services = cfg["services"]
    assert "searxng" not in services
    assert "valkey" not in services
    assert "ollama" not in services
    installer = _standard_installer_text()
    assert "--with-searxng was removed from the bundled stack" in installer
    assert "Bundled Ollama is not part of this release" in installer
    assert "WITH_OLLAMA" not in installer


def test_evidence_controller_is_off_by_default():
    env = (ROOT / "provider.env.example").read_text()
    assert "EVIDENCE_DECISION_MODE=off" in env


def test_openwebui_connection_forwards_stable_user_identity():
    cfg = yaml.safe_load((ROOT / "install/docker-compose.yml").read_text())
    env = cfg["services"]["openwebui"]["environment"]
    assert env["ENABLE_FORWARD_USER_INFO_HEADERS"] == "false"
    assert "X-OpenWebUI-User-Id" in env["OPENAI_API_CONFIGS"]
    assert "{{USER_ID}}" in env["OPENAI_API_CONFIGS"]


def test_openwebui_root_assets_are_not_rate_limited():
    nginx = (ROOT / "install/nginx/nginx-openwebui.conf").read_text()
    root_block = nginx.split("location / {", 1)[1].split("}", 1)[0]
    assert "limit_req" not in root_block


def test_rag_api_explicitly_forwards_test_identity_header():
    for name in ("nginx.conf", "nginx-openwebui.conf"):
        nginx = (ROOT / "install/nginx" / name).read_text()
        assert "proxy_set_header X-RAG-User-ID $http_x_rag_user_id;" in nginx


def test_openwebui_provider_config_is_installer_authoritative():
    cfg = yaml.safe_load((ROOT / "install/docker-compose.yml").read_text())
    env = cfg["services"]["openwebui"]["environment"]
    assert env["ENABLE_PERSISTENT_CONFIG"] == "false"
    assert env["BYPASS_MODEL_ACCESS_CONTROL"] == "true"
    assert env["OPENAI_API_KEY"] == "${OPENWEBUI_PROVIDER_API_KEY:-}"


def test_sync_graph_discovery_is_opt_in_by_default():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    assert cfg["sync"]["graph_queue"]["enabled"] is False
    assert "structural_relations" not in cfg["graph_retrieval"]
    sync_source = (ROOT / "rag/sync.py").read_text()
    assert 'cfg_get(cfg, "sync.graph_queue.enabled", default=False)' in sync_source


def test_optional_relation_date_properties_use_dynamic_access():
    graph_source = (ROOT / "rag/graph.py").read_text()
    assert "c.evidence_date_confidence AS evidence_date_confidence" not in graph_source
    assert "properties(c)['evidence_date_confidence'] AS evidence_date_confidence" in graph_source


def test_graph_answer_hook_is_cited_only_not_sync_coupled():
    provider = (ROOT / "rag/openai_provider.py").read_text()
    assert provider.count('evidence_action="answer_cited"') == 2
    assert "explicit_cited_results = _cited_results(answer, results)" in provider


def test_docker_and_ml_beta_dependencies_are_pinned():
    cfg = yaml.safe_load((ROOT / "install/docker-compose.yml").read_text())
    images = {name: spec["image"] for name, spec in cfg["services"].items()}
    assert "latest" not in "\n".join(images.values())
    assert set(images) == {"proxy", "qdrant", "neo4j", "openwebui"}
    assert all("@sha256:" in image for image in images.values())
    assert "v1.19.0@sha256:" in images["qdrant"]
    assert "5.26.29-community@sha256:" in images["neo4j"]
    assert "v0.11.0@sha256:" in images["openwebui"]
    lock = yaml.safe_load((ROOT / "versions.lock.yaml").read_text())
    for name in ("nginx", "qdrant", "neo4j", "openwebui"):
        assert lock["docker"][name]["ref"].endswith(lock["docker"][name]["digest"])
        assert "@sha256:" in lock["docker"][name]["ref"]
    req = (ROOT / "requirements.txt").read_text()
    assert "transformers==4.57.6" in req
    installer = _standard_installer_text()
    assert "torch==2.13.0+cpu" in installer
    assert "import torch.export" in installer


def test_provider_auth_scopes_user_id_to_authenticated_client():
    provider = (ROOT / "rag/openai_provider.py").read_text()
    assert "authenticate_client(api_key)" in provider
    assert "scope_identity(client_id" in provider
    assert "authorization != f\"Bearer {PROVIDER_API_KEY}\"" not in provider


def test_beta_defaults_are_multiuser_and_tls_verified():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    assert cfg["acl"]["enabled"] is True
    assert cfg["acl"]["identity_mode"] == "credential_store"
    assert cfg["acl"]["verify_tls"] is True
    assert cfg["auth"]["verify_tls"] is True
    assert cfg["carddav"]["verify_tls"] is True
    installer = _standard_installer_text()
    assert "MULTI_USER=1" in installer
    assert "--single-user" in installer
    assert "--acl-off" in installer


def test_per_user_mail_and_web_are_not_shipped_in_yaml():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    web = yaml.safe_load((ROOT / "web.yaml").read_text())
    assert "accounts" not in (cfg.get("mail") or {})
    assert "webdav" not in (cfg.get("mail") or {})
    assert "root" not in (web.get("archive") or {})


def test_installer_ships_per_user_mail_worker_without_global_mail_secret_envs():
    installer = _standard_installer_text()
    runtime_example = (ROOT / "install/runtime.env.example").read_text()
    assert "start-mail-worker.sh" in installer
    assert "rag-mail-worker" in installer
    assert "start-sync-worker.sh" in installer
    assert "rag-sync-worker" in installer
    assert "MAIL_IMAP_USERNAME" not in installer
    assert "MAIL_IMAP_PASSWORD" not in installer
    assert "MAIL_IMAP_USERNAME" not in runtime_example
    assert "MAIL_IMAP_PASSWORD" not in runtime_example


def test_proxy_defaults_to_https_and_reserves_root_for_ui():
    for name in ("nginx.conf", "nginx-openwebui.conf"):
        nginx = (ROOT / "install/nginx" / name).read_text()
        assert "listen 443 ssl default_server;" in nginx
        assert "return 308 https://$host$request_uri;" in nginx
        assert "location = /proxy-health" in nginx
        assert "location /rag-admin/" in nginx
        assert "location /admin/" not in nginx
    no_ui = (ROOT / "install/nginx/nginx.conf").read_text()
    assert "return 302 /rag-admin/;" in no_ui
    ui = (ROOT / "install/nginx/nginx-openwebui.conf").read_text()
    assert "proxy_pass http://127.0.0.1:3000;" in ui


def test_proxy_mounts_bootstrap_tls_material():
    cfg = yaml.safe_load((ROOT / "install/docker-compose.yml").read_text())
    mounts = cfg["services"]["proxy"]["volumes"]
    assert "./nginx/tls:/etc/nginx/tls:ro,z" in mounts
    installer = _standard_installer_text()
    assert "openssl req -x509" in installer
    assert "Firewall is NOT modified" in installer


def test_elasticsearch_password_is_env_referenced_not_yaml_secret():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    es = cfg["elasticsearch"]
    assert es["password_env"] == "ELASTICSEARCH_PASSWORD"
    assert "password" not in es
    assert es["verify_tls"] is True
    runtime = (ROOT / "install/runtime.env.example").read_text()
    assert "ELASTICSEARCH_PASSWORD=" in runtime


def test_bundled_openwebui_uses_loopback_provider_without_tls_coupling():
    cfg = yaml.safe_load((ROOT / "install/docker-compose.yml").read_text())
    spec = cfg["services"]["openwebui"]
    env = spec["environment"]
    assert spec["network_mode"] == "host"
    assert "ports" not in spec
    assert "extra_hosts" not in spec
    assert env["HOST"] == "127.0.0.1"
    assert env["PORT"] == "${OPENWEBUI_PORT:-3000}"
    assert env["OPENAI_API_BASE_URL"] == "http://127.0.0.1:8766/v1"
    # Do not weaken OpenWebUI's global outbound TLS verification merely to
    # reach the local provider.
    assert "AIOHTTP_CLIENT_SESSION_SSL" not in env


def test_rag_api_root_redirects_to_health():
    for name in ("nginx.conf", "nginx-openwebui.conf"):
        nginx = (ROOT / "install/nginx" / name).read_text()
        assert "location = /rag-api {" in nginx
        assert "location = /rag-api/ {" in nginx
        assert nginx.count("return 302 /rag-api/health;") >= 2


def test_openwebui_followup_helper_is_suppressed_without_llm():
    provider = (ROOT / "rag/openai_provider.py").read_text()
    assert 'if auxiliary_kind == "ui:follow_ups":' in provider
    assert "return _static_response('{\"follow_ups\":[]}'" in provider


def test_installer_waits_for_bundled_ui_and_proxy_health():
    installer = _standard_installer_text()
    status = (ROOT / "status.sh").read_text()
    smoke = (ROOT / "install/smoke-test.sh").read_text()
    assert 'Waiting for OpenWebUI on 127.0.0.1:${OPENWEBUI_PORT:-3000}' in installer
    assert 'http://127.0.0.1:${OPENWEBUI_PORT:-3000}/health' in installer
    assert 'https://127.0.0.1/proxy-health' in installer
    assert 'LOCAL_OPENWEBUI=0' in status
    assert 'openwebui "${OPENWEBUI_PORT:-3000}"' in status
    assert 'OpenWebUI HTTP (127.0.0.1:${OPENWEBUI_PORT:-3000})' in smoke


def test_sync_and_reset_do_not_use_qdrant_filter_delete():
    sync_source = (ROOT / "rag/sync.py").read_text()
    reset_source = (ROOT / "reset-rag.sh").read_text()
    assert 'json={"filter": {"must": [{"key": "document_id"' not in sync_source
    assert '"filter"' not in sync_source.split("def qdrant_delete_chunk_range", 1)[1].split("def qdrant_upsert", 1)[0]
    assert '/points/delete?wait=true' not in reset_source
    assert '-X DELETE' in reset_source


def test_periodic_sync_worker_wraps_existing_rag_sync():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    worker = cfg["sync_worker"]
    assert worker["enabled"] is True
    assert worker["poll_interval_seconds"] >= 60
    assert worker["max_documents"] == 0
    assert worker["enqueue_graph"] is False
    script = (ROOT / "start-sync-worker.sh").read_text()
    assert "-m rag.sync" in script
    assert "--max-documents" in script
    assert "--no-enqueue-graph" in script



def test_public_baseline_repository_hygiene():
    assert (ROOT / "rag/version.py").read_text().strip() == 'VERSION = "0.8.5-rc4.1"'
    assert not (ROOT / "provider.env").exists()
    assert "provider.env" in (ROOT / ".gitignore").read_text().splitlines()
    assert (ROOT / "CHANGELOG.md").exists()
    assert (ROOT / "SECURITY.md").exists()
    assert (ROOT / "docs/ARCHITECTURE.md").exists()
    assert not list(ROOT.glob("MIGRATION-*.md"))
    assert not list(ROOT.glob("DESIGN-*.md"))


def test_installer_creates_local_provider_env_from_example():
    installer = _standard_installer_text()
    assert 'cp -a "$SOURCE_DIR/provider.env.example" "$PREFIX/provider.env"' in installer
    assert "provider.env.example README.md CHANGELOG.md SECURITY.md" in installer


def test_admin_navigation_uses_four_primary_areas_and_graph_subnav():
    base = (ROOT / "rag/templates/admin/base.html").read_text()
    for label in ("Übersicht", "Benutzer", "Graph", "Sicherheit"):
        assert f">{label}</a>" in base
    assert ">Merge-Kandidaten</a>" in base
    assert ">Beobachtungen</a>" in base
    assert ">Relationen</a>" in base
    assert ">Kontaktquellen</a>" in base
    assert ">Graph-Import / Queue</a>" in base
    assert ">/health</a>" not in base


def test_installer_never_executes_state_from_unrecognized_prefix(tmp_path):
    prefix = tmp_path / "foreign"
    state_dir = prefix / "install"
    state_dir.mkdir(parents=True)
    sentinel = tmp_path / "executed"
    (state_dir / "install-state.env").write_text(
        "DEPLOYMENT_PROFILE=standard\n"
        f"LOCAL_NEO4J=$(touch {sentinel})\n"
    )

    result = subprocess.run(
        ["bash", str(ROOT / "install/profiles/install-standard.sh"), "--plan", "--prefix", str(prefix)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "not recognized as an AKI RAG installation" in result.stderr
    assert not sentinel.exists()


def test_installer_parses_recognized_state_as_data_on_rerun(tmp_path):
    prefix = tmp_path / "aki"
    (prefix / "install").mkdir(parents=True)
    (prefix / "rag").mkdir()
    (prefix / "config.yaml").write_text("{}\n")
    (prefix / ".aki-rag-installation").write_text(
        "AKI_RAG_INSTALLATION=1\nDEPLOYMENT_PROFILE=standard\nDEPLOYMENT_MODE=native\n"
    )
    (prefix / "install/install-state.env").write_text(
        "LOCAL_QDRANT=0\n"
        "LOCAL_NEO4J=1\n"
        "LOCAL_OPENWEBUI=0\n"
        "LOCAL_PROXY=1\n"
        "PROXY_BASIC_AUTH_STATE=1\n"
        "MALICIOUS=$(touch /tmp/aki-rag-state-must-not-run)\n"
    )

    result = subprocess.run(
        ["bash", str(ROOT / "install/profiles/install-standard.sh"), "--plan", "--prefix", str(prefix)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Neo4j:                   install/start" in result.stdout
    assert 'source "$PREFIX/install/install-state.env"' not in _standard_installer_text()


def test_super_light_rerun_preserves_admin_credentials_and_proxy_identity():
    script = (ROOT / "install/profiles/install-super-light.sh").read_text()
    assert 'ADMIN_PASSWORD="$(sed -n \'s/^RAG_ADMIN_PASSWORD=//p\'' in script
    assert 'if [[ -z "$ADMIN_PASSWORD" || "$ADMIN_PASSWORD" == "replace-me" ]]' in script
    assert 'printf \'%s:%s\\n\' "${ADMIN_USER:-admin}"' in script
    assert "printf 'admin:%s\\n'" not in script
