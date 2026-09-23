"""Self-service Research Finding curation authenticated by Nextcloud Login Flow.

This surface intentionally does not reuse the persistent provider credential.
Each curation login receives a short-lived Nextcloud app password, stored only
in the encrypted curation_sessions table. The absolute session expiry is
checked on every request.
"""
from __future__ import annotations

import base64
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.templating import Jinja2Templates

from rag.acl import NextcloudLiveAcl
from rag.credential_store import CredentialStore, CurationSession, normalize_nextcloud_server
from rag.curator import GraphCurator
from rag.graph import cfg_get
from rag.research_findings import evidence_frame_view
from rag.version import VERSION


log = logging.getLogger("rag.curation")
HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "templates" / "curation"
CSS_FILE = HERE / "static" / "admin" / "admin.css"
COOKIE_NAME = "aki_curation"


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _store(cfg: dict[str, Any]) -> CredentialStore:
    path = str(
        cfg_get(cfg, "auth.credential_store", default=cfg_get(cfg, "acl.credential_store", default="runtime/users.sqlite"))
        or "runtime/users.sqlite"
    )
    return CredentialStore(path)


def _verify_tls(cfg: dict[str, Any]) -> bool | str:
    ca_file = str(cfg_get(cfg, "acl.ca_file", default="") or "").strip()
    if ca_file:
        return ca_file
    return _truthy(
        cfg_get(cfg, "auth.verify_tls", default=cfg_get(cfg, "acl.verify_tls", default=True)),
        True,
    )


def _filter_findings_with_acl(
    acl: NextcloudLiveAcl,
    session: CurationSession,
    findings: list[dict[str, Any]],
    purge_denied: Any | None = None,
) -> list[dict[str, Any]]:
    """Filter self-service Findings through the current Nextcloud ACL, fail closed."""
    if not acl.enabled:
        raise HTTPException(
            status_code=503,
            detail="Live ACL is disabled; self-service Finding curation is unavailable",
        )
    candidates = [
        {
            "document_id": str(item.get("document_id") or ""),
            "_finding_id": str(item.get("finding_id") or ""),
        }
        for item in findings
        if str(item.get("document_id") or "").strip()
    ]
    if not candidates:
        return []
    decision = acl.authorize_with_credential(
        candidates,
        username=session.nextcloud_login,
        password=session.app_password,
    )
    if not decision.enabled:
        raise HTTPException(
            status_code=503,
            detail="Live ACL is disabled; self-service Finding curation is unavailable",
        )
    allowed = {str(item.get("_finding_id") or "") for item in decision.results}
    denied_purgeable = list(dict.fromkeys(
        str(item.get("_finding_id") or "")
        for item in candidates
        if str(item.get("_finding_id") or "")
        and str(item.get("_finding_id") or "") not in allowed
        and str(item.get("document_id") or "").startswith("files:")
        and str(item.get("document_id") or "")[6:].isdigit()
    ))
    if denied_purgeable and purge_denied is not None:
        try:
            purge_denied(session.canonical_user_id, denied_purgeable)
        except Exception as exc:
            log.warning(
                "ACL self-cleanup failed for user=%s findings=%s: %s: %s",
                session.canonical_user_id,
                len(denied_purgeable),
                type(exc).__name__,
                exc,
            )
    return [
        item
        for item in findings
        if str(item.get("finding_id") or "") in allowed
    ]


def _revoke_app_password(session: CurationSession, cfg: dict[str, Any]) -> bool:
    """Best-effort revocation of the app password represented by *session*."""
    url = session.nextcloud_server.rstrip("/") + "/ocs/v2.php/core/apppassword"
    try:
        response = httpx.request(
            "DELETE",
            url,
            auth=(session.nextcloud_login, session.app_password),
            headers={"OCS-APIREQUEST": "true", "Accept": "application/json"},
            timeout=15.0,
            verify=_verify_tls(cfg),
        )
        if 200 <= response.status_code < 300:
            return True
        log.warning(
            "Curation app-password revocation failed for %s@%s: HTTP %s",
            session.nextcloud_login, session.nextcloud_server, response.status_code,
        )
    except Exception as exc:
        log.warning(
            "Curation app-password revocation failed for %s@%s: %s: %s",
            session.nextcloud_login, session.nextcloud_server, type(exc).__name__, exc,
        )
    return False


