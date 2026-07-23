"""FastAPI application for the admin console."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any
from urllib.parse import quote

from company_brain.admin_console import audit, auth
from company_brain.admin_console.config import dispatch_jobs, stale_minutes
from company_brain.admin_console.costs import costs_snapshot
from company_brain.admin_console.dispatch import DispatchError, run_dispatch
from company_brain.admin_console.heartbeats import status_rows
from company_brain.admin_console.review import review_snapshot
from company_brain.admin_console.wiki_ops import get_page, save_page, search_wiki

_OAUTH_STATE_COOKIE = "cb_admin_oauth_state"

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

try:
    from fastapi import FastAPI, Form, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore[misc, assignment]


def create_app():
    if FastAPI is None:  # pragma: no cover
        raise RuntimeError(
            "admin-console extra required: pip install 'company-brain[admin-console]'"
        )

    app = FastAPI(title="company-brain admin console", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def _authed(request: Request) -> bool:
        return auth.verify_session(request.cookies.get(auth.COOKIE_NAME))

    def _require(request: Request):
        if not _authed(request):
            return RedirectResponse("/login", status_code=303)
        return None

    def _flash(request: Request) -> dict[str, str] | None:
        kind = request.query_params.get("flash")
        text = request.query_params.get("msg")
        if kind and text:
            return {"kind": kind, "text": text}
        return None

    def _ctx(request: Request, nav: str, **extra: Any) -> dict[str, Any]:
        return {
            "show_nav": True,
            "nav": nav,
            "flash": _flash(request),
            **extra,
        }

    def _render(request: Request, name: str, context: dict[str, Any]):
        return templates.TemplateResponse(request, name, context)

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        if _authed(request):
            return RedirectResponse("/status", status_code=303)
        return RedirectResponse("/login", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    async def login_get(request: Request):
        if _authed(request):
            return RedirectResponse("/status", status_code=303)
        return _render(
            request,
            "login.html",
            {
                "show_nav": False,
                "flash": _flash(request),
                "nav": "",
                "sso_enabled": auth.sso_enabled(),
                "password_login": auth.password_login_enabled() and auth.password_configured(),
            },
        )

    @app.post("/login")
    async def login_post(request: Request, password: str = Form(...)):
        if not auth.password_login_enabled() or not auth.password_configured():
            return RedirectResponse(
                "/login?flash=err&msg=" + quote("Password login disabled"),
                status_code=303,
            )
        if not auth.verify_password(password):
            audit.append_event("login_failed")
            return RedirectResponse(
                "/login?flash=err&msg=" + quote("Invalid password"),
                status_code=303,
            )
        token = auth.mint_session(email=auth.PASSWORD_LOCAL_EMAIL)
        audit.append_event("login_ok", who="password")
        resp = RedirectResponse("/status", status_code=303)
        resp.set_cookie(value=token, **auth.session_cookie_kwargs())
        return resp

    @app.get("/auth/google")
    async def auth_google():
        if not auth.sso_enabled():
            return RedirectResponse(
                "/login?flash=err&msg=" + quote("Google SSO not configured"),
                status_code=303,
            )
        state = secrets.token_urlsafe(24)
        resp = RedirectResponse(auth.google_authorize_url(state=state), status_code=303)
        resp.set_cookie(
            key=_OAUTH_STATE_COOKIE,
            value=state,
            httponly=True,
            samesite="lax",
            max_age=600,
            path="/",
        )
        return resp

    @app.get("/auth/callback")
    async def auth_callback(request: Request):
        if not auth.sso_enabled():
            return RedirectResponse(
                "/login?flash=err&msg=" + quote("Google SSO not configured"),
                status_code=303,
            )
        err = request.query_params.get("error")
        if err:
            audit.append_event("login_failed", who="google", detail=err)
            return RedirectResponse(
                "/login?flash=err&msg=" + quote(f"Google auth error: {err}"),
                status_code=303,
            )
        state = request.query_params.get("state") or ""
        cookie_state = request.cookies.get(_OAUTH_STATE_COOKIE) or ""
        if not state or not cookie_state or state != cookie_state:
            audit.append_event("login_failed", who="google", detail="state_mismatch")
            return RedirectResponse(
                "/login?flash=err&msg=" + quote("OAuth state mismatch"),
                status_code=303,
            )
        code = request.query_params.get("code") or ""
        if not code:
            return RedirectResponse(
                "/login?flash=err&msg=" + quote("Missing OAuth code"),
                status_code=303,
            )
        try:
            info = auth.exchange_google_code(code)
        except auth.AuthError as exc:
            audit.append_event("login_failed", who="google", detail=str(exc)[:200])
            return RedirectResponse(
                "/login?flash=err&msg=" + quote(str(exc)[:200]),
                status_code=303,
            )
        token = auth.mint_session(email=str(info["email"]))
        audit.append_event("login_ok", who=str(info["email"]))
        resp = RedirectResponse("/status", status_code=303)
        resp.set_cookie(value=token, **auth.session_cookie_kwargs())
        resp.delete_cookie(_OAUTH_STATE_COOKIE, path="/")
        return resp

    @app.get("/logout")
    async def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(auth.COOKIE_NAME, path="/")
        audit.append_event("logout")
        return resp

    @app.get("/review", response_class=HTMLResponse)
    async def review_page(request: Request):
        denied = _require(request)
        if denied:
            return denied
        return _render(
            request,
            "review.html",
            _ctx(request, "review", snap=review_snapshot()),
        )

    @app.get("/api/review")
    async def api_review(request: Request):
        if not _authed(request):
            return {"error": "unauthorized"}
        return review_snapshot()

    @app.get("/status", response_class=HTMLResponse)
    async def status_page(request: Request):
        denied = _require(request)
        if denied:
            return denied
        from company_brain.runtime.fleet_gate import snapshot

        return _render(
            request,
            "status.html",
            _ctx(
                request,
                "status",
                rows=status_rows(),
                stale_minutes=stale_minutes(),
                fleet=snapshot(),
            ),
        )

    @app.post("/fleet/pause")
    async def fleet_pause(request: Request):
        denied = _require(request)
        if denied:
            return denied
        from company_brain.runtime.fleet_gate import request_pause

        request_pause(by="admin_console")
        audit.append_event("fleet_pause")
        return RedirectResponse(
            "/status?flash=ok&msg=" + quote("Fleet pause requested"),
            status_code=303,
        )

    @app.post("/fleet/resume")
    async def fleet_resume(request: Request):
        denied = _require(request)
        if denied:
            return denied
        from company_brain.runtime.fleet_gate import resume

        resume(by="admin_console")
        audit.append_event("fleet_resume")
        return RedirectResponse(
            "/status?flash=ok&msg=" + quote("Fleet resumed"),
            status_code=303,
        )

    @app.post("/fleet/request-redeploy")
    async def fleet_request_redeploy(request: Request):
        denied = _require(request)
        if denied:
            return denied
        from company_brain.runtime.fleet_gate import request_redeploy

        request_redeploy(by="admin_console", note="Manual redeploy cue from console")
        audit.append_event("fleet_request_redeploy")
        return RedirectResponse(
            "/status?flash=ok&msg=" + quote("Redeploy cue set"),
            status_code=303,
        )

    @app.post("/fleet/clear-redeploy")
    async def fleet_clear_redeploy(request: Request):
        denied = _require(request)
        if denied:
            return denied
        from company_brain.runtime.fleet_gate import clear_redeploy

        clear_redeploy()
        audit.append_event("fleet_clear_redeploy")
        return RedirectResponse(
            "/status?flash=ok&msg=" + quote("Redeploy cue cleared"),
            status_code=303,
        )

    @app.get("/api/status")
    async def api_status(request: Request):
        if not _authed(request):
            return {"error": "unauthorized"}
        from company_brain.runtime.fleet_gate import snapshot

        return {
            "rows": status_rows(),
            "stale_minutes": stale_minutes(),
            "fleet": snapshot(),
        }

    @app.get("/costs", response_class=HTMLResponse)
    async def costs_page(request: Request):
        denied = _require(request)
        if denied:
            return denied
        do_reconcile = request.query_params.get("reconcile") == "1"
        snap = costs_snapshot(reconcile=do_reconcile)
        return _render(
            request,
            "costs.html",
            _ctx(
                request,
                "costs",
                budget=snap["budget"],
                expense_rel=snap["expense_rel"],
                expense_body=snap["expense_body"],
                reconcile=snap["reconcile"],
                vm=snap["vm"],
                total_month_usd=snap["total_month_usd"],
                total_is_estimate=snap["total_is_estimate"],
            ),
        )

    @app.get("/query", response_class=HTMLResponse)
    async def query_page(request: Request):
        denied = _require(request)
        if denied:
            return denied
        from company_brain.wiki.citation_query import citation_query, expand_result

        q = (request.query_params.get("q") or "").strip()
        as_member = (request.query_params.get("as_member") or "").strip()
        expand = (request.query_params.get("expand") or "").strip()
        volume = (request.query_params.get("volume") or "").strip()
        member = (request.query_params.get("member") or "").strip()
        expanded = None
        result = None
        if expand:
            expanded = expand_result(
                expand,
                as_member=as_member,
                admin_bypass=True,
                volume=volume,
                member=member,
            )
        elif q:
            result = citation_query(
                q,
                as_member=as_member,
                admin_bypass=True,
                limit=12,
            )
        return _render(
            request,
            "query.html",
            _ctx(
                request,
                "query",
                q=q,
                as_member=as_member,
                result=result.to_dict() if result else None,
                expanded=expanded,
            ),
        )

    @app.get("/wiki", response_class=HTMLResponse)
    async def wiki_page(request: Request):
        denied = _require(request)
        if denied:
            return denied
        q = (request.query_params.get("q") or "").strip()
        hits: list[dict[str, Any]] = search_wiki(q) if q else []
        return _render(request, "wiki.html", _ctx(request, "wiki", q=q, hits=hits))

    @app.get("/wiki/edit", response_class=HTMLResponse)
    async def wiki_edit(request: Request):
        denied = _require(request)
        if denied:
            return denied
        path = (request.query_params.get("path") or "").strip()
        if not path:
            return RedirectResponse(
                "/wiki?flash=err&msg=" + quote("path required"),
                status_code=303,
            )
        try:
            page = get_page(path)
        except FileNotFoundError:
            return RedirectResponse(
                "/wiki?flash=err&msg=" + quote(f"not found: {path}"),
                status_code=303,
            )
        return _render(request, "wiki_edit.html", _ctx(request, "wiki", page=page))

    @app.post("/wiki/save")
    async def wiki_save(
        request: Request,
        rel_path: str = Form(...),
        title: str = Form(...),
        body: str = Form(...),
    ):
        denied = _require(request)
        if denied:
            return denied
        try:
            save_page(rel_path, title, body, sync=True)
        except Exception as exc:
            return RedirectResponse(
                "/wiki?flash=err&msg=" + quote(str(exc)[:200]),
                status_code=303,
            )
        return RedirectResponse(
            "/wiki/edit?path=" + quote(rel_path) + "&flash=ok&msg=" + quote("Saved"),
            status_code=303,
        )

    @app.get("/dispatch", response_class=HTMLResponse)
    async def dispatch_page(request: Request):
        denied = _require(request)
        if denied:
            return denied
        return _render(
            request,
            "dispatch.html",
            _ctx(request, "dispatch", jobs=dispatch_jobs(), result=None),
        )

    @app.post("/dispatch/run", response_class=HTMLResponse)
    async def dispatch_run(request: Request, job_id: str = Form(...), force: str = Form("")):
        denied = _require(request)
        if denied:
            return denied
        do_force = force in {"1", "true", "on", "yes"}
        try:
            result = run_dispatch(job_id, force=do_force)
            flash = {"kind": "ok", "text": f"Dispatched {job_id}"}
        except DispatchError as exc:
            result = {"status": "error", "error": str(exc)}
            flash = {"kind": "err", "text": str(exc)}
        except Exception as exc:
            result = {"status": "error", "error": str(exc)[:500]}
            flash = {"kind": "err", "text": str(exc)[:200]}
        return _render(
            request,
            "dispatch.html",
            {
                "show_nav": True,
                "nav": "dispatch",
                "flash": flash,
                "jobs": dispatch_jobs(),
                "result": result,
            },
        )

    @app.get("/assist", response_class=HTMLResponse)
    async def assist_get(request: Request):
        denied = _require(request)
        if denied:
            return denied
        return _render(
            request,
            "assist.html",
            _ctx(request, "assist", message="", reply="", proposals=[]),
        )

    @app.post("/assist", response_class=HTMLResponse)
    async def assist_post(request: Request, message: str = Form(...)):
        denied = _require(request)
        if denied:
            return denied
        from company_brain.admin_console.assist import run_assist

        out = run_assist(message)
        return _render(
            request,
            "assist.html",
            _ctx(
                request,
                "assist",
                message=message,
                reply=out.get("reply") or "",
                proposals=out.get("proposals") or [],
            ),
        )

    @app.get("/health")
    async def health():
        return {"ok": True, "service": "admin_console"}

    return app
