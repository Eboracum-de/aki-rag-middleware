"""Canonical TLS policy for outbound connections to the configured Nextcloud.

New installations use the ``nextcloud`` section as the single source of truth:

    nextcloud:
      verify_tls: true
      ca_file: "/path/to/private-ca-bundle.pem"

Component-local settings remain compatibility fallbacks for older installations.
The helper also applies the process-wide Python/OpenSSL X.509 strict policy so
standalone workers (CardDAV/mail) behave like API/provider processes.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rag.tls_compat import configure_tls_compat


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _section(cfg: Mapping[str, Any], source: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(source, str):
        value = cfg.get(source)
        return value if isinstance(value, Mapping) else {}
    return source


def nextcloud_verify_value(
    cfg: dict[str, Any] | None,
    *legacy_sources: str | Mapping[str, Any],
) -> bool | str:
    """Return the requests/httpx ``verify`` value for Nextcloud connections.

    ``nextcloud.ca_file`` and ``nextcloud.verify_tls`` are canonical. If neither
    is configured, legacy component sections are consulted in caller-supplied
    priority order. A CA file enables normal certificate/hostname validation
    against that bundle; ``False`` is retained only for explicit diagnostics.
    """
    config = cfg or {}
    configure_tls_compat(config)

    canonical = _section(config, "nextcloud")
    ca_file = str(canonical.get("ca_file") or "").strip()
    if ca_file:
        return ca_file
    if "verify_tls" in canonical:
        return _truthy(canonical.get("verify_tls"), True)

    for source in legacy_sources:
        legacy = _section(config, source)
        ca_file = str(legacy.get("ca_file") or "").strip()
        if ca_file:
            return ca_file
        if "verify_tls" in legacy:
            return _truthy(legacy.get("verify_tls"), True)

    return True
