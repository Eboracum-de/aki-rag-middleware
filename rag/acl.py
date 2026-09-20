"""Live Nextcloud authorization for final RAG evidence.

The retrieval indices may contain stale ACL metadata.  This module deliberately
asks Nextcloud itself whether the current user can see the already-ranked file
IDs.  Authorization therefore happens *after* retrieval/reranking and never
pulls replacement candidates.

Two identity modes are supported:

``single_user``
    Useful for the current one-user deployment and for smoke/regression tests.
    Every RAG request is checked with the configured Nextcloud app password.

``credential_store``
    Uses a frontend-scoped identity to retrieve a JIT-created Nextcloud app
    credential.  The identity is additionally bound to a canonical
    (nextcloud_server, nextcloud_login) user for admin-managed user settings.

``mapped_users``
    Legacy static mapping. Missing identities/credentials fail closed.

No password is stored in config.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any
from urllib.parse import quote
import xml.etree.ElementTree as ET

import httpx

from rag.credential_store import CredentialStore
from rag.nextcloud_tls import nextcloud_verify_value


DAV_NS = "DAV:"
OC_NS = "http://owncloud.org/ns"




def _cfg_get(cfg: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = cfg
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current

class AclError(RuntimeError):
    """Base class for live ACL failures."""


class AclConfigurationError(AclError):
    pass


class AclIdentityError(AclError):
    pass


class AclBackendError(AclError):
    pass


@dataclass(frozen=True)
class NextcloudCredential:
    username: str
    password: str


@dataclass(frozen=True)
class AclDecision:
    enabled: bool
    results: list[dict[str, Any]]
    checked: int
    authorized: int


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _file_id(item: dict[str, Any]) -> str | None:
    """Return the numeric Nextcloud fileid represented by a result."""
    raw = str(item.get("document_id") or item.get("id") or "").strip()
    match = re.fullmatch(r"files:(\d+)", raw)
    if match:
        return match.group(1)

    # Some legacy payloads carry a separate open-file id.
    for key in ("nextcloud_openfile_id", "fileid", "file_id"):
        value = str(item.get(key) or "").strip()
        if value.isdigit():
            return value
    return None


def _nested_or(expressions: list[ET.Element]) -> ET.Element:
    """Build a balanced RFC5323 binary OR tree.

    A left-deep tree reaches Python/XML recursion limits around ~1000 file ids.
    Pairwise folding keeps the tree depth logarithmic.  Live ACL additionally
    sends bounded batches, so neither the serializer nor Nextcloud receives a
    pathological boolean expression.
    """
    if not expressions:
        raise ValueError("at least one expression is required")
    level = list(expressions)
    while len(level) > 1:
        next_level: list[ET.Element] = []
        for index in range(0, len(level), 2):
            if index + 1 >= len(level):
                next_level.append(level[index])
                continue
            node = ET.Element(f"{{{DAV_NS}}}or")
            node.append(level[index])
            node.append(level[index + 1])
            next_level.append(node)
        level = next_level
    return level[0]


def build_fileid_search_xml(username: str, file_ids: list[str]) -> bytes:
    """Return a Nextcloud WebDAV SEARCH body for one or more file IDs."""
    clean_ids = []
    seen: set[str] = set()
    for value in file_ids:
        text = str(value).strip()
        if text.isdigit() and text not in seen:
            seen.add(text)
            clean_ids.append(text)
    if not clean_ids:
        raise ValueError("no numeric file ids")

    ET.register_namespace("d", DAV_NS)
    ET.register_namespace("oc", OC_NS)
    root = ET.Element(f"{{{DAV_NS}}}searchrequest")
    basic = ET.SubElement(root, f"{{{DAV_NS}}}basicsearch")
    select = ET.SubElement(basic, f"{{{DAV_NS}}}select")
    props = ET.SubElement(select, f"{{{DAV_NS}}}prop")
    ET.SubElement(props, f"{{{OC_NS}}}fileid")
    ET.SubElement(props, f"{{{DAV_NS}}}displayname")

    from_node = ET.SubElement(basic, f"{{{DAV_NS}}}from")
    scope = ET.SubElement(from_node, f"{{{DAV_NS}}}scope")
    href = ET.SubElement(scope, f"{{{DAV_NS}}}href")
    href.text = f"/files/{quote(username, safe='')}"
    depth = ET.SubElement(scope, f"{{{DAV_NS}}}depth")
    depth.text = "infinity"

    where = ET.SubElement(basic, f"{{{DAV_NS}}}where")
    comparisons: list[ET.Element] = []
    for file_id in clean_ids:
        eq = ET.Element(f"{{{DAV_NS}}}eq")
        prop = ET.SubElement(eq, f"{{{DAV_NS}}}prop")
        ET.SubElement(prop, f"{{{OC_NS}}}fileid")
        literal = ET.SubElement(eq, f"{{{DAV_NS}}}literal")
        literal.text = file_id
        comparisons.append(eq)
    where.append(_nested_or(comparisons) if len(comparisons) > 1 else comparisons[0])
    ET.SubElement(basic, f"{{{DAV_NS}}}orderby")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def parse_authorized_fileids(xml_body: str | bytes) -> set[str]:
    """Extract successfully returned oc:fileid values from DAV multistatus."""
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError as exc:
        raise AclBackendError(f"invalid WebDAV SEARCH response: {exc}") from exc
    result: set[str] = set()
    for elem in root.iter(f"{{{OC_NS}}}fileid"):
        if elem.text and elem.text.strip().isdigit():
            result.add(elem.text.strip())
    return result


class NextcloudLiveAcl:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.enabled = _truthy(_cfg_get(cfg, "acl.enabled", default=False))
        self.identity_mode = str(_cfg_get(cfg, "acl.identity_mode", default="single_user") or "single_user").strip().lower()
        self.timeout = float(_cfg_get(cfg, "acl.timeout", default=15.0) or 15.0)
        self.batch_size = max(1, min(500, int(_cfg_get(cfg, "acl.batch_size", default=100) or 100)))
        verify = nextcloud_verify_value(cfg, "acl", "carddav")
        self.verify_tls = verify if isinstance(verify, bool) else True
        self.ca_file = verify if isinstance(verify, str) else None
        explicit_url = str(_cfg_get(cfg, "acl.webdav_url", default="") or "").strip()
        if explicit_url:
            self.webdav_url = explicit_url.rstrip("/") + "/"
        else:
            base = str(_cfg_get(cfg, "nextcloud.base_url", default="") or "").rstrip("/")
            self.webdav_url = base + "/remote.php/dav/" if base else ""

    def _credential(self, rag_user_id: str | None) -> NextcloudCredential:
        if self.identity_mode == "single_user":
            username_env = str(_cfg_get(self.cfg, "acl.username_env", default="NEXTCLOUD_USERNAME") or "NEXTCLOUD_USERNAME")
            password_env = str(_cfg_get(self.cfg, "acl.password_env", default="NEXTCLOUD_APP_PASSWORD") or "NEXTCLOUD_APP_PASSWORD")
            username = os.getenv(username_env, "").strip()
            password = os.getenv(password_env, "")
            if not username or not password:
                raise AclConfigurationError(
                    f"live ACL credentials missing ({username_env}/{password_env})"
                )
            return NextcloudCredential(username, password)

        user_id = str(rag_user_id or "").strip()
        if not user_id:
            raise AclIdentityError("RAG user identity missing")

        if self.identity_mode == "credential_store":
            store_path = str(_cfg_get(self.cfg, "acl.credential_store", default="runtime/users.sqlite") or "runtime/users.sqlite")
            store = CredentialStore(store_path)
            credential = store.get_credential(user_id, "nextcloud")
            if credential is None:
                raise AclIdentityError("no Nextcloud credential stored for current RAG user")
            canonical = store.get_canonical_user_for_identity(user_id)
            if canonical is not None and not canonical.enabled:
                raise AclIdentityError("Nextcloud user is disabled by RAG admin")
            return NextcloudCredential(credential.username, credential.secret)

        if self.identity_mode != "mapped_users":
            raise AclConfigurationError(f"unknown acl.identity_mode={self.identity_mode!r}")
        mapping = _cfg_get(self.cfg, "acl.user_map", default={}) or {}
        if not isinstance(mapping, dict):
            raise AclConfigurationError("acl.user_map must be a mapping")
        entry = mapping.get(user_id)
        if not isinstance(entry, dict):
            raise AclIdentityError("no Nextcloud credential mapping for current RAG user")
        username = str(entry.get("username") or "").strip()
        username_env = str(entry.get("username_env") or "").strip()
        if username_env:
            username = os.getenv(username_env, "").strip()
        password_env = str(entry.get("password_env") or "").strip()
        password = os.getenv(password_env, "") if password_env else ""
        if not username or not password:
            raise AclIdentityError("Nextcloud credential mapping is incomplete")
        return NextcloudCredential(username, password)

    def credential_for_user(self, rag_user_id: str | None = None) -> NextcloudCredential:
        """Return the server-side Nextcloud credential for the current RAG user.

        This is shared by live ACL checks and other user-scoped WebDAV actions
        such as archival of selected public web evidence. Credentials never
        leave the middleware response.
        """
        return self._credential(rag_user_id)

    def authorize_with_credential(
        self,
        results: list[dict[str, Any]],
        *,
        username: str,
        password: str,
    ) -> AclDecision:
        """Authorize a bounded result set with an explicitly supplied temporary credential.

        Used by ephemeral curation sessions. The credential is never written to
        the normal provider credential namespace.
        """
        if not self.enabled:
            return AclDecision(False, list(results), len(results), len(results))
        if not results:
            return AclDecision(True, [], 0, 0)
        if not self.webdav_url:
            raise AclConfigurationError("acl.webdav_url/nextcloud.base_url is not configured")
        credential = NextcloudCredential(str(username or "").strip(), str(password or ""))
        if not credential.username or not credential.password:
            raise AclIdentityError("temporary Nextcloud credential is incomplete")
        return self._authorize_with_credential(results, credential)

    def _authorize_with_credential(
        self,
        results: list[dict[str, Any]],
        credential: NextcloudCredential,
    ) -> AclDecision:
        ids_by_pos: list[str | None] = [_file_id(item) for item in results]
        file_ids = [x for x in ids_by_pos if x]
        if not file_ids:
            # Fail closed for results that cannot be tied to a Nextcloud file.
            return AclDecision(True, [], len(results), 0)

        # Preserve order while avoiding repeated file ids across batches.
        unique_file_ids = list(dict.fromkeys(file_ids))
        verify: bool | str = self.ca_file if self.ca_file else self.verify_tls
        authorized_ids: set[str] = set()
        for offset in range(0, len(unique_file_ids), self.batch_size):
            batch = unique_file_ids[offset:offset + self.batch_size]
            body = build_fileid_search_xml(credential.username, batch)
            try:
                response = httpx.request(
                    "SEARCH",
                    self.webdav_url,
                    content=body,
                    headers={"Content-Type": "text/xml; charset=utf-8"},
                    auth=(credential.username, credential.password),
                    timeout=self.timeout,
                    verify=verify,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in {401, 403}:
                    raise AclIdentityError(f"Nextcloud rejected live ACL credentials (HTTP {status})") from exc
                raise AclBackendError(f"Nextcloud live ACL SEARCH failed (HTTP {status})") from exc
            except httpx.HTTPError as exc:
                raise AclBackendError(f"Nextcloud live ACL SEARCH failed: {type(exc).__name__}: {exc}") from exc
            authorized_ids.update(parse_authorized_fileids(response.content))
        filtered = [
            item for item, file_id in zip(results, ids_by_pos)
            if file_id is not None and file_id in authorized_ids
        ]
        return AclDecision(True, filtered, len(results), len(filtered))

    def authorize(self, results: list[dict[str, Any]], *, rag_user_id: str | None = None) -> AclDecision:
        """Filter *already final* results against current Nextcloud visibility."""
        if not self.enabled:
            return AclDecision(False, list(results), len(results), len(results))
        if not results:
            return AclDecision(True, [], 0, 0)
        if not self.webdav_url:
            raise AclConfigurationError("acl.webdav_url/nextcloud.base_url is not configured")
        return self._authorize_with_credential(results, self._credential(rag_user_id))
