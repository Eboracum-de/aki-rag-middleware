"""Persistent source-origin registry and Elasticsearch mirror/reconcile helpers.

The registry is the middleware-owned source of truth for special archive origins.
Ordinary Nextcloud files intentionally need no registry row: absence means
``documents``.  Elasticsearch/Qdrant carry a mirrored ``source_origin`` field so
source scopes can be applied before candidate limits are consumed.
"""
from __future__ import annotations

import argparse
import json
import logging
from functools import lru_cache
from pathlib import Path
import sqlite3
import time
from typing import Iterable

from rag.mail_metadata import normalize_mail_metadata, normalize_cloud_path

import requests
import yaml

from rag.elasticsearch_client import requests_options as elastic_requests_options

log = logging.getLogger("rag-source-registry")
BASE_DIR = Path(__file__).resolve().parent.parent
SPECIAL_ORIGINS = frozenset({"mail_archive", "web_archive", "chat_archive"})

# Process-local throttle/state for the lightweight ES mirror repair.  The
# registry file stamp changes whenever importers add/update archive documents.
# Missing ES documents are retried because Nextcloud indexing is asynchronous.
_AUTO_MIRROR_STAMP: tuple[int, int, int, int] | None = None
_AUTO_MIRROR_MISSING = 0
_AUTO_MIRROR_LAST_ATTEMPT = 0.0


