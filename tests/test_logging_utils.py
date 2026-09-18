import logging

from rag.logging_utils import configure_third_party_logging


def test_third_party_logging_defaults_to_warning(monkeypatch):
    for key in (
        "THIRD_PARTY_LOG_LEVEL", "NEO4J_LOG_LEVEL", "HTTPX_LOG_LEVEL",
        "URLLIB3_LOG_LEVEL", "QDRANT_LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)
    configure_third_party_logging()
    assert logging.getLogger("neo4j").level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("qdrant_client").level == logging.WARNING


def test_neo4j_logging_can_be_enabled_independently(monkeypatch):
    monkeypatch.setenv("NEO4J_LOG_LEVEL", "DEBUG")
    configure_third_party_logging()
    assert logging.getLogger("neo4j").level == logging.DEBUG
