"""AgentsMind IT Helpdesk: an external system with a public complaint form, staff screens and a REST API.

Run from the repo root:
    uvicorn it_portal.app:create_app --factory --app-dir external_systems --host 127.0.0.1 --port 8202

Environment (see .env.example):
    IT_PORTAL_API_KEY       required, 24+ chars; X-API-Key for /api/v1 (used by it-mcp)
    IT_PORTAL_SECRET_KEY    required, 32+ chars; signs the staff session cookie
    IT_PORTAL_ADMIN_EMAIL / IT_PORTAL_ADMIN_PASSWORD   first staff account (first run only)
    IT_PORTAL_PUBLIC_URL    default http://127.0.0.1:8202 (used in confirmation links)
    IT_PORTAL_DB_URL        default sqlite:///<repo>/data/it_portal.db
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from portal_common.core import (
    COMMON_DIR,
    csrf_ok,
    env,
    flash,
    keys_match,
    load_dotenv_file,
    make_sqlite_engine,
    make_templates,
    new_token,
    page_meta,
)
from portal_common.staff import attempt_login, bootstrap_staff

from . import service as svc
from .models import CATEGORIES, DEPARTMENTS, PRIORITIES, SLA_HOURS, STATUSES, TRANSITIONS, Attachment, Base, StaffUser

REPO_ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("it_portal")
PORTAL_NAME = "AgentsMind IT Helpdesk"


def load_config() -> dict[str, str]:
    load_dotenv_file(REPO_ROOT / ".env")
    return {
        "db_url": env("IT_PORTAL_DB_URL", f"sqlite:///{(REPO_ROOT / 'data' / 'it_portal.db').as_posix()}"),
        "api_key": env("IT_PORTAL_API_KEY", required=True, min_len=24),
        "secret_key": env("IT_PORTAL_SECRET_KEY", required=True, min_len=32),
        "admin_email": env("IT_PORTAL_ADMIN_EMAIL", ""),
        "admin_password": env("IT_PORTAL_ADMIN_PASSWORD", ""),
        "public_url": env("IT_PORTAL_PUBLIC_URL", "http://127.0.0.1:8202").rstrip("/"),
        "upload_dir": env("IT_PORTAL_UPLOAD_DIR", str(REPO_ROOT / "data" / "it_portal_uploads")),
    }


def create_app(config: dict[str, str] | None = None) -> FastAPI:
    cfg = config or load_config()
    engine = make_sqlite_engine(cfg["db_url"])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)  # noqa: N806
    upload_dir = Path(cfg["upload_dir"])
    templates = make_templates(Path(__file__).parent / "templates", portal_name=PORTAL_NAME, short_name="IT Helpdesk")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            bootstrap_staff(db, StaffUser, cfg["admin_email"], cfg["admin_password"], "IT administrator")
        yield
        engine.dispose()

    app = FastAPI(title=PORTAL_NAME, version="1.0.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
    app.state.engine, app.state.SessionLocal = engine, SessionLocal
    app.add_middleware(SessionMiddleware, secret_key=cfg["secret_key"], session_cookie="it_portal_session",
                       max_age=8 * 3600, same_site="lax", https_only=False)
    app.mount("/static", StaticFiles(directory=str(COMMON_DIR / "static")), name="static")

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    def get_db() -> Iterator[Session]:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def confirmation_url(number: str, token: str) -> str:
        return f"{cfg['public_url']}/complaint/submitted/{number}?t={quote(token)}"

    def tracking_url(number: str, token: str) -> str:
        return f"{cfg['public_url']}/track/{number}?t={quote(token)}"

    base_ctx = {"categories": CATEGORIES, "priorities": PRIORITIES, "statuses": STATUSES, "departments": DEPARTMENTS,
                "sla_hours": SLA_HOURS, "transitions": TRANSITIONS}

    def render(request: Request, name: str, ctx: dict[str, Any], status: int = 200) -> HTMLResponse:
        return templates.TemplateResponse(request, name, {**base_ctx, **ctx}, status_code=status)

    # ── errors ──────────────────────────────────────────────────────────────
    def _is_api(request: Request) -> bool:
        return request.url.path.startswith("/api/")

    @app.exception_handler(svc.ServiceError)
    async def _svc_err(request: Request, exc: svc.ServiceError):
        if _is_api(request):
            return JSONResponse({"detail": {"code": exc.code, "message": exc.message}}, status_code=exc.status)
        return render(request, "error.html", {"status": exc.status, "title": "Request failed", "message": exc.message,
                                              "back_url": "/"}, status=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _val_err(request: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"detail": {"code": "validation_error", "message": "Check the fields.", "fields": fields}},
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_err(request: Request, exc: StarletteHTTPException):
        if _is_api(request):
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
            return JSONResponse({"detail": detail}, status_code=exc.status_code)
        msg = {404: "The page or ticket does not exist. Check the link you were given.",
               403: str(exc.detail) if exc.detail else "You do not have access to this page."}.get(
            exc.status_code, "Something went wrong.")
        return render(request, "error.html", {"status": exc.status_code,
                                              "title": "Page not found" if exc.status_code == 404 else "Not allowed",
                                              "message": msg, "back_url": "/", "back_label": "Raise a complaint"},
                      status=exc.status_code)

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        if _is_api(request):
            return JSONResponse({"detail": {"code": "server_error", "message": "Unexpected error. It was logged."}},
                                status_code=500)
        return render(request, "error.html", {"status": 500, "title": "Something went wrong",
                                              "message": "The error was logged. Try again in a moment.",
                                              "back_url": "/"}, status=500)

    # ── REST API ────────────────────────────────────────────────────────────
    def require_key(x_api_key: str | None = Header(default=None)) -> None:
        if not keys_match(x_api_key, cfg["api_key"]):
            raise HTTPException(401, detail={"code": "invalid_api_key", "message": "Missing or invalid X-API-Key."})

    def api_actor(x_actor: str | None) -> str:
        safe = "".join(ch for ch in (x_actor or "") if ch.isalnum() or ch in "@._-")[:120]
        return safe or "api:client"

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_key)])

    @app.get("/api/v1/health")
    def health() -> dict:
        return {"status": "ok", "service": "it-helpdesk"}

    @api.post("/tickets", status_code=201)
    def api_create(body: svc.TicketIn, response: Response, db: Session = Depends(get_db),
                   idempotency_key: str | None = Header(default=None, max_length=100),
                   x_actor: str | None = Header(default=None)) -> dict:
        t, token, created = svc.create_ticket(db, body, actor=api_actor(x_actor), source="agentsmind",
                                              idempotency_key=idempotency_key)
        out = {"created": created, "ticket": svc.ticket_out(t, include_internal=False)}
        if token:
            out["confirmation_url"] = confirmation_url(t.number, token)
            out["tracking_url"] = tracking_url(t.number, token)
        else:
            response.status_code = 200
            response.headers["Idempotent-Replay"] = "true"
        return out

    @api.get("/tickets")
    def api_list(status: str = "", priority: str = "", category: str = "", q: str = Query("", max_length=100),
                 assignee: str = "", requester_email: str = "",
                 sort: str = Query("created_at", pattern="^(created_at|sla_due_at|priority|status|id)$"),
                 order: str = Query("desc", pattern="^(asc|desc)$"), page: int = Query(1, ge=1),
                 page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
        rows, total = svc.query_tickets(db, status=status, priority=priority, category=category, q=q,
                                        assignee=assignee, requester_email=requester_email, sort=sort, order=order,
                                        page=page, page_size=page_size)
        return {"items": [svc.ticket_out(t) for t in rows], **page_meta(total, page, page_size)}

    @api.get("/tickets/{number}")
    def api_get(number: str, db: Session = Depends(get_db)) -> dict:
        return svc.ticket_out(svc.get_ticket(db, number))

    @api.patch("/tickets/{number}/status")
    def api_status(number: str, body: svc.StatusChangeIn, db: Session = Depends(get_db),
                   x_actor: str | None = Header(default=None)) -> dict:
        return svc.ticket_out(svc.change_status(db, number, body, actor=api_actor(x_actor)))

    @api.post("/tickets/{number}/comments", status_code=201)
    def api_comment(number: str, body: svc.CommentIn, db: Session = Depends(get_db),
                    x_actor: str | None = Header(default=None)) -> dict:
        return svc.ticket_out(svc.add_comment(db, number, body, actor=api_actor(x_actor)))

    app.include_router(api)

    # ── public complaint form ───────────────────────────────────────────────
    def check_csrf(request: Request, token: str | None) -> None:
        if not csrf_ok(request, token):
            raise HTTPException(403, detail="The form expired. Reload the page and try again.")

    def _form_errors(exc: ValidationError) -> dict[str, str]:
        out: dict[str, str] = {}
        for e in exc.errors():
            out.setdefault(str(e["loc"][0]) if e["loc"] else "_", e["msg"].removeprefix("Value error, "))
        return out

    @app.get("/", include_in_schema=False)
    def complaint_form(request: Request) -> HTMLResponse:
        return render(request, "complaint.html", {"v": {"priority": "medium"}, "errors": {}, "form_key": new_token(12)})

    @app.post("/complaint", include_in_schema=False)
    async def complaint_submit(request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        check_csrf(request, form.get("csrf"))
        keys = ("requester_name", "requester_email", "department", "category", "priority", "summary", "description")
        v = {k: str(form.get(k) or "").strip() for k in keys}
        upload = form.get("attachment")
        attachment = None
        if isinstance(upload, UploadFile) and upload.filename:
            data = await upload.read(svc.MAX_UPLOAD_BYTES + 1)
            attachment = (upload.filename, data)
        try:
            data_in = svc.TicketIn(**{k: val for k, val in v.items() if val != "" or k == "summary"})
            t, token, _ = svc.create_ticket(db, data_in, actor=data_in.requester_email, source="portal",
                                            idempotency_key=("form-" + str(form.get("form_key")))
                                            if form.get("form_key") else None,
                                            attachment=attachment, upload_dir=upload_dir)
        except ValidationError as exc:
            return render(request, "complaint.html", {"v": v, "errors": _form_errors(exc),
                                                      "form_key": form.get("form_key")}, status=422)
        except svc.ServiceError as exc:
            return render(request, "complaint.html", {"v": v, "errors": {"attachment": exc.message},
                                                      "form_key": form.get("form_key")}, status=exc.status)
        if token is None:  # double submit of the same form: show the original ticket without a new token
            return render(request, "error.html", {"status": 409, "title": "Already submitted",
                                                  "message": f"This form was already submitted as {t.number}. "
                                                             "Use the link from the first confirmation page.",
                                                  "back_url": "/"}, status=409)
        return RedirectResponse(f"/complaint/submitted/{t.number}?t={quote(token)}", status_code=303)

    def _ticket_for_requester(db: Session, number: str, t_token: str):
        t = svc.get_ticket(db, number)
        if not svc.check_tracking(t, t_token):
            raise HTTPException(404)  # do not reveal whether the ticket exists
        return t

    @app.get("/complaint/submitted/{number}", include_in_schema=False)
    def submitted(request: Request, number: str, t: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
        ticket = _ticket_for_requester(db, number, t)
        return render(request, "submitted.html", {"t": ticket, "track_url": f"/track/{ticket.number}?t={quote(t)}",
                                                  "expected": svc.response_time_text(ticket.priority)})

    @app.get("/track/{number}", include_in_schema=False)
    def track(request: Request, number: str, t: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
        ticket = _ticket_for_requester(db, number, t)
        return render(request, "track.html", {"t": ticket, "view": svc.ticket_out(ticket, include_internal=False)})

    # ── staff screens ───────────────────────────────────────────────────────
    class LoginRequired(Exception):
        pass

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, _exc: LoginRequired):
        return RedirectResponse("/staff/login?" + urlencode({"next": request.url.path}), status_code=303)

    def staff(request: Request, db: Session = Depends(get_db)) -> StaffUser:
        sid = request.session.get("staff_id")
        u = db.get(StaffUser, sid) if sid else None
        if u is None:
            raise LoginRequired()
        return u

    @app.get("/staff/login", include_in_schema=False)
    def staff_login_form(request: Request, next: str = "") -> HTMLResponse:
        return render(request, "login.html", {"action": "/staff/login", "next": next})

    @app.post("/staff/login", include_in_schema=False)
    def staff_login(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form(""),
                    csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        user, err = attempt_login(db, StaffUser, email, password)
        if user is None:
            return render(request, "login.html", {"action": "/staff/login", "error": err, "email": email,
                                                  "next": next}, status=401)
        request.session.clear()
        request.session["staff_id"] = user.id
        dest = next if next.startswith("/staff") else "/staff/tickets"
        return RedirectResponse(dest, status_code=303)

    @app.post("/staff/logout", include_in_schema=False)
    def staff_logout(request: Request, csrf: str = Form("")):
        check_csrf(request, csrf)
        request.session.clear()
        return RedirectResponse("/staff/login", status_code=303)

    @app.get("/staff/tickets", include_in_schema=False)
    def staff_tickets(request: Request, status: str = "", priority: str = "", category: str = "", q: str = "",
                      sort: str = "created_at", order: str = "desc", page: int = Query(1, ge=1),
                      user: StaffUser = Depends(staff), db: Session = Depends(get_db)) -> HTMLResponse:
        f = {"status": status, "priority": priority, "category": category, "q": q[:100],
             "sort": sort if sort in ("created_at", "sla_due_at", "priority", "status") else "created_at",
             "order": order if order in ("asc", "desc") else "desc"}
        rows, total = svc.query_tickets(db, **f, page=page, page_size=25)
        return render(request, "staff_tickets.html", {
            "user": user, "rows": [(r, svc.ticket_out(r)) for r in rows], "f": f, "qs": urlencode(f),
            "qs_nosort": urlencode({k: v for k, v in f.items() if k not in ("sort", "order")}),
            "meta": page_meta(total, page, 25), "nav": "tickets"})

    @app.get("/staff/tickets/{number}", include_in_schema=False)
    def staff_ticket(request: Request, number: str, user: StaffUser = Depends(staff),
                     db: Session = Depends(get_db)) -> HTMLResponse:
        t = svc.get_ticket(db, number)
        staff_emails = [s.email for s in db.scalars(select(StaffUser).order_by(StaffUser.email))]
        return render(request, "staff_ticket.html", {"user": user, "t": t, "view": svc.ticket_out(t),
                                                     "staff_emails": staff_emails, "nav": "tickets", "error": ""})

    @app.post("/staff/tickets/{number}/status", include_in_schema=False)
    def staff_status(request: Request, number: str, status: str = Form(""), comment: str = Form(""),
                     csrf: str = Form(""), user: StaffUser = Depends(staff), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        try:
            svc.change_status(db, number, svc.StatusChangeIn(status=status, comment=comment), actor=user.email)
        except (ValidationError, svc.ServiceError) as exc:
            flash(request, exc.message if isinstance(exc, svc.ServiceError) else "Choose a valid status.", "error")
        else:
            flash(request, f"Status changed to {STATUSES[status]}.", "ok")
        return RedirectResponse(f"/staff/tickets/{number}", status_code=303)

    @app.post("/staff/tickets/{number}/comment", include_in_schema=False)
    def staff_comment(request: Request, number: str, body: str = Form(""), internal: str = Form(""),
                      csrf: str = Form(""), user: StaffUser = Depends(staff), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        try:
            svc.add_comment(db, number, svc.CommentIn(body=body, internal=bool(internal)), actor=user.email)
        except (ValidationError, svc.ServiceError) as exc:
            flash(request, exc.message if isinstance(exc, svc.ServiceError) else "Write a comment first.", "error")
        else:
            flash(request, "Comment added.", "ok")
        return RedirectResponse(f"/staff/tickets/{number}", status_code=303)

    @app.post("/staff/tickets/{number}/assign", include_in_schema=False)
    def staff_assign(request: Request, number: str, assignee: str = Form(""), csrf: str = Form(""),
                     user: StaffUser = Depends(staff), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        valid = {s.email for s in db.scalars(select(StaffUser))}
        if assignee and assignee not in valid:
            flash(request, "Choose a staff member from the list.", "error")
        else:
            svc.assign(db, number, assignee, actor=user.email)
            flash(request, f"Assigned to {assignee}." if assignee else "Unassigned.", "ok")
        return RedirectResponse(f"/staff/tickets/{number}", status_code=303)

    @app.get("/staff/attachments/{attachment_id}", include_in_schema=False)
    def staff_attachment(attachment_id: int, user: StaffUser = Depends(staff), db: Session = Depends(get_db)):
        a = db.get(Attachment, attachment_id)
        if a is None or not (upload_dir / a.stored_name).is_file():
            raise HTTPException(404)
        return FileResponse(upload_dir / a.stored_name, media_type=a.mime_type, filename=a.original_name,
                            content_disposition_type="attachment")

    return app
