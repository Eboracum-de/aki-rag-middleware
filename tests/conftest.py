import pytest


@pytest.fixture(autouse=True)
def _configured_internal_api_key(monkeypatch):
    """Production installers always provide this machine secret."""
    monkeypatch.setenv("RAG_INTERNAL_API_KEY", "test-internal-api-key-" + "x" * 40)
    monkeypatch.setenv("RAG_PROVIDER_INTERNAL_KEY", "test-provider-internal-key-" + "y" * 40)
