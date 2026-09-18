#!/usr/bin/env python3
"""Small server-rendered graph curator UI for the existing FastAPI service.

No SPA, no Node.js and no direct browser-to-Neo4j access.  Every mutation goes
through GraphCurator / GraphQueue, i.e. the same backend operations used by the
CLI.  High-impact actions are preview-first.
"""

from __future__ import annotations
from rag.version import VERSION

import asyncio
import base64
import json
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates

from rag.curator import GraphCurator
from rag.graph import cfg_get
from rag.graph_queue import GraphQueue
from rag.credential_store import CredentialStore, canonical_credential_owner
from rag.carddav_sync import CardDAVClient, CardDAVSettings, sync_for_canonical_user
from rag.mail_sync import probe_mailboxes


POLICIES = ("exclusive", "contextual", "search_only", "document_only")
PRIORITIES = ("high", "normal", "background")
HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "templates" / "admin"
CSS_FILE = HERE / "static" / "admin" / "admin.css"
JS_FILE = HERE / "static" / "admin" / "admin.js"


def _env_or_cfg(cfg: dict[str, Any], direct_path: str, env_path: str, default: str = "") -> str:
    env_name = str(cfg_get(cfg, env_path, default="") or "").strip()
    if env_name:
        value = os.getenv(env_name, "")
        if value:
            return value
    return str(cfg_get(cfg, direct_path, default=default) or default)


