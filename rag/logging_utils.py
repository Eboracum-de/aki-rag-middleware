"""Small component-oriented logging helper.

Runtime services use a compact, stable format:
    2026-08-30 10:31:22 INFO [api] message

LOG_LEVEL is the global default.  COMPONENT_LOG_LEVEL overrides it, e.g.
API_LOG_LEVEL=DEBUG or WORKER_LOG_LEVEL=WARN.
"""
from __future__ import annotations

import logging
import os


def _level(component: str) -> int:
    key = f"{component.upper().replace('-', '_')}_LOG_LEVEL"
    raw = os.getenv(key, os.getenv("LOG_LEVEL", "INFO")).strip().upper()
    return getattr(logging, raw, logging.INFO)


def get_logger(component: str) -> logging.Logger:
    name = str(component or "rag").strip().lower() or "rag"
    logger = logging.getLogger(name)
    logger.setLevel(_level(name))
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
    for handler in logger.handlers:
        handler.setLevel(_level(name))
    return logger


def _env_level(name: str, default: str = "WARNING") -> int:
    raw = os.getenv(name, default).strip().upper()
    return getattr(logging, raw, getattr(logging, default, logging.WARNING))


def configure_third_party_logging() -> None:
    """Keep chatty dependency logs out of normal API/admin operation.

    Neo4j can emit Cypher/driver diagnostics when a broader/root logger is put
    into DEBUG mode.  The admin UI performs many small graph reads, so those
    messages quickly dominate the API log.  Third-party loggers therefore use
    WARNING by default and can be re-enabled independently for diagnostics.
    """
    default = os.getenv("THIRD_PARTY_LOG_LEVEL", "WARNING").strip().upper() or "WARNING"
    groups = {
        "NEO4J_LOG_LEVEL": ("neo4j",),
        "HTTPX_LOG_LEVEL": ("httpx", "httpcore"),
        "URLLIB3_LOG_LEVEL": ("urllib3",),
        "QDRANT_LOG_LEVEL": ("qdrant_client",),
    }
    for env_name, logger_names in groups.items():
        level = _env_level(env_name, default)
        for logger_name in logger_names:
            logging.getLogger(logger_name).setLevel(level)
