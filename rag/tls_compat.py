"""Process-wide TLS compatibility controls.

Python 3.13 enables VERIFY_X509_STRICT in default client contexts.  That is a
useful modern default, but some long-lived private PKIs remain valid for the
site's operational purposes while missing RFC-5280 extensions such as AKI.

``tls.x509_strict: false`` keeps certificate verification, hostname/SAN checks,
validity checks and trust-chain verification enabled; it only removes the
additional VERIFY_X509_STRICT flag.  The patch is process-wide so stdlib/httpx
and requests/urllib3 use one consistent policy.
"""
from __future__ import annotations

import ssl
from typing import Any

from rag.logging_utils import get_logger


log = get_logger("tls")
_CONFIGURED: bool | None = None
_ORIGINAL_CREATE_DEFAULT_CONTEXT = ssl.create_default_context
_ORIGINAL_URLLIB3_FACTORY = None


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def x509_strict_enabled(config: dict[str, Any] | None) -> bool:
    tls = dict((config or {}).get("tls") or {})
    return _truthy(tls.get("x509_strict"), False)


def _clear_strict(ctx: ssl.SSLContext) -> ssl.SSLContext:
    strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict:
        ctx.verify_flags &= ~strict
    return ctx


def configure_tls_compat(config: dict[str, Any] | None) -> bool:
    """Apply the configured Python TLS policy and return x509_strict state.

    The function is idempotent.  Re-enabling strict inside an already-running
    process is intentionally unsupported; services should be restarted after a
    configuration change.
    """
    global _CONFIGURED, _ORIGINAL_URLLIB3_FACTORY

    strict_enabled = x509_strict_enabled(config)
    if strict_enabled:
        if _CONFIGURED is None:
            _CONFIGURED = True
        return True

    if _CONFIGURED is False:
        return False

    def rag_create_default_context(*args: Any, **kwargs: Any) -> ssl.SSLContext:
        return _clear_strict(_ORIGINAL_CREATE_DEFAULT_CONTEXT(*args, **kwargs))

    ssl.create_default_context = rag_create_default_context

    # requests uses urllib3's own context factory.  Patch both the utility
    # module and the copy imported into urllib3.connection.
    try:
        import urllib3.util.ssl_ as urllib3_ssl

        if _ORIGINAL_URLLIB3_FACTORY is None:
            _ORIGINAL_URLLIB3_FACTORY = urllib3_ssl.create_urllib3_context

        def rag_create_urllib3_context(*args: Any, **kwargs: Any) -> ssl.SSLContext:
            return _clear_strict(_ORIGINAL_URLLIB3_FACTORY(*args, **kwargs))

        urllib3_ssl.create_urllib3_context = rag_create_urllib3_context
        try:
            import urllib3.connection as urllib3_connection
            urllib3_connection.create_urllib3_context = rag_create_urllib3_context
        except Exception:
            log.debug("Could not patch urllib3.connection TLS context factory", exc_info=True)
    except Exception:
        # urllib3 is optional for code paths that use only httpx/stdlib.
        log.debug("urllib3 TLS compatibility patch unavailable", exc_info=True)

    _CONFIGURED = False
    return False
