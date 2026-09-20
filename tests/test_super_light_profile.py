from pathlib import Path
import subprocess

import pytest
import yaml

from rag.reranker import Reranker


ROOT = Path(__file__).resolve().parent.parent


def test_super_light_profile_disables_vector_reranker_and_graph_documents():
    cfg = yaml.safe_load((ROOT / "install/super-light/config.super-light.yaml").read_text())
    assert cfg["deployment"]["profile"] == "super-light"
    assert cfg["elasticsearch"]["enabled"] is True
    assert cfg["qdrant"]["enabled"] is False
    assert cfg["sync_worker"]["enabled"] is False
    assert cfg["neo4j"]["enabled"] is True
    assert cfg["entity_resolution"]["enabled"] is True
    assert cfg["graph_retrieval"]["enabled"] is False
    assert cfg["graph_queue"]["enabled"] is False
    assert cfg["graph_queue"]["worker"]["enabled"] is False
    assert cfg["graph_indexer"]["enabled"] is False
    assert cfg["graph_entity_discovery"]["enabled"] is False
    assert cfg["graph_relation_discovery"]["enabled"] is False
    assert cfg["reranker"]["backend"] == "none"


def test_super_light_requirements_have_no_model_or_vector_client_dependencies():
    req = (ROOT / "requirements-super-light.txt").read_text().lower()
    for forbidden in ("qdrant-client", "transformers", "huggingface", "sentencepiece", "torch"):
        assert forbidden not in req
    assert "neo4j" in req


def test_super_light_web_profile_enables_local_playwright():
    web = yaml.safe_load((ROOT / "install/super-light/web.super-light.yaml").read_text())
    renderer = web["archive"]["renderer"]
    assert renderer["enabled"] is True
    assert renderer["url"] == "http://127.0.0.1:8090/render"
    assert renderer["cleanup"]["cookie_consent"] == "accept_all"
    assert renderer["cleanup"]["dismiss_overlays"] is True
    assert renderer["cleanup"]["remove_overlays"] is False


def test_reranker_none_is_explicitly_disabled():
    reranker = Reranker(backend="none")
    reranker.load()
    status = reranker.status()
    assert status["backend"] == "none"
    assert status["disabled_reason"] == "disabled by configuration"
    with pytest.raises(RuntimeError, match="deaktiviert"):
        reranker.score("query", ["document"])


def test_search_skips_reranker_when_disabled(monkeypatch):
    from types import SimpleNamespace
    import rag.search as search

    monkeypatch.setattr(search, "RERANKER_ENABLED", False)
    monkeypatch.setattr(search, "ELASTICSEARCH_ENABLED", True)
    monkeypatch.setattr(search, "RETRIEVAL_SIGNAL_ENABLED", False)
    monkeypatch.setattr(
        search,
        "prepare_entity_context",
        lambda question: {"enabled": False, "entities": [], "elastic_phrase_expansion": [], "error": None},
    )
    monkeypatch.setattr(
        search,
        "create_plan",
        lambda *a, **k: SimpleNamespace(must=["examplehost"], phrases=[], entity_should_phrases=[]),
    )

    def fake_es(question, plan, diagnostics):
        diagnostics.update({"total_hits": 2, "total_relation": "eq", "available": True})
        return [
            {"document_id": "files:1", "title": "a.pdf", "path": "a.pdf", "score": 10.0, "text": "a", "snippet": "a"},
            {"document_id": "files:2", "title": "b.pdf", "path": "b.pdf", "score": 9.0, "text": "b", "snippet": "b"},
        ]

    monkeypatch.setattr(search, "elastic_search", fake_es)
    monkeypatch.setattr(
        search,
        "rerank_results",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("reranker must not run")),
    )

    payload = search.perform_search(
        "examplehost 2025",
        limit=2,
        retrieval_arms={"files"},
        force_unspecific=True,
    )

    assert payload["retrieval_mode"] == "rrf_no_reranker"
    assert payload["reranker_used"] is False
    assert payload["reranker_error"] is None
    assert [item["document_id"] for item in payload["results"]] == ["files:1", "files:2"]