def _split_lines(value: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(value or "").replace("\r", "\n").split("\n"):
        item = raw.strip().strip("/")
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def _label_type(labels: Any) -> str:
    values = [str(x) for x in (labels or [])]
    for name in ("Person", "Organization", "OrganizationalUnit"):
        if name in values:
            return name
    return "Entity"


def _queue_contact_relink(queue: GraphQueue, document_ids: list[str], *, reason: str, priority: str = "high") -> dict[str, Any]:
    ids = [str(x).strip() for x in document_ids if str(x or "").strip()]
    if not ids:
        return {"queued": 0, "coalesced": 0, "document_count": 0}
    result = queue.enqueue_evidence({
        "query_id": reason,
        "user_query": "",
        "retrieval_query": "",
        "evidence_action": reason,
        "queue_priority": priority,
        "entity_discovery": False,
        "force_reindex": True,
        "count_evidence": False,
        "documents": [{"document_id": document_id} for document_id in ids],
    })
    return {"document_count": len(ids), **result}


def create_admin_router(cfg: dict[str, Any], graph_queue: GraphQueue, web_cfg: dict[str, Any] | None = None) -> APIRouter:
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    router = APIRouter(prefix="/rag-admin", tags=["admin"], include_in_schema=False)

    enabled = bool(cfg_get(cfg, "admin_ui.enabled", default=True))
    allow_unauthenticated = bool(cfg_get(cfg, "admin_ui.allow_unauthenticated", default=False))
    username = _env_or_cfg(cfg, "admin_ui.username", "admin_ui.username_env", "")
    password = _env_or_cfg(cfg, "admin_ui.password", "admin_ui.password_env", "")
    nextcloud_base_url = str(
        os.getenv("NEXTCLOUD_BASE_URL", "")
        or cfg_get(cfg, "nextcloud.base_url", default="")
        or ""
    ).strip().rstrip("/")
    user_store = CredentialStore(
        str(cfg_get(cfg, "auth.credential_store", default=cfg_get(cfg, "acl.credential_store", default="runtime/users.sqlite")) or "runtime/users.sqlite")
    )

    contact_sync_lock = threading.Lock()
    contact_sync_jobs: dict[str, dict[str, Any]] = {}
    contact_sync_active: dict[str, str] = {}

    def _contact_job_snapshot(job_id: str) -> dict[str, Any] | None:
        with contact_sync_lock:
            job = contact_sync_jobs.get(job_id)
            return dict(job) if job else None

    def _contact_active_job(canonical_user_id: str) -> dict[str, Any] | None:
        with contact_sync_lock:
            job_id = contact_sync_active.get(canonical_user_id)
            job = contact_sync_jobs.get(job_id or "") if job_id else None
            return dict(job) if job else None

    def _update_contact_job(job_id: str, payload: dict[str, Any]) -> None:
        with contact_sync_lock:
            job = contact_sync_jobs.get(job_id)
            if not job:
                return
            total = int(payload.get("contacts_total") or job.get("contacts_total") or 0)
            seen = int(payload.get("contacts_seen") or 0)
            job.update({
                "phase": str(payload.get("phase") or job.get("phase") or "importing"),
                "contacts_total": total,
                "contacts_seen": seen,
                "contacts_written": int(payload.get("contacts_written") or 0),
                "contacts_repaired": int(payload.get("contacts_repaired") or 0),
                "contacts_deleted": int(payload.get("contacts_deleted") or 0),
                "error_count": len(payload.get("errors") or []),
                "current_addressbook": str(payload.get("current_addressbook") or ""),
                "percent": (min(100, int((seen * 100) / total)) if total > 0 else 0),
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            })

    def _run_contact_job(job_id: str, user: Any) -> None:
        try:
            result = sync_for_canonical_user(
                cfg, user_store, user, progress=lambda payload: _update_contact_job(job_id, payload)
            )
            with contact_sync_lock:
                job = contact_sync_jobs.get(job_id)
                if job is not None:
                    job.update({
                        "status": str(result.get("status") or "completed"),
                        "phase": "completed",
                        "contacts_total": int(result.get("contacts_total") or result.get("contacts_seen") or 0),
                        "contacts_seen": int(result.get("contacts_seen") or 0),
                        "contacts_written": int(result.get("contacts_written") or 0),
                        "contacts_repaired": int(result.get("contacts_repaired") or 0),
                        "contacts_deleted": int(result.get("contacts_deleted") or 0),
                        "error_count": len(result.get("errors") or []),
                        "errors": list(result.get("errors") or [])[:10],
                        "percent": 100,
                        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    })
        except Exception as exc:
            with contact_sync_lock:
                job = contact_sync_jobs.get(job_id)
                if job is not None:
                    job.update({
                        "status": "failed",
                        "phase": "failed",
                        "error_count": max(1, int(job.get("error_count") or 0)),
                        "fatal_error": f"{type(exc).__name__}: {exc}",
                        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    })
        finally:
            with contact_sync_lock:
                if contact_sync_active.get(str(user.canonical_user_id)) == job_id:
                    contact_sync_active.pop(str(user.canonical_user_id), None)

    def _discover_contact_addressbooks(user: Any) -> tuple[list[dict[str, Any]], str]:
        credential = user_store.get_nextcloud_credential_for_canonical_user(user.canonical_user_id)
        if credential is None:
            return [], "Kein Nextcloud-Credential vorhanden"
        contact_settings = user_store.get_contact_sync_settings(user.canonical_user_id)
        try:
            settings = CardDAVSettings.for_canonical_user(cfg, user, credential, contact_settings)
            with CardDAVClient(settings) as dav:
                books = dav.discover_addressbooks()
            includes = {x.casefold() for x in settings.include_addressbooks}
            excludes = {x.casefold() for x in settings.exclude_addressbooks}
            out: list[dict[str, Any]] = []
            for book in books:
                keys = {str(book.get("displayname") or "").casefold(), str(book.get("slug") or "").casefold()}
                excluded = bool(keys & excludes)
                selected = (not includes or bool(keys & includes)) and not excluded
                out.append({**book, "selected": selected, "excluded": excluded})
            return out, ""
        except Exception as exc:
            return [], f"{type(exc).__name__}: {exc}"

    def _discover_mail_account_mailboxes(account: Any) -> tuple[list[dict[str, Any]], str]:
        if account is None:
            return [], "Zuerst Mailkonto-Konfiguration speichern"
        credential = user_store.get_mail_secret(account)
        if credential is None:
            return [], "Kein IMAP-Credential vorhanden"
        try:
            infos = probe_mailboxes(account, credential.secret)
            roots = list(account.mailboxes)
            out: list[dict[str, Any]] = []
            for info in infos:
                covered_by = info.covered_by(roots)
                exact_root = any(
                    info.name == root or (info.name.casefold() == "inbox" and str(root).casefold() == "inbox")
                    for root in roots
                )
                out.append({
                    "name": info.name,
                    "delimiter": info.delimiter or "",
                    "flags": list(info.flags),
                    "selectable": info.selectable,
                    "depth": info.depth,
                    "configured_root": exact_root,
                    "covered_by": covered_by,
                })
            out.sort(key=lambda item: str(item.get("name") or "").casefold())
            return out, ""
        except Exception as exc:
            return [], f"{type(exc).__name__}: {exc}"

    async def require_admin(request: Request) -> None:
        if not enabled:
            raise HTTPException(status_code=404, detail="Admin UI ist deaktiviert")
        if allow_unauthenticated:
            return
        if not username or not password:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Admin UI ist aktiviert, aber keine Zugangsdaten sind konfiguriert. "
                    "Setze admin_ui.username(_env) und admin_ui.password(_env)."
                ),
            )
        header = str(request.headers.get("authorization") or "")
        if not header.lower().startswith("basic "):
            raise HTTPException(status_code=401, detail="Authentifizierung erforderlich", headers={"WWW-Authenticate": 'Basic realm="RAG Admin"'})
        try:
            decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
            supplied_user, supplied_password = decoded.split(":", 1)
        except Exception:
            raise HTTPException(status_code=401, detail="Ungültige Authentifizierung", headers={"WWW-Authenticate": 'Basic realm="RAG Admin"'})
        if not (secrets.compare_digest(supplied_user, username) and secrets.compare_digest(supplied_password, password)):
            raise HTTPException(status_code=401, detail="Ungültige Authentifizierung", headers={"WWW-Authenticate": 'Basic realm="RAG Admin"'})

    auth = [Depends(require_admin)]

    def base_context(request: Request, **extra: Any) -> dict[str, Any]:
        return {
            "request": request,
            "version": VERSION,
            "message": request.query_params.get("msg", ""),
            "policies": POLICIES,
            "priorities": PRIORITIES,
            "unauthenticated_warning": bool(allow_unauthenticated),
            **extra,
        }

    def _secure_headers(response: Any) -> Any:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        )
        return response

    def render(request: Request, name: str, **context: Any) -> HTMLResponse:
        response = templates.TemplateResponse(
            request=request,
            name=name,
            context=base_context(request, **context),
        )
        return _secure_headers(response)

    def error_page(request: Request, exc: Exception, *, status_code: int = 500) -> HTMLResponse:
        back_url = str(request.app.url_path_for("admin_overview"))
        referer = str(request.headers.get("referer") or "").strip()
        if referer:
            parsed = urlparse(referer)
            if (not parsed.netloc) or parsed.netloc.lower() in _request_host_candidates(request):
                back_url = referer
        return render(
            request,
            "error.html",
            status_code=status_code,
            error=f"{type(exc).__name__}: {exc}",
            back_url=back_url,
        )

    def redirect(url: str, message: str = "") -> RedirectResponse:
        if message:
            joiner = "&" if "?" in url else "?"
            url = f"{url}{joiner}{urlencode({'msg': message})}"
        return _secure_headers(RedirectResponse(url=url, status_code=303))

    def _request_host_candidates(request: Request) -> set[str]:
        # Admin URLs are deliberately path-only, so rendering does not depend on
        # proxy Host/Scheme rewriting.  For the POST origin guard we still accept
        # both the direct Host and the standard forwarded host supplied by a
        # trusted reverse proxy.
        hosts: set[str] = set()
        for header_name in ("host", "x-forwarded-host"):
            raw = str(request.headers.get(header_name) or "")
            for value in raw.split(","):
                value = value.strip().lower()
                if value:
                    hosts.add(value)
        return hosts

    async def form_values(request: Request) -> dict[str, list[str]]:
        # A plain urlencoded parser keeps the UI dependency-free apart from Jinja2.
        # Keep all values so checkbox/bulk forms can submit repeated finding_id fields.
        origin = str(request.headers.get("origin") or "").strip()
        if origin:
            parsed = urlparse(origin)
            if parsed.netloc and parsed.netloc.lower() not in _request_host_candidates(request):
                raise HTTPException(status_code=403, detail="Cross-origin Admin-POST verweigert")
        raw = (await request.body()).decode("utf-8", errors="replace")
        return parse_qs(raw, keep_blank_values=True)

    async def form_data(request: Request) -> dict[str, str]:
        values = await form_values(request)
        return {key: (items[-1] if items else "") for key, items in values.items()}

    def nextcloud_document_url(document_id: str, path: str) -> str:
        if not nextcloud_base_url:
            return ""
        document_id = str(document_id or "").strip()
        if not document_id.startswith("files:"):
            return ""
        openfile = document_id.split(":", 1)[1].strip()
        if not openfile:
            return ""
        path = str(path or "").strip().replace("\\", "/").strip("/")
        if path and "/" in path:
            directory = "/" + str(PurePosixPath(path).parent).strip("/")
        else:
            directory = "/"
        params = urlencode({"dir": directory, "openfile": openfile})
        return f"{nextcloud_base_url}/index.php/apps/files/?{params}"

    def add_doc_links(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["nextcloud_url"] = nextcloud_document_url(
                str(item.get("document_id") or ""),
                str(item.get("document_path") or item.get("document_title") or ""),
            )
            out.append(item)
        return out

    def compact_for_display(value: Any, *, max_items: int = 50) -> Any:
        if isinstance(value, dict):
            return {k: compact_for_display(v, max_items=max_items) for k, v in value.items() if not str(k).startswith("_")}
        if isinstance(value, list):
            shown = [compact_for_display(v, max_items=max_items) for v in value[:max_items]]
            if len(value) > max_items:
                shown.append(f"… {len(value) - max_items} weitere Einträge")
            return shown
        return value

    def preview_response(
        request: Request,
        *,
        title: str,
        preview: dict[str, Any],
        action_url: str,
        fields: dict[str, Any],
        danger: bool = False,
        confirm_label: str = "Ausführen",
        cancel_url: str = "/rag-admin/",
    ) -> HTMLResponse:
        clean_preview = compact_for_display(preview)
        hidden = [{"name": key, "value": "" if value is None else str(value)} for key, value in fields.items()]
        hidden.append({"name": "confirm", "value": "yes"})
        return render(
            request,
            "preview.html",
            title=title,
            preview=clean_preview,
            preview_json=json.dumps(clean_preview, ensure_ascii=False, indent=2, default=str),
            action_url=action_url,
            hidden=hidden,
            danger=danger,
            confirm_label=confirm_label,
            cancel_url=cancel_url,
        )

    @router.get("/assets/admin.css", include_in_schema=False, dependencies=auth)
    async def admin_css() -> FileResponse:
        response = FileResponse(CSS_FILE, media_type="text/css")
        response.headers["Cache-Control"] = "private, max-age=300"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @router.get("/assets/admin.js", include_in_schema=False, name="admin_js", dependencies=auth)
    async def admin_js() -> FileResponse:
        response = FileResponse(JS_FILE, media_type="application/javascript")
        response.headers["Cache-Control"] = "private, max-age=300"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @router.get("/security", response_class=HTMLResponse, name="admin_security", dependencies=auth)
    async def admin_security(request: Request):
        status = user_store.secret_security_status()
        env_names = (
            "LLM_API_KEY", "EMBEDDING_API_KEY", "GRAPH_ENTITY_API_KEY",
            "GRAPH_RELATION_API_KEY", "WEB_SEARCH_API_KEY", "WEB_LLM_API_KEY",
            "ELASTICSEARCH_PASSWORD", "NEO4J_PASSWORD", "RAG_ADMIN_PASSWORD",
            "PROVIDER_API_KEY",
        )
        env_status = [{"name": name, "configured": bool(os.getenv(name, ""))} for name in env_names]
        return render(request, "security.html", secret_status=status, env_status=env_status)

    @router.post("/security/migrate", name="admin_security_migrate", dependencies=auth)
    async def admin_security_migrate(request: Request):
        try:
            changed = user_store.migrate_plaintext_secrets()
            return redirect(
                str(request.app.url_path_for("admin_security")),
                f"Secret-Migration abgeschlossen: {changed['credentials']} Credential(s), {changed['flows']} Login-Flow(s)",
            )
        except Exception as exc:
            return error_page(request, exc, status_code=400)

    @router.get("/users", response_class=HTMLResponse, name="admin_users", dependencies=auth)
    async def admin_users(request: Request):
        rows: list[dict[str, Any]] = []
        for user in user_store.list_canonical_users():
            mail_accounts = user_store.list_mail_accounts(user.canonical_user_id)
            web_settings = user_store.get_web_settings(user.canonical_user_id)
            contact_settings = user_store.get_contact_sync_settings(user.canonical_user_id)
            rows.append({
                "user": user,
                "bindings": user_store.list_bindings(user.canonical_user_id),
                "mail_accounts": mail_accounts,
                "web_settings": web_settings,
                "contact_settings": contact_settings,
                "has_nextcloud_credential": user_store.get_nextcloud_credential_for_canonical_user(user.canonical_user_id) is not None,
            })
        return render(request, "users.html", rows=rows)

    @router.get("/users/{canonical_user_id}", response_class=HTMLResponse, name="admin_user_detail", dependencies=auth)
    async def admin_user_detail(request: Request, canonical_user_id: str):
        user = user_store.get_canonical_user(canonical_user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Unbekannter kanonischer Benutzer")
        mail_accounts = user_store.list_mail_accounts(canonical_user_id)
        mail_account = mail_accounts[0] if mail_accounts else None
        mailboxes: list[dict[str, Any]] = []
        mailbox_error = ""
        mailbox_discovery_requested = request.query_params.get("discover_mailboxes", "") == "1"
        if mailbox_discovery_requested:
            mailboxes, mailbox_error = _discover_mail_account_mailboxes(mail_account)
        contact_settings = user_store.get_contact_sync_settings(canonical_user_id)
        addressbooks: list[dict[str, Any]] = []
        addressbook_error = ""
        addressbook_discovery_requested = request.query_params.get("discover_addressbooks", "") == "1"
        if addressbook_discovery_requested:
            addressbooks, addressbook_error = _discover_contact_addressbooks(user)
        contact_last_sync = "nie"
        if contact_settings is not None and contact_settings.last_sync_at:
            contact_last_sync = datetime.fromtimestamp(contact_settings.last_sync_at).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        return render(
            request,
            "user.html",
            user=user,
            bindings=user_store.list_bindings(canonical_user_id),
            mail_accounts=mail_accounts,
            mail_account=mail_account,
            mailboxes=mailboxes,
            mailbox_error=mailbox_error,
            mailbox_discovery_requested=mailbox_discovery_requested,
            web_settings=user_store.get_web_settings(canonical_user_id),
            contact_settings=contact_settings,
            contact_last_sync=contact_last_sync,
            contact_sync_job=_contact_active_job(canonical_user_id),
            contact_addressbooks=addressbooks,
            contact_addressbook_error=addressbook_error,
            contact_addressbook_discovery_requested=addressbook_discovery_requested,
            has_nextcloud_credential=user_store.get_nextcloud_credential_for_canonical_user(canonical_user_id) is not None,
            mail_engine_enabled=bool(cfg_get(cfg, "mail.enabled", default=False)),
            web_engine_enabled=bool((web_cfg or {}).get("enabled", False)),
        )

    @router.post("/users/{canonical_user_id}/reauth", name="admin_user_reauth", dependencies=auth)
    async def admin_user_reauth(request: Request, canonical_user_id: str):
        user = user_store.get_canonical_user(canonical_user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Unbekannter kanonischer Benutzer")
        result = user_store.clear_nextcloud_credentials_for_canonical_user(canonical_user_id)
        return redirect(
            str(request.app.url_path_for("admin_user_detail", canonical_user_id=canonical_user_id)),
            f"Nextcloud Re-Auth vorbereitet ({result['credentials_deleted']} Credential(s) entfernt)",
        )

    @router.post("/users/{canonical_user_id}/enabled", name="admin_user_enabled", dependencies=auth)
    async def admin_user_enabled(request: Request, canonical_user_id: str):
        data = await form_data(request)
        enabled_value = data.get("enabled", "") == "yes"
        if not user_store.set_canonical_user_enabled(canonical_user_id, enabled_value):
            raise HTTPException(status_code=404, detail="Unbekannter kanonischer Benutzer")
        return redirect(
            str(request.app.url_path_for("admin_user_detail", canonical_user_id=canonical_user_id)),
            "Benutzer aktiviert" if enabled_value else "Benutzer deaktiviert",
        )

    @router.post("/users/{canonical_user_id}/web", name="admin_user_web", dependencies=auth)
    async def admin_user_web(request: Request, canonical_user_id: str):
        data = await form_data(request)
        try:
            archive_enabled = data.get("archive_enabled") == "on"
            target_path = data.get("target_path", "").strip()
            if archive_enabled and not target_path:
                target_path = "RAG/Webarchiv"
            settings = user_store.set_web_settings(
                canonical_user_id,
                enabled=data.get("enabled") == "on",
                archive_enabled=archive_enabled,
                target_path=target_path,
            )
            return redirect(
                str(request.app.url_path_for("admin_user_detail", canonical_user_id=canonical_user_id)),
                f"Web-Konfiguration gespeichert (Ziel: {settings.target_path or 'kein Archiv'})",
            )
        except Exception as exc:
            return error_page(request, exc, status_code=400)

    @router.post("/users/{canonical_user_id}/contacts", name="admin_user_contacts", dependencies=auth)
    async def admin_user_contacts(request: Request, canonical_user_id: str):
        user = user_store.get_canonical_user(canonical_user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Unbekannter Nextcloud-Benutzer")
        data = await form_data(request)
        try:
            settings = user_store.set_contact_sync_settings(
                canonical_user_id,
                enabled=data.get("enabled") == "on",
                include_addressbooks=_split_lines(data.get("include_addressbooks", "")),
                exclude_addressbooks=_split_lines(data.get("exclude_addressbooks", "")),
            )
            return redirect(
                str(request.app.url_path_for("admin_user_detail", canonical_user_id=canonical_user_id)),
                "Kontakt-DB-Konfiguration gespeichert" if settings.enabled else "Kontakt-DB für diesen Benutzer deaktiviert",
            )
        except Exception as exc:
            return error_page(request, exc, status_code=400)

    @router.post("/users/{canonical_user_id}/contacts/sync", name="admin_user_contacts_sync", dependencies=auth)
    async def admin_user_contacts_sync(
        request: Request, canonical_user_id: str, background_tasks: BackgroundTasks
    ):
        user = user_store.get_canonical_user(canonical_user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Unbekannter Nextcloud-Benutzer")
        active = _contact_active_job(canonical_user_id)
        if active and str(active.get("status") or "") == "running":
            return redirect(
                str(request.app.url_path_for(
                    "admin_user_contacts_sync_status",
                    canonical_user_id=canonical_user_id,
                    job_id=str(active["job_id"]),
                )),
                "Kontakt-Sync läuft bereits",
            )
        job_id = secrets.token_urlsafe(10)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with contact_sync_lock:
            contact_sync_jobs[job_id] = {
                "job_id": job_id,
                "canonical_user_id": canonical_user_id,
                "status": "running",
                "phase": "starting",
                "contacts_total": 0,
                "contacts_seen": 0,
                "contacts_written": 0,
                "contacts_repaired": 0,
                "contacts_deleted": 0,
                "error_count": 0,
                "percent": 0,
                "current_addressbook": "",
                "started_at": now,
                "updated_at": now,
            }
            contact_sync_active[canonical_user_id] = job_id
        background_tasks.add_task(_run_contact_job, job_id, user)
        return redirect(
            str(request.app.url_path_for(
                "admin_user_contacts_sync_status", canonical_user_id=canonical_user_id, job_id=job_id
            ))
        )

    @router.get(
        "/users/{canonical_user_id}/contacts/sync/{job_id}",
        name="admin_user_contacts_sync_status",
        dependencies=auth,
    )
    async def admin_user_contacts_sync_status(request: Request, canonical_user_id: str, job_id: str):
        user = user_store.get_canonical_user(canonical_user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Unbekannter Nextcloud-Benutzer")
        job = _contact_job_snapshot(job_id)
        if job is None or str(job.get("canonical_user_id") or "") != canonical_user_id:
            raise HTTPException(status_code=404, detail="Kontakt-Sync-Job nicht gefunden")
        response = render(request, "contact_sync.html", user=user, job=job)
        if str(job.get("status") or "") == "running":
            response.headers["Refresh"] = "2"
        return response

    @router.post("/users/{canonical_user_id}/mail", name="admin_user_mail", dependencies=auth)
    async def admin_user_mail(request: Request, canonical_user_id: str):
        data = await form_data(request)
        try:
            existing = user_store.list_mail_accounts(canonical_user_id)
            account_id = data.get("account_id", "").strip()
            if not account_id and existing:
                account_id = existing[0].account_id
            if account_id:
                current = user_store.get_mail_account(account_id)
                if current is not None and current.canonical_user_id != canonical_user_id:
                    raise ValueError("Mailkonto gehört zu einem anderen Benutzer")
            account = user_store.save_mail_account(
                canonical_user_id,
                account_id=account_id,
                name=data.get("name", "primary"),
                enabled=data.get("enabled") == "on",
                host=data.get("host", ""),
                port=int(data.get("port") or 993),
                security=data.get("security", "tls"),
                verify_tls=data.get("verify_tls") == "on",
                username=data.get("username", ""),
                password="",
                mailboxes=data.get("mailboxes", "INBOX"),
                max_messages_per_run=int(data.get("max_messages_per_run") or 50),
                not_before=data.get("not_before", ""),
                store_eml=data.get("store_eml") == "on",
                store_attachments=data.get("store_attachments") == "on",
                target_path=data.get("target_path", ""),
                eml_target_path=data.get("eml_target_path", ""),
            )
            suffix = "" if account.has_secret else " – IMAP-Credential fehlt noch"
            return redirect(
                str(request.app.url_path_for("admin_user_detail", canonical_user_id=canonical_user_id)),
                f"Mailkonto {account.name} gespeichert{suffix}",
            )
        except Exception as exc:
            return error_page(request, exc, status_code=400)

    @router.post("/users/{canonical_user_id}/mail/credential", name="admin_user_mail_credential", dependencies=auth)
    async def admin_user_mail_credential(request: Request, canonical_user_id: str):
        data = await form_data(request)
        try:
            account_id = data.get("account_id", "").strip()
            account = user_store.get_mail_account(account_id)
            if account is None or account.canonical_user_id != canonical_user_id:
                raise ValueError("Unbekanntes Mailkonto")
            password_value = str(data.get("password") or "")
            if not password_value:
                raise ValueError("IMAP-Passwort darf nicht leer sein")
            user_store.set_mail_secret(account_id, password_value)
            return redirect(
                str(request.app.url_path_for("admin_user_detail", canonical_user_id=canonical_user_id)),
                "IMAP-Credential verschlüsselt gespeichert/ersetzt",
            )
        except Exception as exc:
            return error_page(request, exc, status_code=400)

    @router.post("/users/{canonical_user_id}/mail/delete", name="admin_user_mail_delete", dependencies=auth)
    async def admin_user_mail_delete(request: Request, canonical_user_id: str):
        data = await form_data(request)
        account_id = data.get("account_id", "").strip()
        if account_id:
            account = user_store.get_mail_account(account_id)
            if account is not None and account.canonical_user_id != canonical_user_id:
                return error_page(request, ValueError("Mailkonto gehört zu einem anderen Benutzer"), status_code=400)
            user_store.delete_mail_account(account_id)
        return redirect(
            str(request.app.url_path_for("admin_user_detail", canonical_user_id=canonical_user_id)),
            "Mailkonto entfernt",
        )

    @router.get("/", response_class=HTMLResponse, name="admin_overview", dependencies=auth)
    async def admin_overview(request: Request):
        try:
            with GraphCurator.from_config(cfg) as curator:
                stats = curator.graph.stats()
                sources = curator.list_contact_sources()
            queue = graph_queue.stats()
            users = user_store.list_canonical_users()
            mail_accounts = user_store.list_mail_accounts()
            secret_status = user_store.secret_security_status()
            security_ok = bool(
                secret_status.get("master_key", {}).get("valid")
                and int(secret_status.get("credentials_plaintext") or 0) == 0
                and int(secret_status.get("flows_plaintext") or 0) == 0
            )
            return render(
                request,
                "overview.html",
                stats=stats,
                queue=queue,
                contact_sources=len(sources),
                user_stats={"total": len(users), "enabled": sum(1 for user in users if user.enabled)},
                mail_accounts=len(mail_accounts),
                security_ok=security_ok,
                services={
                    "sync_worker": bool(cfg_get(cfg, "sync_worker.enabled", default=False)),
                    "mail_feature": bool(cfg_get(cfg, "mail.enabled", default=False)),
                    "mail_worker": bool(cfg_get(cfg, "mail.worker.enabled", default=False)),
                    "graph_worker": bool(cfg_get(cfg, "graph_queue.worker.enabled", default=False)),
                    "graph_auto_enqueue": bool(cfg_get(cfg, "graph_queue.auto_enqueue_cited_documents", default=False)),
                    "web": bool((web_cfg or {}).get("enabled", False)),
                },
            )
        except Exception as exc:
            return error_page(request, exc)

    @router.get("/entities", response_class=HTMLResponse, name="admin_entities", dependencies=auth)
    async def admin_entities(request: Request, q: str = "", limit: int = 50):
        try:
            rows: list[dict[str, Any]] = []
            if q.strip():
                with GraphCurator.from_config(cfg) as curator:
                    rows = curator.find_entities(q, limit=max(1, min(limit, 200)))
            for row in rows:
                row["entity_type"] = _label_type(row.get("labels"))
            return render(request, "entities.html", q=q, entities=rows)
        except Exception as exc:
            return error_page(request, exc)

    @router.get("/relations", response_class=HTMLResponse, name="admin_relations", dependencies=auth)
    async def admin_relations(request: Request, q: str = "", limit: int = 100):
        try:
            with GraphCurator.from_config(cfg) as curator:
                rows = curator.list_relations(q, limit=max(1, min(limit, 500)))
            rows = add_doc_links(rows)
            return render(request, "relations.html", q=q, relations=rows)
        except Exception as exc:
            return error_page(request, exc)

    @router.get("/findings", response_class=HTMLResponse, name="admin_findings", dependencies=auth)
    async def admin_findings(request: Request, q: str = "", state: str = "open", limit: int = 200):
        try:
            state = str(state or "open").strip().casefold()
            allowed_states = {"inbox", "all", "open", "entities_resolved", "claimed", "no_entity", "suppressed"}
            if state not in allowed_states:
                state = "open"
            with GraphCurator.from_config(cfg) as curator:
                all_rows = curator.list_research_findings(q, limit=max(1, min(limit, 1000)))
                counts = {key: 0 for key in ("open", "entities_resolved", "claimed", "no_entity", "suppressed")}
                for row in all_rows:
                    key = str(row.get("graph_state") or "open")
                    if key in counts:
                        counts[key] += 1
                if state == "inbox":
                    rows = [row for row in all_rows if row.get("graph_state") in {"open", "entities_resolved"}]
                elif state == "all":
                    rows = all_rows
                else:
                    rows = [row for row in all_rows if row.get("graph_state") == state]
                rows = add_doc_links(rows)

                # Entity-centric work queue. One finding may occur in multiple groups
                # when more than one entity text still needs a curator decision.
                grouped: dict[str, dict[str, Any]] = {}
                for row in rows:
                    entity_texts = [str(x).strip() for x in (row.get("entity_texts") or []) if str(x or "").strip()]
                    curated = {str(x.get("text") or "").casefold() for x in (row.get("curated_entities") or []) if x}
                    suppressed = {str(x).casefold() for x in (row.get("suppressed_entity_texts") or [])}
                    unresolved = [text for text in entity_texts if text.casefold() not in curated | suppressed]
                    group_texts = unresolved if unresolved else (["__no_entity__"] if not entity_texts else ["__resolved__"])
                    for entity_text in group_texts:
                        key = entity_text.casefold()
                        group = grouped.setdefault(key, {
                            "key": key,
                            "entity_text": "" if entity_text.startswith("__") else entity_text,
                            "kind": "no_entity" if entity_text == "__no_entity__" else "resolved" if entity_text == "__resolved__" else "entity",
                            "rows": [],
                            "suggestions": [],
                        })
                        group["rows"].append(row)
                for group in grouped.values():
                    if group["kind"] == "entity":
                        group["suggestions"] = curator.find_entities(group["entity_text"], limit=6)
                groups = sorted(grouped.values(), key=lambda g: (g["kind"] != "entity", -len(g["rows"]), g["entity_text"].casefold()))
            return render(request, "findings.html", q=q, state=state, counts=counts, findings=rows, finding_groups=groups)
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/findings/bulk-entity", name="admin_findings_bulk_entity", dependencies=auth)
    async def admin_findings_bulk_entity(request: Request):
        try:
            values = await form_values(request)
            finding_ids = [x.strip() for x in values.get("finding_id", []) if x.strip()]
            entity_text = (values.get("entity_text", [""])[-1] or "").strip()
            action = (values.get("action", [""])[-1] or "").strip().casefold()
            target_entity_id = (values.get("target_entity_id", [""])[-1] or "").strip()
            reason = (values.get("reason", [""])[-1] or "bulk_findings_curation").strip()
            if not finding_ids:
                raise ValueError("Keine Findings ausgewählt")
            if not entity_text:
                raise ValueError("Entity-Text fehlt")
            if action not in {"resolve", "suppress"}:
                raise ValueError("Ungültige Bulk-Aktion")
            if action == "resolve" and not target_entity_id:
                raise ValueError("Bitte eine Ziel-Entity auswählen")
            with GraphCurator.from_config(cfg) as curator:
                result = curator.bulk_curate_research_finding_entities(
                    finding_ids,
                    entity_text=entity_text,
                    action=action,
                    target_entity_id=target_entity_id,
                    reason=reason,
                    apply=True,
                )
            failures = list(result.get("failures") or [])
            updated = int(result.get("updated") or 0)
            requested = int(result.get("requested") or len(finding_ids))
            if failures and updated == 0:
                details = "; ".join(str(item.get("error") or "unbekannter Fehler") for item in failures[:3])
                raise ValueError(f"Keine Entity-Entscheidung übernommen ({len(failures)} Fehler): {details}")
            message = f"{updated}/{requested} Entity-Entscheidungen übernommen"
            if failures:
                message += f"; {len(failures)} Fehler – betroffene Findings bleiben offen"
            return redirect(str(request.app.url_path_for("admin_findings")) + "?state=open", message)
        except Exception as exc:
            return error_page(request, exc, status_code=400)

    @router.post("/findings/suppress-no-entity", name="admin_findings_suppress_no_entity", dependencies=auth)
    async def admin_findings_suppress_no_entity(request: Request):
        try:
            await form_data(request)  # origin/CSRF-equivalent host check
            with GraphCurator.from_config(cfg) as curator:
                result = curator.suppress_research_findings_without_entities(apply=True)
            return redirect(str(request.app.url_path_for("admin_findings")) + "?state=open", f"{result['updated']} Findings ohne Entity unterdrückt")
        except Exception as exc:
            return error_page(request, exc, status_code=400)

    @router.get("/finding/{finding_id}", response_class=HTMLResponse, name="admin_finding_detail", dependencies=auth)
    async def admin_finding_detail(request: Request, finding_id: str):
        try:
            with GraphCurator.from_config(cfg) as curator:
                detail = curator.get_research_finding(finding_id)
                entity_options = curator.research_finding_entity_options(finding_id) if detail else []
            if detail is None:
                raise ValueError(f"Finding nicht gefunden: {finding_id}")
            document = dict(detail.get("document") or {})
            if document:
                document.setdefault("document_title", document.get("title"))
                document.setdefault("document_path", document.get("path"))
                detail["document"] = add_doc_links([document])[0]
            detail["entity_options"] = entity_options
            return render(request, "finding.html", detail=detail)
        except ValueError as exc:
            return error_page(request, exc, status_code=404)
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/finding/{finding_id}/entity", name="admin_finding_entity", dependencies=auth)
    async def admin_finding_entity(request: Request, finding_id: str):
        data = await form_data(request)
        fields = {
            "entity_text": data.get("entity_text", "").strip(),
            "action": data.get("action", "").strip(),
            "target_entity_id": data.get("target_entity_id", "").strip(),
            "new_name": data.get("new_name", "").strip(),
            "entity_type": data.get("entity_type", "").strip(),
            "reason": data.get("reason", "").strip(),
        }
        confirm = data.get("confirm", "") == "yes"
        try:
            with GraphCurator.from_config(cfg) as curator:
                result = curator.curate_research_finding_entity(finding_id, apply=confirm, **fields)
            if not confirm:
                return preview_response(
                    request,
                    title="Finding-Entity kuratieren",
                    preview=result,
                    action_url=str(request.app.url_path_for("admin_finding_entity", finding_id=finding_id)),
                    fields=fields,
                    danger=fields["action"] == "suppress",
                    confirm_label="Entity-Entscheidung übernehmen",
                    cancel_url=str(request.app.url_path_for("admin_finding_detail", finding_id=finding_id)),
                )
            return redirect(
                str(request.app.url_path_for("admin_finding_detail", finding_id=finding_id)),
                "Entity-Resolution aktualisiert",
            )
        except Exception as exc:
            return error_page(request, exc, status_code=400)

    @router.post("/finding/{finding_id}/claim", name="admin_finding_claim", dependencies=auth)
    async def admin_finding_claim(request: Request, finding_id: str):
        data = await form_data(request)
        fields = {
            "subject_entity_id": data.get("subject_entity_id", "").strip(),
            "predicate_id": data.get("predicate_id", "").strip(),
            "object_entity_id": data.get("object_entity_id", "").strip(),
            "predicate_label": data.get("predicate_label", "").strip(),
            "claim_text": data.get("claim_text", "").strip(),
        }
        confirm = data.get("confirm", "") == "yes"
        try:
            with GraphCurator.from_config(cfg) as curator:
                result = curator.curate_research_finding_claim(finding_id, apply=confirm, **fields)
            if not confirm:
                return preview_response(
                    request,
                    title="Claim-Kandidat anlegen",
                    preview=result,
                    action_url=str(request.app.url_path_for("admin_finding_claim", finding_id=finding_id)),
                    fields=fields,
                    confirm_label="Claim anlegen",
                    cancel_url=str(request.app.url_path_for("admin_finding_detail", finding_id=finding_id)),
                )
            return redirect(
                str(request.app.url_path_for("admin_finding_detail", finding_id=finding_id)),
                "Dokumentgebundener Claim angelegt",
            )
        except Exception as exc:
            return error_page(request, exc, status_code=400)

    @router.post("/finding/{finding_id}/curate", name="admin_finding_curate", dependencies=auth)
    async def admin_finding_curate(request: Request, finding_id: str):
        data = await form_data(request)
        status = data.get("status", "").strip()
        reason = data.get("reason", "").strip()
        confirm = data.get("confirm", "") == "yes"
        if status not in {"", "suppressed"}:
            return error_page(request, ValueError(f"Ungültiger Finding-Status: {status}"), status_code=400)
        try:
            with GraphCurator.from_config(cfg) as curator:
                result = curator.curate_research_finding(
                    finding_id, status=status, reason=reason, apply=confirm
                )
            if not confirm:
                return preview_response(
                    request,
                    title="Research Finding kuratieren",
                    preview=result,
                    action_url=str(request.app.url_path_for("admin_finding_curate", finding_id=finding_id)),
                    fields={"status": status, "reason": reason},
                    confirm_label="Finding aktualisieren",
                    cancel_url=str(request.app.url_path_for("admin_finding_detail", finding_id=finding_id)),
                )
            return redirect(
                str(request.app.url_path_for("admin_finding_detail", finding_id=finding_id)),
                "Finding aktualisiert",
            )
        except Exception as exc:
            return error_page(request, exc)

    @router.get("/entity/{entity_id}", response_class=HTMLResponse, name="admin_entity_detail", dependencies=auth)
    async def admin_entity_detail(request: Request, entity_id: str):
        try:
            with GraphCurator.from_config(cfg) as curator:
                detail = curator.get_entity(entity_id)
            detail["entity"]["entity_type"] = _label_type(detail["entity"].get("labels"))
            detail["observations"] = add_doc_links(list(detail.get("observations") or []))
            return render(request, "entity.html", detail=detail)
        except ValueError as exc:
            return error_page(request, exc, status_code=404)
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/entity/{entity_id}/policy", name="admin_entity_policy", dependencies=auth)
    async def admin_entity_policy(request: Request, entity_id: str):
        data = await form_data(request)
        form = data.get("form", "")
        policy = data.get("policy", "")
        try:
            if policy not in POLICIES:
                raise ValueError(f"Ungültige Policy: {policy}")
            with GraphCurator.from_config(cfg) as curator:
                curator.set_form_policy(entity_id, form, policy, apply=True)
            return redirect(str(request.app.url_path_for("admin_entity_detail", entity_id=entity_id)), f"Policy für {form} auf {policy} gesetzt")
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/entity/{entity_id}/alias/add", name="admin_entity_alias_add", dependencies=auth)
    async def admin_entity_alias_add(request: Request, entity_id: str):
        data = await form_data(request)
        alias = data.get("alias", "").strip()
        policy = data.get("policy", "contextual")
        try:
            if policy not in ("exclusive", "contextual", "search_only"):
                raise ValueError(f"Ungültige Alias-Policy: {policy}")
            with GraphCurator.from_config(cfg) as curator:
                curator.add_alias(entity_id, alias, policy=policy, apply=True)
            return redirect(str(request.app.url_path_for("admin_entity_detail", entity_id=entity_id)), f"Alias hinzugefügt: {alias}")
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/entity/{entity_id}/alias/remove", name="admin_entity_alias_remove", dependencies=auth)
    async def admin_entity_alias_remove(request: Request, entity_id: str):
        data = await form_data(request)
        alias = data.get("alias", "").strip()
        try:
            with GraphCurator.from_config(cfg) as curator:
                curator.remove_alias(entity_id, alias, apply=True)
            return redirect(str(request.app.url_path_for("admin_entity_detail", entity_id=entity_id)), f"Alias entfernt: {alias}")
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/entity/{entity_id}/name", name="admin_entity_name", dependencies=auth)
    async def admin_entity_name(request: Request, entity_id: str):
        data = await form_data(request)
        new_name = data.get("new_name", "").strip()
        reason = data.get("reason", "manual_name_correction").strip() or "manual_name_correction"
        confirm = data.get("confirm", "") == "yes"
        try:
            with GraphCurator.from_config(cfg) as curator:
                result = curator.correct_name(entity_id, new_name, reason=reason, apply=confirm)
            if not confirm:
                return preview_response(
                    request,
                    title="Kanonischen Namen ändern",
                    preview=result,
                    action_url=str(request.app.url_path_for("admin_entity_name", entity_id=entity_id)),
                    fields={"new_name": new_name, "reason": reason},
                    confirm_label="Name ändern",
                    cancel_url=str(request.app.url_path_for("admin_entity_detail", entity_id=entity_id)),
                )
            return redirect(str(request.app.url_path_for("admin_entity_detail", entity_id=entity_id)), f"Name geändert: {new_name}")
        except Exception as exc:
            return error_page(request, exc)

    @router.get("/entity/{entity_id}/merge", response_class=HTMLResponse, name="admin_entity_merge_search", dependencies=auth)
    async def admin_entity_merge_search(request: Request, entity_id: str, q: str = ""):
        try:
            with GraphCurator.from_config(cfg) as curator:
                current = curator.get_entity(entity_id)["entity"]
                candidates = curator.find_entities(q, limit=50) if q.strip() else []
            candidates = [row for row in candidates if row.get("entity_id") != entity_id]
            return render(request, "merge_search.html", current=current, q=q, candidates=candidates)
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/merge", name="admin_merge", dependencies=auth)
    async def admin_merge(request: Request):
        data = await form_data(request)
        keep_id = data.get("keep_id", "").strip()
        merge_id = data.get("merge_id", "").strip()
        alias_policy = data.get("alias_policy", "contextual")
        confirm = data.get("confirm", "") == "yes"
        cancel_url = data.get("cancel_url", "/rag-admin/candidates") or "/rag-admin/candidates"
        try:
            if alias_policy not in POLICIES:
                raise ValueError(f"Ungültige Alias-Policy: {alias_policy}")
            with GraphCurator.from_config(cfg) as curator:
                result = curator.merge(keep_id, merge_id, alias_policy=alias_policy, apply=confirm)
            if not confirm:
                return preview_response(
                    request,
                    title="Entities zusammenführen",
                    preview=result,
                    action_url=str(request.app.url_path_for("admin_merge")),
                    fields={"keep_id": keep_id, "merge_id": merge_id, "alias_policy": alias_policy, "cancel_url": cancel_url},
                    danger=True,
                    confirm_label="Merge bestätigen",
                    cancel_url=cancel_url,
                )
            return redirect(str(request.app.url_path_for("admin_entity_detail", entity_id=keep_id)), "Entities zusammengeführt")
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/entity/{entity_id}/delete", name="admin_entity_delete", dependencies=auth)
    async def admin_entity_delete(request: Request, entity_id: str):
        data = await form_data(request)
        reason = data.get("reason", "manual_not_an_entity").strip() or "manual_not_an_entity"
        confirm = data.get("confirm", "") == "yes"
        try:
            with GraphCurator.from_config(cfg) as curator:
                result = curator.delete_entity(entity_id, reason=reason, apply=confirm)
            if not confirm:
                return preview_response(
                    request,
                    title="Entity als Non-Entity entfernen",
                    preview=result,
                    action_url=str(request.app.url_path_for("admin_entity_delete", entity_id=entity_id)),
                    fields={"reason": reason},
                    danger=True,
                    confirm_label="Entity entfernen",
                    cancel_url=str(request.app.url_path_for("admin_entity_detail", entity_id=entity_id)),
                )
            return redirect(str(request.app.url_path_for("admin_entities")), "Entity entfernt; Observations bleiben als Curator-Evidenz erhalten")
        except Exception as exc:
            return error_page(request, exc)

    @router.get("/candidates", response_class=HTMLResponse, name="admin_candidates", dependencies=auth)
    async def admin_candidates(request: Request):
        try:
            with GraphCurator.from_config(cfg) as curator:
                rows = curator.list_candidates()
            return render(request, "candidates.html", candidates=rows)
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/candidate/reject", name="admin_candidate_reject", dependencies=auth)
    async def admin_candidate_reject(request: Request):
        data = await form_data(request)
        left_id = data.get("left_id", "").strip()
        right_id = data.get("right_id", "").strip()
        reason = data.get("reason", "manual_rejection").strip() or "manual_rejection"
        confirm = data.get("confirm", "") == "yes"
        try:
            with GraphCurator.from_config(cfg) as curator:
                result = curator.reject_merge(left_id, right_id, reason=reason, apply=confirm)
            if not confirm:
                return preview_response(
                    request,
                    title="Als verschiedene Entities markieren",
                    preview=result,
                    action_url=str(request.app.url_path_for("admin_candidate_reject")),
                    fields={"left_id": left_id, "right_id": right_id, "reason": reason},
                    confirm_label="NOT_SAME_AS speichern",
                    cancel_url=str(request.app.url_path_for("admin_candidates")),
                )
            return redirect(str(request.app.url_path_for("admin_candidates")), "NOT_SAME_AS gespeichert")
        except Exception as exc:
            return error_page(request, exc)

    @router.get("/observations", response_class=HTMLResponse, name="admin_observations", dependencies=auth)
    async def admin_observations(request: Request, q: str = "", status: str = "", limit: int = 200):
        try:
            with GraphCurator.from_config(cfg) as curator:
                rows = curator.search_observations(query=q, status=status, limit=max(1, min(limit, 1000)))
            rows = add_doc_links(rows)
            return render(request, "observations.html", observations=rows, q=q, status=status)
        except Exception as exc:
            return error_page(request, exc)

    @router.get("/observation/{observation_id}", response_class=HTMLResponse, name="admin_observation_detail", dependencies=auth)
    async def admin_observation_detail(request: Request, observation_id: str, q: str = ""):
        try:
            with GraphCurator.from_config(cfg) as curator:
                obs = curator.get_observation(observation_id)
                if obs is None:
                    raise ValueError(f"Observation nicht gefunden: {observation_id}")
                search_q = q.strip() or str(obs.get("canonical_name") or obs.get("observed_text") or "").strip()
                candidates = curator.find_entities(search_q, limit=30) if search_q else []
            obs = add_doc_links([obs])[0]
            return render(request, "observation.html", observation=obs, q=search_q, candidates=candidates)
        except ValueError as exc:
            return error_page(request, exc, status_code=404)
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/observation/{observation_id}/correct", name="admin_observation_correct", dependencies=auth)
    async def admin_observation_correct(request: Request, observation_id: str):
        data = await form_data(request)
        target_id = data.get("target_id", "").strip()
        reason = data.get("reason", "ocr").strip() or "ocr"
        confirm = data.get("confirm", "") == "yes"
        try:
            with GraphCurator.from_config(cfg) as curator:
                result = curator.correct_observation(observation_id, target_id, reason=reason, apply=confirm)
            if not confirm:
                return preview_response(
                    request,
                    title="Observation neu zuordnen",
                    preview=result,
                    action_url=str(request.app.url_path_for("admin_observation_correct", observation_id=observation_id)),
                    fields={"target_id": target_id, "reason": reason},
                    confirm_label="Zuordnung ändern",
                    cancel_url=str(request.app.url_path_for("admin_observation_detail", observation_id=observation_id)),
                )
            return redirect(str(request.app.url_path_for("admin_observation_detail", observation_id=observation_id)), "Observation neu zugeordnet")
        except Exception as exc:
            return error_page(request, exc)

    @router.get("/contacts", response_class=HTMLResponse, name="admin_contacts", dependencies=auth)
    async def admin_contacts(
        request: Request,
        cloud_id: str = "",
        source_user_id: str = "",
        addressbook: str = "",
        import_run_id: str = "",
    ):
        try:
            with GraphCurator.from_config(cfg) as curator:
                sources = curator.list_contact_sources()
                runs = curator.list_contact_import_runs(limit=50)
                records: list[dict[str, Any]] = []
                if any((cloud_id, source_user_id, addressbook, import_run_id)):
                    records = curator.list_contacts(
                        cloud_id=cloud_id,
                        source_user_id=source_user_id,
                        addressbook=addressbook,
                        import_run_id=import_run_id,
                        limit=1000,
                    )
            for row in sources:
                total = int(row.get("contact_records") or 0)
                overlap = int(row.get("overlap_contact_records") or 0)
                row["overlap_percent"] = round((100.0 * overlap / total), 1) if total else 0.0
            return render(
                request,
                "contacts.html",
                sources=sources,
                runs=runs,
                records=records,
                filters={
                    "cloud_id": cloud_id,
                    "source_user_id": source_user_id,
                    "addressbook": addressbook,
                    "import_run_id": import_run_id,
                },
            )
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/contacts/rollback", name="admin_contacts_rollback", dependencies=auth)
    async def admin_contacts_rollback(request: Request):
        data = await form_data(request)
        scope = {
            "cloud_id": data.get("cloud_id", "").strip(),
            "source_user_id": data.get("source_user_id", "").strip(),
            "addressbook": data.get("addressbook", "").strip(),
            "import_run_id": data.get("import_run_id", "").strip(),
        }
        confirm = data.get("confirm", "") == "yes"
        try:
            with GraphCurator.from_config(cfg) as curator:
                result = curator.rollback_contacts(**scope, apply=confirm)
            if not confirm:
                return preview_response(
                    request,
                    title="Kontaktquelle zurückrollen",
                    preview=result,
                    action_url=str(request.app.url_path_for("admin_contacts_rollback")),
                    fields=scope,
                    danger=True,
                    confirm_label="Kontaktquelle entfernen",
                    cancel_url=str(request.app.url_path_for("admin_contacts")),
                )
            relink = _queue_contact_relink(
                graph_queue,
                list(result.get("relink_document_ids") or []),
                reason="contact_rollback_relink",
                priority="high",
            )
            return redirect(
                str(request.app.url_path_for("admin_contacts")),
                f"Kontaktquelle zurückgerollt; {relink.get('document_count', 0)} Dokumente zum Relink eingereiht",
            )
        except Exception as exc:
            return error_page(request, exc)

    @router.get("/contact/{contact_id}", response_class=HTMLResponse, name="admin_contact_detail", dependencies=auth)
    async def admin_contact_detail(request: Request, contact_id: str, q: str = ""):
        try:
            with GraphCurator.from_config(cfg) as curator:
                contact = curator.get_contact(contact_id)
                if contact is None:
                    raise ValueError(f"ContactRecord nicht gefunden: {contact_id}")
                candidates = curator.find_entities(q, limit=30) if q.strip() else []
            return render(request, "contact.html", contact=contact, q=q, candidates=candidates)
        except ValueError as exc:
            return error_page(request, exc, status_code=404)
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/contact/{contact_id}/reassign", name="admin_contact_reassign", dependencies=auth)
    async def admin_contact_reassign(request: Request, contact_id: str):
        data = await form_data(request)
        target_id = data.get("target_id", "").strip()
        confirm = data.get("confirm", "") == "yes"
        try:
            with GraphCurator.from_config(cfg) as curator:
                result = curator.reassign_contact(contact_id, target_id, apply=confirm)
            if not confirm:
                return preview_response(
                    request,
                    title="ContactRecord neu zuordnen",
                    preview=result,
                    action_url=str(request.app.url_path_for("admin_contact_reassign", contact_id=contact_id)),
                    fields={"target_id": target_id},
                    confirm_label="Kontakt neu zuordnen",
                    cancel_url=str(request.app.url_path_for("admin_contact_detail", contact_id=contact_id)),
                )
            relink = _queue_contact_relink(
                graph_queue,
                list(result.get("relink_document_ids") or []),
                reason="contact_reassignment_relink",
                priority="high",
            )
            return redirect(
                str(request.app.url_path_for("admin_contact_detail", contact_id=contact_id)),
                f"ContactRecord neu zugeordnet; {relink.get('document_count', 0)} Dokumente zum Relink eingereiht",
            )
        except Exception as exc:
            return error_page(request, exc)

    @router.get("/queue", response_class=HTMLResponse, name="admin_queue", dependencies=auth)
    async def admin_queue(request: Request):
        try:
            stats = graph_queue.stats()
            jobs = graph_queue.recent_jobs(50)
            return render(request, "queue.html", queue=stats, jobs=jobs)
        except Exception as exc:
            return error_page(request, exc)

    @router.post("/queue/path", name="admin_queue_path", dependencies=auth)
    async def admin_queue_path(request: Request):
        data = await form_data(request)
        include_text = data.get("include_paths", "")
        exclude_text = data.get("exclude_paths", "")
        include_paths = _split_lines(include_text)
        exclude_paths = _split_lines(exclude_text)
        priority = data.get("priority", "normal")
        limit = int(data.get("limit", "0") or 0)
        confirm = data.get("confirm", "") == "yes"
        try:
            if priority not in PRIORITIES:
                raise ValueError(f"Ungültige Priorität: {priority}")
            if not confirm:
                preview = graph_queue.preview_path(
                    include_paths, exclude_paths, priority=priority, limit=max(0, limit)
                )
                preview.pop("_documents", None)
                return preview_response(
                    request,
                    title="Pfad in Graph-Queue einreihen",
                    preview=preview,
                    action_url=str(request.app.url_path_for("admin_queue_path")),
                    fields={
                        "include_paths": include_text,
                        "exclude_paths": exclude_text,
                        "priority": priority,
                        "limit": limit,
                    },
                    confirm_label="Dokumente einreihen",
                    cancel_url=str(request.app.url_path_for("admin_queue")),
                )
            result = graph_queue.enqueue_path(
                include_paths, exclude_paths, priority=priority, limit=max(0, limit)
            )
            return redirect(
                str(request.app.url_path_for("admin_queue")),
                f"{result.get('documents_found', 0)} Dokumente geprüft/eingereiht; queued={result.get('queued', 0)}, coalesced={result.get('coalesced', 0)}",
            )
        except Exception as exc:
            return error_page(request, exc)

    return router