def invalidate_curation_session(
    store: CredentialStore,
    session: CurationSession,
    cfg: dict[str, Any],
) -> bool:
    """Invalidate locally first, then revoke at Nextcloud.

    Failed revocation remains as revocation_pending so a later API start retries
    it. A pending session is never accepted for curation requests.
    """
    store.mark_curation_session_revocation_pending(session.session_id_hash)
    if _revoke_app_password(session, cfg):
        store.delete_curation_session_by_hash(session.session_id_hash)
        return True
    return False


def cleanup_stale_curation_sessions(cfg: dict[str, Any]) -> dict[str, int]:
    """Invalidate and revoke every curation token left by an earlier API process."""
    store = _store(cfg)
    sessions, undecryptable = store.list_curation_sessions_for_cleanup()
    # A decryption failure can mean either damaged ciphertext or, importantly,
    # a temporarily wrong/restored master key. Keep the row locally unusable so
    # a later startup with the correct key can still revoke its Nextcloud app
    # password. Deleting it here would destroy the only automatic revocation path.
    for session_id_hash in undecryptable:
        store.mark_curation_session_revocation_pending(session_id_hash)
    if undecryptable:
        log.warning(
            "Retained %d undecryptable curation session(s) as revocation_pending; "
            "their Nextcloud app passwords could not be revoked automatically.",
            len(undecryptable),
        )

    revoked = 0
    pending = len(undecryptable)
    for session in sessions:
        store.mark_curation_session_revocation_pending(session.session_id_hash)
        if _revoke_app_password(session, cfg):
            store.delete_curation_session_by_hash(session.session_id_hash)
            revoked += 1
        else:
            pending += 1
    found = len(sessions) + len(undecryptable)
    if found:
        log.info(
            "Startup curation-session cleanup: found=%d revoked=%d pending=%d",
            found, revoked, pending,
        )
    return {"found": found, "revoked": revoked, "pending": pending}