def test_super_light_proxy_htpasswd_is_worker_readable():
    installer = (ROOT / "install" / "profiles" / "install-super-light.sh").read_text(encoding="utf-8")
    assert 'chmod 644 "$PREFIX/install/nginx/htpasswd"' in installer
    assert 'chmod 600 "$PREFIX/install/nginx/htpasswd"' not in installer


def test_super_light_web_capability_is_globally_enabled_but_still_user_gated():
    web = yaml.safe_load((ROOT / "install/super-light/web.super-light.yaml").read_text())
    assert web["enabled"] is True
    assert web["search"]["provider"] == "brave"


def test_super_light_base_compose_does_not_define_optional_openwebui_or_proxy():
    compose = yaml.safe_load((ROOT / "install/super-light/docker-compose.yml").read_text())
    services = compose["services"]
    assert "openwebui" not in services
    assert "proxy" not in services
    assert {"api", "provider", "neo4j", "playwright-renderer"}.issubset(services)


def test_super_light_installer_generates_optional_compose_override():
    installer = (ROOT / "install/profiles/install-super-light.sh").read_text(encoding="utf-8")
    assert 'docker-compose.override.yml' in installer
    assert 'if [[ $WITH_OPENWEBUI -eq 1 ]]' in installer
    assert 'if [[ $WITH_PROXY -eq 1 ]]' in installer
    assert 'compose up -d --remove-orphans' in installer


def test_super_light_marks_dockerized_deployment_mode():
    cfg = yaml.safe_load((ROOT / "install/super-light/config.super-light.yaml").read_text())
    assert cfg["deployment"]["profile"] == "super-light"
    assert cfg["deployment"]["mode"] == "dockerized"


def test_super_light_private_ca_is_baked_into_provider_image():
    dockerfile = (ROOT / "install/super-light/Dockerfile.provider").read_text(encoding="utf-8")
    installer = (ROOT / "install/profiles/install-super-light.sh").read_text(encoding="utf-8")
    assert "--ca-certificate" in installer
    assert "runtime/ca" in installer
    assert "COPY runtime/ca/" in dockerfile
    assert "update-ca-certificates" in dockerfile
    assert "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" in dockerfile
    assert "REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt" in dockerfile


def test_docker_build_context_excludes_runtime_secrets_but_keeps_ca():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "runtime/*" in ignore
    assert "!runtime/ca/" in ignore
    assert "provider.env" in ignore
    assert "runtime.env" in ignore


def test_super_light_retrieval_policy_keeps_es_required_and_document_graph_disabled():
    cfg = yaml.safe_load((ROOT / "install/super-light/config.super-light.yaml").read_text())
    policy = cfg["retrieval_policy"]
    assert policy["internal"] == {
        "files": "required",
        "vector": "disabled",
        "graph": "disabled",
    }
    assert policy["web"] == "planner"
    assert cfg["tls"]["x509_strict"] is False


def test_public_installer_exposes_profile_and_deployment_axes():
    installer = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
    assert "--deployment native|dockerized" in installer
    assert "standard:native" in installer
    assert "super-light:dockerized" in installer


def test_super_light_installer_supports_x509_compatibility_without_disabling_tls():
    installer = (ROOT / "install" / "profiles" / "install-super-light.sh").read_text(encoding="utf-8")
    assert "--x509-strict" in installer
    assert "--no-x509-strict" in installer
    assert "X509_STRICT=0" in installer
    assert "x509_strict: false" in installer
    assert "verify_tls: false" not in installer


def test_super_light_uses_ten_verification_candidates_without_reranker():
    cfg = yaml.safe_load((ROOT / "install/super-light/config.super-light.yaml").read_text())
    assert cfg["retrieval_planner"]["verification_candidate_limit"] == 10
    assert cfg["reranker"]["backend"] == "none"


def test_super_light_renderer_is_shared_landscape_desktop_component():
    compose = yaml.safe_load((ROOT / "install/super-light/docker-compose.yml").read_text())
    service = compose["services"]["playwright-renderer"]
    assert service["build"]["context"] == "../components/playwright-renderer"
    assert "playwright_state:/state" in service["volumes"]
    assert (ROOT / "install/components/playwright-renderer/app/renderer.py").is_file()
    web = yaml.safe_load((ROOT / "install/super-light/web.super-light.yaml").read_text())
    renderer = web["archive"]["renderer"]
    assert renderer["landscape"] is True
    assert renderer["prefer_css_page_size"] is False
    assert renderer["viewport"] == {"width": 1440, "height": 900}
    assert renderer["persist_state"] is True


