"""Role-aware LLM backend routing.

The rc1 provider had one global backend with several model overrides.  rc2 keeps
that configuration as the default and allows selected roles to override backend,
URL, credentials and TLS independently.  Empty role variables inherit the
canonical ``LLM_*`` settings.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from urllib.parse import urlparse

from rag.llm_backend import LLMBackend, build_llm_backend


ROLES = ("default", "planner", "verifier", "evidence", "answer")


def _truthy(value: str | None, default: bool = True) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _env(role: str, suffix: str, default: str = "") -> str:
    if role == "default":
        return str(os.getenv(f"LLM_{suffix}", default) or default).strip()
    value = str(os.getenv(f"{role.upper()}_LLM_{suffix}", "") or "").strip()
    if value:
        return value
    return str(os.getenv(f"LLM_{suffix}", default) or default).strip()


def _scope_for_url(base_url: str) -> str:
    """Classify a backend endpoint for trust-boundary display/budgets.

    Loopback and RFC1918/ULA/link-local addresses are treated as local/private.
    Public addresses and ordinary public DNS names are remote. Administrators
    can override the automatic result with ``<ROLE>_LLM_SCOPE=local|remote``.
    """
    try:
        host = (urlparse(base_url).hostname or "").strip().casefold()
        if host in {"localhost", "localhost.localdomain"}:
            return "local"
        address = ipaddress.ip_address(host)
        if address.is_loopback or address.is_private or address.is_link_local:
            return "local"
        return "remote"
    except ValueError:
        # A DNS name cannot be proven private without performing resolution.
        return "remote"


@dataclass(frozen=True)
class RoleBackend:
    role: str
    backend_name: str
    base_url: str
    model: str
    scope: str
    backend: LLMBackend

    @property
    def remote(self) -> bool:
        return self.scope == "remote"

    def info(self) -> dict[str, object]:
        data = dict(self.backend.info())
        data.update({"role": self.role, "scope": self.scope, "remote": self.remote})
        return data


def build_role_backends(
    *,
    default_backend: str,
    default_base_url: str,
    default_model: str,
    default_api_key: str,
    default_verify_tls: bool,
    default_ca_file: str | None,
    models: dict[str, str] | None = None,
) -> dict[str, RoleBackend]:
    model_map = {str(k): str(v) for k, v in (models or {}).items()}
    result: dict[str, RoleBackend] = {}

    for role in ROLES:
        prefix = role.upper()
        if role == "default":
            backend_name = default_backend
            base_url = default_base_url
            api_key = default_api_key
            verify_tls = default_verify_tls
            ca_file = default_ca_file
            model = model_map.get(role) or default_model
            scope_override = str(os.getenv("LLM_SCOPE", "") or "").strip().lower()
        else:
            backend_name = str(os.getenv(f"{prefix}_LLM_BACKEND", "") or "").strip() or default_backend
            base_url = str(os.getenv(f"{prefix}_LLM_BASE_URL", "") or "").strip().rstrip("/") or default_base_url
            # An explicitly configured role key wins. Empty means inherit.
            api_key_env = os.getenv(f"{prefix}_LLM_API_KEY")
            api_key = default_api_key if api_key_env is None or api_key_env == "" else api_key_env
            verify_raw = os.getenv(f"{prefix}_LLM_VERIFY_TLS")
            verify_tls = default_verify_tls if verify_raw is None or verify_raw == "" else _truthy(verify_raw, default_verify_tls)
            ca_raw = os.getenv(f"{prefix}_LLM_CA_FILE")
            ca_file = default_ca_file if ca_raw is None or str(ca_raw).strip() == "" else str(ca_raw).strip()
            model = str(os.getenv(f"{prefix}_LLM_MODEL", "") or "").strip() or model_map.get(role) or default_model
            scope_override = str(os.getenv(f"{prefix}_LLM_SCOPE", "") or "").strip().lower()

        if scope_override and scope_override not in {"local", "remote"}:
            raise RuntimeError(f"{prefix}_LLM_SCOPE must be 'local' or 'remote'")
        scope = scope_override or _scope_for_url(base_url)
        backend = build_llm_backend(
            backend_name,
            base_url=base_url,
            model=model,
            api_key=api_key,
            verify_tls=verify_tls,
            ca_file=ca_file,
        )
        result[role] = RoleBackend(
            role=role,
            backend_name=backend_name,
            base_url=base_url,
            model=model,
            scope=scope,
            backend=backend,
        )
    return result