def create_curation_router(cfg: dict[str, Any]) -> APIRouter:
    router = APIRouter(prefix="/curation", tags=["curation"], include_in_schema=False)
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    store = _store(cfg)
    acl = NextcloudLiveAcl(cfg)

    globally_enabled = lambda: _truthy(
        cfg_get(cfg, "research_findings.curation.user_self_service", default=False)
    )
    session_max_seconds = max(
        300,
        int(cfg_get(cfg, "research_findings.curation.session_max_seconds", default=7200) or 7200),
    )
    flow_ttl = max(
        60,
        int(cfg_get(cfg, "auth.login_flow_ttl_seconds", default=1200) or 1200),
    )
    nextcloud_base = str(cfg_get(cfg, "nextcloud.base_url", default="") or "").strip().rstrip("/")

    def secure(response: Any) -> Any:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'none'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        )
        return response

    def render(request: Request, name: str, **context: Any) -> HTMLResponse:
        return secure(
            templates.TemplateResponse(
                request=request,
                name=name,
                context={"request": request, "version": VERSION, **context},
            )
        )

    def redirect(url: str, message: str = "") -> RedirectResponse:
        if message:
            url += ("&" if "?" in url else "?") + urlencode({"msg": message})
        return secure(RedirectResponse(url=url, status_code=303))

    def host_candidates(request: Request) -> set[str]:
        hosts: set[str] = set()
        for header in ("host", "x-forwarded-host"):
            for value in str(request.headers.get(header) or "").split(","):
                value = value.strip().casefold()
                if value:
                    hosts.add(value)
        return hosts

    async def form_values(request: Request) -> dict[str, list[str]]:
        origin = str(request.headers.get("origin") or "").strip()
        if origin:
            parsed = urlparse(origin)
            if parsed.netloc and parsed.netloc.casefold() not in host_candidates(request):
                raise HTTPException(status_code=403, detail="Cross-origin curation POST denied")
        raw = (await request.body()).decode("utf-8", errors="replace")
        return parse_qs(raw, keep_blank_values=True)

    async def form_data(request: Request) -> dict[str, str]:
        values = await form_values(request)
        return {key: (vals[-1] if vals else "") for key, vals in values.items()}

    async def session_from_request(request: Request) -> tuple[str, CurationSession]:
        if not globally_enabled():
            raise HTTPException(status_code=404, detail="Self-service Finding curation is disabled")
        token = str(request.cookies.get(COOKIE_NAME) or "").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Curation session required")
        session = store.get_curation_session(token)
        if session is None:
            stale = store.get_curation_session_any(token)
            if stale is not None:
                await run_in_threadpool(invalidate_curation_session, store, stale, cfg)
            raise HTTPException(status_code=401, detail="Curation session expired")
        user = store.get_canonical_user(session.canonical_user_id)
        if user is None or not user.enabled or not user.findings_curation_enabled:
            await run_in_threadpool(invalidate_curation_session, store, session, cfg)
            raise HTTPException(status_code=403, detail="Finding curation is not enabled for this user")
        return token, session

    def csrf(session: CurationSession, supplied: str) -> None:
        if not supplied or not secrets.compare_digest(session.csrf_token, str(supplied)):
            raise HTTPException(status_code=403, detail="Invalid curation CSRF token")

    def purge_denied_uncurated_findings(
        canonical_user_id: str,
        finding_ids: list[str],
    ) -> dict[str, int]:
        with GraphCurator.from_config(cfg) as curator:
            return curator.purge_denied_uncurated_research_findings_for_user(
                canonical_user_id, finding_ids
            )

    async def filter_findings(
        session: CurationSession,
        findings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return await run_in_threadpool(
            _filter_findings_with_acl,
            acl,
            session,
            findings,
            purge_denied_uncurated_findings,
        )

    async def require_finding(session: CurationSession, finding_id: str) -> dict[str, Any]:
        with GraphCurator.from_config(cfg) as curator:
            if not curator.research_finding_observed_by_user(session.canonical_user_id, finding_id):
                raise HTTPException(status_code=404, detail="Finding not observed by current user")
            detail = curator.get_research_finding(finding_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Finding not found")
        finding = dict(detail.get("finding") or {})
        document = dict(detail.get("document") or {})
        row = {
            "finding_id": str(finding.get("finding_id") or finding_id),
            "document_id": str(document.get("document_id") or ""),
        }
        visible = await filter_findings(session, [row])
        if not visible:
            raise HTTPException(status_code=404, detail="Finding is not visible under current Nextcloud ACL")
        return visible[0]

    @router.get("/assets/admin.css", include_in_schema=False)
    async def css() -> FileResponse:
        response = FileResponse(CSS_FILE, media_type="text/css")
        response.headers["Cache-Control"] = "private, max-age=300"
        return response

    @router.get("/", response_class=HTMLResponse, name="curation_home")
    async def home(request: Request, state: str = "open", q: str = ""):
        message = request.query_params.get("msg", "")
        try:
            _token, session = await session_from_request(request)
        except HTTPException:
            return render(
                request,
                "login.html",
                enabled=globally_enabled(),
                flow=None,
                message=message,
                session_hours=round(session_max_seconds / 3600, 2),
            )

        with GraphCurator.from_config(cfg) as curator:
            runs = curator.list_research_runs(
                canonical_user_id=session.canonical_user_id,
                query=q,
                state="all",
                limit=1000,
            )

        all_findings: list[dict[str, Any]] = []
        for run in runs:
            all_findings.extend(list(run.get("findings") or []))
        visible = await filter_findings(session, all_findings)
        allowed_ids = {str(x.get("finding_id") or "") for x in visible}

        shown: list[dict[str, Any]] = []
        for run in runs:
            run = dict(run)
            items = [
                dict(item) for item in (run.get("findings") or [])
                if str(item.get("finding_id") or "") in allowed_ids
            ]
            if not items:
                continue
            pending = [
                item for item in items
                if str(item.get("run_disposition") or "pending") != "dismissed"
                and str(item.get("graph_state") or "open") in {"open", "no_entity", "review_required"}
            ]
            run["findings"] = items
            run["visible_finding_count"] = len(items)
            run["visible_open_count"] = len(pending)
            run["effective_status"] = (
                "dismissed" if str(run.get("curation_status") or "") == "dismissed"
                else ("open" if pending else "completed")
            )
            if state not in {"open", "completed", "dismissed", "all"}:
                state = "open"
            if state == "all" or run["effective_status"] == state:
                shown.append(run)

        return render(
            request,
            "runs.html",
            session=session,
            runs=shown,
            state=state,
            q=q,
            message=message,
            csrf_token=session.csrf_token,
        )

    @router.post("/login", name="curation_login")
    async def login(request: Request):
        await form_data(request)  # origin guard
        if not globally_enabled():
            raise HTTPException(status_code=404, detail="Self-service Finding curation is disabled")
        if not nextcloud_base:
            raise HTTPException(status_code=503, detail="nextcloud.base_url is not configured")
        async with httpx.AsyncClient(
            timeout=15.0,
            verify=_verify_tls(cfg),
            headers={"User-Agent": "SunaQ", "Accept": "application/json"},
        ) as client:
            response = await client.post(nextcloud_base + "/index.php/login/v2")
        response.raise_for_status()
        payload = response.json()
        poll = payload.get("poll") or {}
        login_url = str(payload.get("login") or "").strip()
        endpoint = str(poll.get("endpoint") or "").strip()
        poll_token = str(poll.get("token") or "").strip()
        if not login_url or not endpoint or not poll_token:
            raise HTTPException(status_code=502, detail="Incomplete Nextcloud Login Flow response")
        identity = "curation-flow:" + secrets.token_urlsafe(18)
        flow_id = store.create_nextcloud_flow(identity, endpoint, poll_token, login_url)
        return render(
            request,
            "login.html",
            enabled=True,
            flow={"flow_id": flow_id, "login_url": login_url},
            message="Nextcloud-Anmeldung starten und danach hier bestätigen.",
            session_hours=round(session_max_seconds / 3600, 2),
        )

    @router.post("/login/{flow_id}", name="curation_login_poll")
    async def login_poll(request: Request, flow_id: str):
        await form_data(request)  # origin guard
        if not globally_enabled():
            raise HTTPException(status_code=404, detail="Self-service Finding curation is disabled")
        flow = store.get_nextcloud_flow(flow_id)
        if flow is None or not str(flow.get("rag_user_id") or "").startswith("curation-flow:"):
            raise HTTPException(status_code=404, detail="Unknown curation login flow")
        if float(flow.get("created_at") or 0) + flow_ttl <= time.time():
            store.delete_nextcloud_flow(flow_id)
            raise HTTPException(status_code=410, detail="Curation login flow expired")

        async with httpx.AsyncClient(
            timeout=15.0,
            verify=_verify_tls(cfg),
            headers={"User-Agent": "SunaQ", "Accept": "application/json"},
        ) as client:
            response = await client.post(
                str(flow["poll_endpoint"]),
                data={"token": str(flow["poll_token"])},
            )
        if response.status_code in {404, 425}:
            return render(
                request,
                "login.html",
                enabled=True,
                flow={"flow_id": flow_id, "login_url": str(flow["login_url"])},
                message="Nextcloud-Anmeldung noch nicht abgeschlossen.",
                session_hours=round(session_max_seconds / 3600, 2),
            )
        response.raise_for_status()
        payload = response.json()
        login_name = str(payload.get("loginName") or "").strip()
        app_password = str(payload.get("appPassword") or "")
        server = normalize_nextcloud_server(str(payload.get("server") or nextcloud_base))
        if not login_name or not app_password or not server:
            raise HTTPException(status_code=502, detail="Incomplete Nextcloud Login Flow completion")

        users = store.find_canonical_users(login_name, server=server)
        user = users[0] if len(users) == 1 else None
        if user is None or not user.enabled or not user.findings_curation_enabled:
            # Revoke the newly issued credential immediately; it must never
            # become a normal provider credential or create a new identity.
            temporary = CurationSession(
                session_id_hash="not-stored",
                canonical_user_id=(user.canonical_user_id if user else ""),
                nextcloud_server=server,
                nextcloud_login=login_name,
                app_password=app_password,
                csrf_token="",
                state="revocation_pending",
                created_at=time.time(),
                expires_at=time.time(),
                last_seen_at=time.time(),
            )
            await run_in_threadpool(_revoke_app_password, temporary, cfg)
            store.delete_nextcloud_flow(flow_id)
            raise HTTPException(status_code=403, detail="Finding curation is not enabled for this Nextcloud user")

        token, session = store.create_curation_session(
            canonical_user_id=user.canonical_user_id,
            nextcloud_server=server,
            nextcloud_login=login_name,
            app_password=app_password,
            lifetime_seconds=session_max_seconds,
        )
        store.delete_nextcloud_flow(flow_id)
        response_out = redirect(str(request.app.url_path_for("curation_home")), "Nextcloud-Identität bestätigt.")
        response_out.set_cookie(
            COOKIE_NAME,
            token,
            max_age=session_max_seconds,
            httponly=True,
            secure=True,
            samesite="strict",
            path="/curation/",
        )
        return response_out

    @router.post("/logout", name="curation_logout")
    async def logout(request: Request):
        token, session = await session_from_request(request)
        data = await form_data(request)
        csrf(session, data.get("csrf_token", ""))
        await run_in_threadpool(invalidate_curation_session, store, session, cfg)
        response = redirect(str(request.app.url_path_for("curation_home")), "Kurationssitzung beendet.")
        response.delete_cookie(COOKIE_NAME, path="/curation/")
        return response

    @router.get("/run/{run_id}", response_class=HTMLResponse, name="curation_run")
    async def run_detail(request: Request, run_id: str):
        _token, session = await session_from_request(request)
        with GraphCurator.from_config(cfg) as curator:
            run = curator.get_research_run(run_id)
        if run is None or str(run.get("canonical_user_id") or "") != session.canonical_user_id:
            raise HTTPException(status_code=404, detail="Research run not found")
        run["findings"] = await filter_findings(session, list(run.get("findings") or []))
        return render(request, "run.html", session=session, run=run, csrf_token=session.csrf_token)

    @router.post("/run/{run_id}/dismiss", name="curation_run_dismiss")
    async def run_dismiss(request: Request, run_id: str):
        _token, session = await session_from_request(request)
        data = await form_data(request)
        csrf(session, data.get("csrf_token", ""))
        with GraphCurator.from_config(cfg) as curator:
            run = curator.get_research_run(run_id)
            if run is None or str(run.get("canonical_user_id") or "") != session.canonical_user_id:
                raise HTTPException(status_code=404, detail="Research run not found")
            curator.dismiss_research_run(
                run_id,
                actor=f"nextcloud-user:{session.nextcloud_login}",
                reason=data.get("reason", ""),
            )
        return redirect(str(request.app.url_path_for("curation_home")), "Recherche ausgeblendet.")

    @router.post("/run/{run_id}/dismiss-findings", name="curation_run_dismiss_findings")
    async def run_dismiss_findings(request: Request, run_id: str):
        _token, session = await session_from_request(request)
        values = await form_values(request)
        csrf(session, (values.get("csrf_token", [""])[-1] or ""))
        finding_ids = [x.strip() for x in values.get("finding_id", []) if x.strip()]
        with GraphCurator.from_config(cfg) as curator:
            run = curator.get_research_run(run_id)
            if run is None or str(run.get("canonical_user_id") or "") != session.canonical_user_id:
                raise HTTPException(status_code=404, detail="Research run not found")
            produced = {str(x.get("finding_id") or "") for x in (run.get("findings") or [])}
            if any(fid not in produced for fid in finding_ids):
                raise HTTPException(status_code=404, detail="Finding is not part of this research run")
            selected = [
                dict(item)
                for item in (run.get("findings") or [])
                if str(item.get("finding_id") or "") in set(finding_ids)
            ]
            visible = await filter_findings(session, selected)
            visible_ids = {str(item.get("finding_id") or "") for item in visible}
            if any(fid not in visible_ids for fid in finding_ids):
                raise HTTPException(status_code=404, detail="Finding is not visible under current Nextcloud ACL")
            curator.set_research_run_finding_disposition(
                run_id,
                finding_ids,
                disposition="dismissed",
                actor=f"nextcloud-user:{session.nextcloud_login}",
            )
        return redirect(str(request.app.url_path_for("curation_run", run_id=run_id)), "Auswahl für diese Recherche ausgeblendet.")

    @router.get("/finding/{finding_id}", response_class=HTMLResponse, name="curation_finding")
    async def finding_detail(request: Request, finding_id: str):
        _token, session = await session_from_request(request)
        await require_finding(session, finding_id)
        with GraphCurator.from_config(cfg) as curator:
            detail = curator.get_research_finding(finding_id)
            entity_options = curator.research_finding_entity_options(finding_id) if detail else []
            claim_options = curator.research_finding_claim_options(finding_id) if detail else []
        if detail is None:
            raise HTTPException(status_code=404, detail="Finding not found")
        detail["entity_options"] = entity_options
        detail["claim_options"] = claim_options
        detail["all_entities_decided"] = bool(entity_options) and all(
            bool(item.get("curated")) or bool(item.get("suppressed")) for item in entity_options
        )
        detail["has_active_claims"] = any(
            str((item or {}).get("curator_status") or "") in {"manual_claim", "review_required"}
            for item in (detail.get("claims") or [])
        )
        raw = str((detail.get("finding") or {}).get("evidence_frame_json") or "").strip()
        detail["evidence_view"] = evidence_frame_view(raw)
        try:
            detail["evidence_pretty"] = json.dumps(json.loads(raw), ensure_ascii=False, indent=2) if raw else "—"
        except Exception:
            detail["evidence_pretty"] = raw
        return render(
            request,
            "finding.html",
            session=session,
            detail=detail,
            csrf_token=session.csrf_token,
        )

    @router.post("/finding/{finding_id}/entity", name="curation_finding_entity")
    async def finding_entity(request: Request, finding_id: str):
        _token, session = await session_from_request(request)
        data = await form_data(request)
        csrf(session, data.get("csrf_token", ""))
        await require_finding(session, finding_id)
        with GraphCurator.from_config(cfg) as curator:
            curator.curate_research_finding_entity(
                finding_id,
                entity_text=data.get("entity_text", ""),
                action=data.get("action", ""),
                target_entity_id=data.get("target_entity_id", ""),
                new_name=data.get("new_name", ""),
                entity_type=data.get("entity_type", ""),
                reason=data.get("reason", ""),
                apply=True,
                curator_actor=f"nextcloud-user:{session.canonical_user_id}",
            )
        return redirect(str(request.app.url_path_for("curation_finding", finding_id=finding_id)), "Entity-Entscheidung gespeichert.")

    @router.post("/finding/{finding_id}/claim", name="curation_finding_claim")
    async def finding_claim(request: Request, finding_id: str):
        _token, session = await session_from_request(request)
        data = await form_data(request)
        csrf(session, data.get("csrf_token", ""))
        await require_finding(session, finding_id)
        with GraphCurator.from_config(cfg) as curator:
            curator.curate_research_finding_claim(
                finding_id,
                subject_entity_id=data.get("subject_entity_id", ""),
                predicate_id=data.get("predicate_id", ""),
                object_entity_id=data.get("object_entity_id", ""),
                claim_text=data.get("claim_text", ""),
                apply=True,
                curator_actor=f"nextcloud-user:{session.canonical_user_id}",
            )
        return redirect(str(request.app.url_path_for("curation_finding", finding_id=finding_id)), "Dokumentgebundener Claim gespeichert.")

    @router.post(
        "/finding/{finding_id}/claim/{relation_id}/review",
        name="curation_finding_claim_review",
    )
    async def finding_claim_review(request: Request, finding_id: str, relation_id: str):
        _token, session = await session_from_request(request)
        data = await form_data(request)
        csrf(session, data.get("csrf_token", ""))
        await require_finding(session, finding_id)
        action = data.get("action", "").strip().casefold()
        if action not in {"confirm", "dismiss"}:
            raise HTTPException(status_code=400, detail="Invalid claim review action")
        with GraphCurator.from_config(cfg) as curator:
            curator.review_research_finding_claim(
                finding_id,
                relation_id=relation_id,
                action=action,
                reason=data.get("reason", ""),
                curator_actor=f"nextcloud-user:{session.canonical_user_id}",
            )
        return redirect(
            str(request.app.url_path_for("curation_finding", finding_id=finding_id)),
            "Claim-Review gespeichert.",
        )

    @router.post("/finding/{finding_id}/status", name="curation_finding_status")
    async def finding_status(request: Request, finding_id: str):
        _token, session = await session_from_request(request)
        data = await form_data(request)
        csrf(session, data.get("csrf_token", ""))
        await require_finding(session, finding_id)
        status = data.get("status", "")
        if status not in {"", "mentions_only"}:
            raise HTTPException(status_code=400, detail="Self-service may only complete/reopen a Finding; use run dismissal to hide it.")
        with GraphCurator.from_config(cfg) as curator:
            curator.curate_research_finding(
                finding_id,
                status=status,
                reason=data.get("reason", ""),
                apply=True,
                curator_actor=f"nextcloud-user:{session.canonical_user_id}",
            )
        return redirect(str(request.app.url_path_for("curation_finding", finding_id=finding_id)), "Finding-Status gespeichert.")

    return router