def test_super_light_contact_cli_executes_in_running_api_container():
    helper = (ROOT / "install/super-light/contacts.sh").read_text(encoding="utf-8")
    seed = (ROOT / "install/super-light/seed-carddav.sh").read_text(encoding="utf-8")
    assert 'exec -T api python -m rag.contacts' in helper
    assert 'run --rm --no-deps api' not in helper
    assert './contacts.sh sync' in seed


def test_super_light_smoke_test_does_not_require_host_venv_or_qdrant():
    smoke = (ROOT / "install" / "smoke-test.sh").read_text(encoding="utf-8")
    assert 'Host Python venv not required' in smoke
    assert 'Qdrant disabled by configuration' in smoke
    assert 'Playwright renderer unavailable' in smoke


def test_super_light_installer_records_profile_state_for_diagnostics():
    installer = (ROOT / "install" / "profiles" / "install-super-light.sh").read_text(encoding="utf-8")
    assert 'DEPLOYMENT_PROFILE=super-light' in installer
    assert 'DEPLOYMENT_MODE=dockerized' in installer
    assert 'LOCAL_QDRANT=0' in installer
    assert 'LOCAL_PLAYWRIGHT=1' in installer


def test_playwright_renderer_stays_alive_in_degraded_browser_state():
    renderer = (ROOT / "install/components/playwright-renderer/app/renderer.py").read_text(encoding="utf-8")
    assert 'Chromium launch failed; renderer stays up in degraded mode' in renderer
    assert '"launch_error": BROWSER_LAUNCH_ERROR' in renderer


def test_installers_refuse_nonempty_foreign_prefixes():
    super_light = (ROOT / "install" / "profiles" / "install-super-light.sh").read_text(encoding="utf-8")
    standard = (ROOT / "install" / "profiles" / "install-standard.sh").read_text(encoding="utf-8")
    marker = "Refusing to install into non-empty directory that is not recognized as an AKI RAG installation"
    assert marker in super_light
    assert marker in standard
    assert '.aki-rag-installation' in super_light
    assert '.aki-rag-installation' in standard


def test_install_profile_shell_scripts_are_syntax_valid():
    for path in (
        ROOT / "install/profiles/install-super-light.sh",
        ROOT / "install/profiles/install-standard.sh",
        ROOT / "install/install.sh",
    ):
        result = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{path}: {result.stderr}"


def test_super_light_rerun_aborts_for_running_stack_but_accepts_stopped_stack():
    installer = (ROOT / "install" / "profiles" / "install-super-light.sh").read_text(encoding="utf-8")
    running = '[WARN] Existing AKI RAG services are running:'
    stopped = '[INFO] Existing AKI RAG stack is stopped; rerun may rebuild/start it.'
    assert running in installer
    assert stopped in installer
    block = installer[installer.index(running):installer.index(stopped)]
    assert "no installation changes were made" in block
    assert "exit 2" in block


def test_super_light_installer_supports_alternate_proxy_ports():
    installer = (ROOT / "install/profiles/install-super-light.sh").read_text(encoding="utf-8")
    assert "--proxy-http-port" in installer
    assert "--proxy-https-port" in installer
    assert 'listen ${PROXY_HTTP_PORT} default_server' in installer
    assert 'listen ${PROXY_HTTPS_PORT} ssl default_server' in installer

    result = subprocess.run(
        [
            "bash",
            str(ROOT / "install/install.sh"),
            "--profile",
            "super-light",
            "--plan",
            "--with-proxy",
            "--proxy-http-port",
            "81",
            "--proxy-https-port",
            "444",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Reverse proxy:           bundled/start on 81/444" in result.stdout


def test_super_light_installer_rejects_invalid_proxy_ports():
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "install/install.sh"),
            "--profile",
            "super-light",
            "--plan",
            "--proxy-http-port",
            "0",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--proxy-http-port must be an integer from 1 to 65535" in result.stderr
