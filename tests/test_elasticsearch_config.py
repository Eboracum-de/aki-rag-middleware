from pathlib import Path

import pytest

from rag.elasticsearch_client import elastic_credentials, elastic_verify, httpx_options, requests_options


def test_elasticsearch_credentials_use_env(monkeypatch):
    cfg = {"elasticsearch": {"username": "nextcloud", "password_env": "ES_TEST_PASSWORD"}}
    monkeypatch.setenv("ES_TEST_PASSWORD", "secret")
    assert elastic_credentials(cfg) == ("nextcloud", "secret")
    assert requests_options(cfg)["auth"] == ("nextcloud", "secret")
    assert httpx_options(cfg)["auth"] == ("nextcloud", "secret")


def test_elasticsearch_username_without_secret_fails(monkeypatch):
    monkeypatch.delenv("ES_MISSING", raising=False)
    cfg = {"elasticsearch": {"username": "nextcloud", "password_env": "ES_MISSING"}}
    with pytest.raises(RuntimeError, match="password is missing"):
        elastic_credentials(cfg)


def test_elasticsearch_ca_file_is_used(tmp_path: Path):
    ca = tmp_path / "ca.pem"
    ca.write_text("not a certificate")
    cfg = {"elasticsearch": {"verify_tls": True, "ca_file": str(ca)}}
    assert elastic_verify(cfg, for_httpx=False) == str(ca)


def test_elasticsearch_verify_false_needs_no_ca():
    cfg = {"elasticsearch": {"verify_tls": False, "ca_file": "/missing"}}
    assert elastic_verify(cfg, for_httpx=False) is False
