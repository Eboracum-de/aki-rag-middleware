import os

import yaml

from rag import openai_provider as provider


def test_nextcloud_base_url_comes_from_config_when_env_missing(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"nextcloud": {"base_url": "https://cloud.example/"}}))
    monkeypatch.delenv("NEXTCLOUD_BASE_URL", raising=False)
    monkeypatch.setenv("RAG_CONFIG_FILE", str(config))
    assert provider._provider_config_nextcloud_base_url() == "https://cloud.example"


def test_nextcloud_base_url_env_override_wins(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"nextcloud": {"base_url": "https://config.example"}}))
    monkeypatch.setenv("RAG_CONFIG_FILE", str(config))
    monkeypatch.setenv("NEXTCLOUD_BASE_URL", "https://override.example/")
    assert provider._provider_config_nextcloud_base_url() == "https://override.example"