def _config() -> dict:
    try:
        data = yaml.safe_load((BASE_DIR / "config.yaml").read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def registry_path() -> Path:
    cfg = _config()
    raw = str((cfg.get("source_registry") or {}).get("path") or "runtime/source_registry.sqlite").strip()
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


class SourceRegistry:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else registry_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_documents (
                document_id TEXT PRIMARY KEY,
                source_origin TEXT NOT NULL,
                source_path TEXT NOT NULL DEFAULT '',
                classification_source TEXT NOT NULL DEFAULT '',
                first_seen_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_documents_origin ON source_documents(source_origin)"
        )
        self.conn.commit()

    def get(self, document_id: str) -> str | None:
        doc = str(document_id or "").strip()
        if not doc:
            return None
        row = self.conn.execute(
            "SELECT source_origin FROM source_documents WHERE document_id=?", (doc,)
        ).fetchone()
        return str(row[0]) if row else None

    def set(self, document_id: str, source_origin: str, *, source_path: str = "", classification_source: str = "") -> bool:
        doc = str(document_id or "").strip()
        origin = str(source_origin or "").strip()
        if not doc or origin not in SPECIAL_ORIGINS:
            return False
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO source_documents(document_id,source_origin,source_path,classification_source,first_seen_at,updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(document_id) DO UPDATE SET
                source_origin=excluded.source_origin,
                source_path=CASE WHEN excluded.source_path<>'' THEN excluded.source_path ELSE source_documents.source_path END,
                classification_source=CASE WHEN excluded.classification_source<>'' THEN excluded.classification_source ELSE source_documents.classification_source END,
                updated_at=excluded.updated_at
            """,
            (doc, origin, str(source_path or ""), str(classification_source or ""), now, now),
        )
        self.conn.commit()
        _registry_map.cache_clear()
        return True

    def rows(self) -> list[tuple[str, str, str, str]]:
        return [tuple(map(str, row)) for row in self.conn.execute(
            "SELECT document_id,source_origin,source_path,classification_source FROM source_documents ORDER BY document_id"
        ).fetchall()]

    def close(self) -> None:
        self.conn.close()


def _stamp(path: Path) -> tuple[int, int, int, int] | None:
    values: list[int] = []
    found = False
    for candidate in (path, Path(str(path) + "-wal")):
        try:
            st = candidate.stat(); values += [st.st_mtime_ns, st.st_size]; found = True
        except OSError:
            values += [0, 0]
    return tuple(values) if found else None


@lru_cache(maxsize=8)
def _registry_map(path_text: str, stamp: tuple[int, int, int, int] | None) -> dict[str, str]:
    del stamp
    path = Path(path_text)
    if not path.exists():
        return {}
    try:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            rows = con.execute("SELECT document_id,source_origin FROM source_documents").fetchall()
        finally:
            con.close()
        return {str(doc): str(origin) for doc, origin in rows if str(origin) in SPECIAL_ORIGINS}
    except Exception:
        return {}


def registered_origin(document_id: str) -> str | None:
    path = registry_path()
    return _registry_map(str(path), _stamp(path)).get(str(document_id or "").strip())


def register_document(document_id: str, source_origin: str, *, source_path: str = "", classification_source: str = "") -> bool:
    registry = SourceRegistry()
    try:
        return registry.set(document_id, source_origin, source_path=source_path, classification_source=classification_source)
    finally:
        registry.close()


def _bulk_update(es_url: str, index: str, updates: list[tuple[str, str]], options: dict) -> int:
    if not updates:
        return 0
    lines: list[str] = []
    for document_id, origin in updates:
        lines.append(json.dumps({"update": {"_index": index, "_id": document_id}}, separators=(",", ":")))
        lines.append(json.dumps({"doc": {"source_origin": origin}}, separators=(",", ":")))
    response = requests.post(
        f"{es_url.rstrip('/')}/_bulk",
        data="\n".join(lines) + "\n",
        headers={"Content-Type": "application/x-ndjson"},
        timeout=120,
        **options,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        failures = [item for item in payload.get("items", []) if int((item.get("update") or {}).get("status") or 500) >= 300]
        raise RuntimeError(f"Elasticsearch source_origin bulk update failed for {len(failures)} documents")
    return len(updates)


def mirror_updates_to_elasticsearch(es_url: str, index: str, updates: Iterable[tuple[str, str]], cfg: dict) -> int:
    clean = [(str(doc), str(origin)) for doc, origin in updates if str(doc) and str(origin) in SPECIAL_ORIGINS]
    return _bulk_update(es_url, index, clean, elastic_requests_options(cfg))


def auto_mirror_registry_to_elasticsearch(*, retry_seconds: float = 15.0) -> dict[str, int]:
    """Best-effort lightweight repair of registry -> Elasticsearch mirrors.

    This is intentionally *not* a full reconcile.  It only considers document
    ids already present in the middleware-owned registry, checks which of those
    ids currently exist in Elasticsearch and repairs missing/wrong
    ``source_origin`` values.  It runs on the first archive-scoped search and
    again whenever the registry WAL/file stamp changes.  Documents not yet
    indexed by Nextcloud are retried after ``retry_seconds``.

    The routine keeps Super-Light self-healing without scanning the complete
    Nextcloud index on every startup/search.
    """
    global _AUTO_MIRROR_STAMP, _AUTO_MIRROR_MISSING, _AUTO_MIRROR_LAST_ATTEMPT

    path = registry_path()
    stamp = _stamp(path)
    now = time.monotonic()
    if stamp == _AUTO_MIRROR_STAMP:
        if _AUTO_MIRROR_MISSING <= 0:
            return {"checked": 0, "updated": 0, "missing": 0}
        if now - _AUTO_MIRROR_LAST_ATTEMPT < max(1.0, float(retry_seconds)):
            return {"checked": 0, "updated": 0, "missing": _AUTO_MIRROR_MISSING}

    cfg = _config()
    es = cfg.get("elasticsearch") or {}
    es_url = str(es.get("url") or "").rstrip("/")
    index = str(es.get("index") or "").strip()
    if not es_url or not index or not path.exists():
        _AUTO_MIRROR_STAMP = stamp
        _AUTO_MIRROR_MISSING = 0
        _AUTO_MIRROR_LAST_ATTEMPT = now
        return {"checked": 0, "updated": 0, "missing": 0}

    registry = SourceRegistry(path)
    try:
        expected = {doc: origin for doc, origin, _source_path, _classification in registry.rows() if origin in SPECIAL_ORIGINS}
    finally:
        registry.close()
    if not expected:
        _AUTO_MIRROR_STAMP = stamp
        _AUTO_MIRROR_MISSING = 0
        _AUTO_MIRROR_LAST_ATTEMPT = now
        return {"checked": 0, "updated": 0, "missing": 0}

    options = elastic_requests_options(cfg)
    found: dict[str, str] = {}
    ids = list(expected)
    chunk_size = 500
    for offset in range(0, len(ids), chunk_size):
        chunk = ids[offset:offset + chunk_size]
        response = requests.post(
            f"{es_url}/{index}/_search",
            json={
                "size": len(chunk),
                "_source": ["source_origin"],
                "query": {"ids": {"values": chunk}},
            },
            timeout=60,
            **options,
        )
        response.raise_for_status()
        for hit in list((response.json().get("hits") or {}).get("hits") or []):
            found[str(hit.get("_id") or "")] = str((hit.get("_source") or {}).get("source_origin") or "")

    updates = [(doc, origin) for doc, origin in expected.items() if doc in found and found.get(doc) != origin]
    updated = _bulk_update(es_url, index, updates, options) if updates else 0
    missing = sum(1 for doc in expected if doc not in found)

    _AUTO_MIRROR_STAMP = stamp
    _AUTO_MIRROR_MISSING = missing
    _AUTO_MIRROR_LAST_ATTEMPT = now
    if updated or missing:
        log.info(
            "source_origin auto-mirror: checked=%d updated=%d pending_not_indexed=%d",
            len(expected), updated, missing,
        )
    return {"checked": len(expected), "updated": updated, "missing": missing}



def _resolve_sidecar_member_path(sidecar_title: str, raw_value: str) -> str:
    """Resolve a sidecar member to the exact indexed Nextcloud title/path."""
    raw = str(raw_value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    # Built-in sidecars may store EML as an absolute/root-relative cloud path.
    if raw.startswith("/"):
        return normalize_cloud_path(raw)
    clean_sidecar = normalize_cloud_path(sidecar_title)
    parent = clean_sidecar.rsplit("/", 1)[0] if "/" in clean_sidecar else ""
    clean_raw = normalize_cloud_path(raw)
    if not clean_raw:
        return ""
    # If a producer already stored a path rooted at/including the sidecar parent,
    # do not prepend the parent a second time.
    if "/" in clean_raw and (not parent or clean_raw.casefold().startswith(parent.casefold() + "/")):
        return clean_raw
    return f"{parent}/{clean_raw}" if parent else clean_raw


def _discover_mail_sidecar_paths(
    es_url: str, index: str, options: dict, batch_size: int
) -> tuple[set[str], int, int]:
    """Return exact mail-member paths declared by indexed .mailmeta.json files.

    Hidden sidecars are intentionally not required to be indexed, therefore this
    is a preferred rebuild source, not the only one.  When they are available,
    their explicit file list is more precise than classifying an entire folder.
    """
    paths: set[str] = set()
    seen = parsed = 0
    scroll_id = None
    try:
        response = requests.post(
            f"{es_url.rstrip('/')}/{index}/_search",
            params={"scroll": "5m"},
            json={
                "size": max(1, int(batch_size)),
                "sort": ["_doc"],
                "_source": ["title", "content"],
                "query": {
                    "bool": {
                        "should": [
                            {"wildcard": {"title.keyword": "*/.mailmeta.json"}},
                            {"wildcard": {"title.keyword": "*/.*.mailmeta.json"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
            },
            timeout=120,
            **options,
        )
        response.raise_for_status(); data = response.json(); scroll_id = data.get("_scroll_id")
        while True:
            hits = list((data.get("hits") or {}).get("hits") or [])
            if not hits:
                break
            for hit in hits:
                src = hit.get("_source") or {}
                title = str(src.get("title") or "").strip()
                content = str(src.get("content") or "").strip()
                if not title:
                    continue
                seen += 1
                try:
                    payload = json.loads(content)
                    metadata = normalize_mail_metadata(payload)
                except Exception:
                    log.debug(
                        "Skipping malformed mail metadata during source reconcile: %s",
                        title,
                        exc_info=True,
                    )
                    continue
                parsed += 1
                files = metadata.get("files") or {}
                members: list[str] = []
                for key in ("text", "readme", "eml"):
                    value = files.get(key)
                    if value:
                        members.append(str(value))
                for key in ("html_pdf", "attachments"):
                    value = files.get(key) or []
                    if isinstance(value, str):
                        value = [value]
                    if isinstance(value, list):
                        members.extend(str(item) for item in value if str(item or "").strip())
                for member in members:
                    resolved = _resolve_sidecar_member_path(title, member)
                    if resolved:
                        paths.add(resolved.casefold())
            response = requests.post(
                f"{es_url.rstrip('/')}/_search/scroll",
                json={"scroll": "5m", "scroll_id": scroll_id}, timeout=120, **options,
            )
            response.raise_for_status(); data = response.json(); scroll_id = data.get("_scroll_id", scroll_id)
    finally:
        if scroll_id:
            try:
                requests.delete(f"{es_url.rstrip('/')}/_search/scroll", json={"scroll_id": [scroll_id]}, timeout=30, **options)
            except Exception:
                log.debug("Failed to clear Elasticsearch mail-sidecar scroll", exc_info=True)
    return paths, seen, parsed

def _discover_mail_container_dirs(es_url: str, index: str, options: dict, batch_size: int) -> set[str]:
    """Discover existing normalized mail containers without relying on account paths."""
    directories: set[str] = set()
    scroll_id = None
    try:
        response = requests.post(
            f"{es_url.rstrip('/')}/{index}/_search",
            params={"scroll": "5m"},
            json={
                "size": max(1, int(batch_size)),
                "sort": ["_doc"],
                "_source": ["title"],
                "query": {"match_phrase": {"content": "CONTENT KIND EMAIL"}},
            },
            timeout=120,
            **options,
        )
        response.raise_for_status(); data = response.json(); scroll_id = data.get("_scroll_id")
        while True:
            hits = list((data.get("hits") or {}).get("hits") or [])
            if not hits:
                break
            for hit in hits:
                title = str((hit.get("_source") or {}).get("title") or "").strip(" /")
                if title:
                    parent = title.rsplit("/", 1)[0] if "/" in title else ""
                    if parent:
                        directories.add(parent.casefold())
            response = requests.post(
                f"{es_url.rstrip('/')}/_search/scroll",
                json={"scroll": "5m", "scroll_id": scroll_id}, timeout=120, **options,
            )
            response.raise_for_status(); data = response.json(); scroll_id = data.get("_scroll_id", scroll_id)
    finally:
        if scroll_id:
            try:
                requests.delete(f"{es_url.rstrip('/')}/_search/scroll", json={"scroll_id": [scroll_id]}, timeout=30, **options)
            except Exception:
                log.debug("Failed to clear Elasticsearch mail-container scroll", exc_info=True)
    return directories


def reconcile(*, batch_size: int = 250) -> dict[str, int]:
    """Rebuild/restore special source origins from registry + configured archive roots.

    The full ES traversal is intentional admin work. Registry entries win over
    path inference, so moved/shared archive documents retain their origin after
    an Elasticsearch reset. Newly discovered archive-path documents are added to
    the registry and mirrored back into Elasticsearch.
    """
    from rag.source_origin import classify_source_origin

    cfg = _config()
    es = cfg.get("elasticsearch") or {}
    es_url = str(es.get("url") or "").rstrip("/")
    index = str(es.get("index") or "").strip()
    if not es_url or not index:
        raise RuntimeError("Elasticsearch url/index missing")
    options = elastic_requests_options(cfg)
    mail_sidecar_paths, mail_sidecars_seen, mail_sidecars_parsed = _discover_mail_sidecar_paths(
        es_url, index, options, batch_size
    )
    mail_container_dirs = _discover_mail_container_dirs(es_url, index, options, batch_size)
    registry = SourceRegistry()
    known = {doc: origin for doc, origin, _path, _source in registry.rows()}
    scanned = discovered = restored = updated = 0
    scroll_id = None
    pending: list[tuple[str, str]] = []
    try:
        response = requests.post(
            f"{es_url}/{index}/_search",
            params={"scroll": "5m"},
            json={"size": max(1, int(batch_size)), "sort": ["_doc"], "_source": ["title", "source_origin"], "query": {"match_all": {}}},
            timeout=120,
            **options,
        )
        response.raise_for_status(); data = response.json(); scroll_id = data.get("_scroll_id")
        while True:
            hits = list((data.get("hits") or {}).get("hits") or [])
            if not hits:
                break
            for hit in hits:
                scanned += 1
                doc = str(hit.get("_id") or "")
                src = hit.get("_source") or {}
                title = str(src.get("title") or "")
                origin = known.get(doc)
                if origin in SPECIAL_ORIGINS:
                    restored += 1
                else:
                    normalized_title = normalize_cloud_path(title).casefold()
                    parent = normalized_title.rsplit("/", 1)[0] if "/" in normalized_title else ""
                    if normalized_title and normalized_title in mail_sidecar_paths:
                        inferred = "mail_archive"
                        source = "mailmeta_reconcile"
                    elif parent and parent in mail_container_dirs:
                        inferred = "mail_archive"
                        source = "mail_marker_reconcile"
                    else:
                        inferred = classify_source_origin(title)
                        source = "path_reconcile"
                    if inferred in SPECIAL_ORIGINS:
                        origin = inferred
                        registry.set(doc, origin, source_path=title, classification_source=source)
                        known[doc] = origin
                        discovered += 1
                if origin in SPECIAL_ORIGINS and str(src.get("source_origin") or "") != origin:
                    pending.append((doc, origin))
                    if len(pending) >= batch_size:
                        updated += _bulk_update(es_url, index, pending, options); pending.clear()
            response = requests.post(
                f"{es_url}/_search/scroll", json={"scroll": "5m", "scroll_id": scroll_id}, timeout=120, **options
            )
            response.raise_for_status(); data = response.json(); scroll_id = data.get("_scroll_id", scroll_id)
        if pending:
            updated += _bulk_update(es_url, index, pending, options)
    finally:
        if scroll_id:
            try:
                requests.delete(f"{es_url}/_search/scroll", json={"scroll_id": [scroll_id]}, timeout=30, **options)
            except Exception:
                log.debug("Failed to clear Elasticsearch reconcile scroll", exc_info=True)
        registry.close()
    return {
        "scanned": scanned,
        "discovered": discovered,
        "registry_hits": restored,
        "es_updated": updated,
        "mail_sidecars_seen": mail_sidecars_seen,
        "mail_sidecars_parsed": mail_sidecars_parsed,
        "mail_sidecar_files": len(mail_sidecar_paths),
        "mail_containers": len(mail_container_dirs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the RAG source-origin registry")
    parser.add_argument("action", choices=["reconcile", "stats"])
    args = parser.parse_args()
    if args.action == "reconcile":
        print(json.dumps(reconcile(), ensure_ascii=False, indent=2)); return 0
    registry = SourceRegistry()
    try:
        counts: dict[str, int] = {}
        for _doc, origin, _path, _source in registry.rows(): counts[origin] = counts.get(origin, 0) + 1
        print(json.dumps({"path": str(registry.path), "counts": counts, "total": sum(counts.values())}, ensure_ascii=False, indent=2))
    finally:
        registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
