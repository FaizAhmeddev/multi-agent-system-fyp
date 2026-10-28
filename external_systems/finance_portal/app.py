"""AgentsMind Finance Portal: an external system with its own database, login and REST API.

Run from the repo root:
    uvicorn finance_portal.app:create_app --factory --app-dir external_systems --host 127.0.0.1 --port 8201

Environment (see .env.example):
    FINANCE_PORTAL_API_KEY       required, 24+ chars; X-API-Key for /api/v1 (used by finance-mcp)
    FINANCE_PORTAL_SECRET_KEY    required, 32+ chars; signs the staff session cookie
    FINANCE_PORTAL_ADMIN_EMAIL / FINANCE_PORTAL_ADMIN_PASSWORD   first staff account (first run only)
    FINANCE_PORTAL_DB_URL        default sqlite:///<repo>/data/finance_portal.db
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker
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
from .models import (
    CURRENCIES,
    DEPARTMENTS,
    EMPLOYMENT_LABELS,
    EMPLOYMENT_TYPES,
    PAYMENT_STATUSES,
    PERSON_STATUSES,
    Base,
    StaffUser,
    from_minor,
)
from .schemas import PaymentIn, PersonIn, PersonPatch

REPO_ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("finance_portal")
PORTAL_NAME = "AgentsMind Finance Portal"


def load_config() -> dict[str, str]:
    load_dotenv_file(REPO_ROOT / ".env")
    return {
        "db_url": env("FINANCE_PORTAL_DB_URL", f"sqlite:///{(REPO_ROOT / 'data' / 'finance_portal.db').as_posix()}"),
        "api_key": env("FINANCE_PORTAL_API_KEY", required=True, min_len=24),
        "secret_key": env("FINANCE_PORTAL_SECRET_KEY", required=True, min_len=32),
        "admin_email": env("FINANCE_PORTAL_ADMIN_EMAIL", ""),
        "admin_password": env("FINANCE_PORTAL_ADMIN_PASSWORD", ""),
    }


def create_app(config: dict[str, str] | None = None) -> FastAPI:
    cfg = config or load_config()
    engine = make_sqlite_engine(cfg["db_url"])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)  # noqa: N806
    templates = make_templates(Path(__file__).parent / "templates", portal_name=PORTAL_NAME, short_name="Finance Portal")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        Base.metadata.create_all(engine)  # the portal is a separate system; it owns its schema
        with SessionLocal() as db:
            bootstrap_staff(db, StaffUser, cfg["admin_email"], cfg["admin_password"], "Finance administrator")
        yield
        engine.dispose()

    app = FastAPI(title=PORTAL_NAME, version="1.0.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
    app.state.engine, app.state.SessionLocal = engine, SessionLocal
    app.add_middleware(SessionMiddleware, secret_key=cfg["secret_key"], session_cookie="finance_portal_session",
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

    # ── errors ──────────────────────────────────────────────────────────────
    def _is_api(request: Request) -> bool:
        return request.url.path.startswith("/api/")

    @app.exception_handler(svc.ServiceError)
    async def _svc_err(request: Request, exc: svc.ServiceError):
        if _is_api(request):
            return JSONResponse({"detail": {"code": exc.code, "message": exc.message}}, status_code=exc.status)
        return templates.TemplateResponse(request, "error.html", {"status": exc.status, "title": "Request failed",
                                                                  "message": exc.message, "back_url": "/people"},
                                          status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _val_err(request: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"detail": {"code": "validation_error", "message": "Check the fields.", "fields": fields}},
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_err(request: Request, exc: StarletteHTTPException):
        if _is_api(request):
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
            return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
        titles = {404: "Page not found", 403: "Not allowed", 405: "Not allowed"}
        msg = {404: "The page or record does not exist. It may have been deleted.",
               403: "You do not have access to this page."}.get(exc.status_code, "Something went wrong.")
        return templates.TemplateResponse(request, "error.html", {"status": exc.status_code,
                                                                  "title": titles.get(exc.status_code, "Error"),
                                                                  "message": msg, "back_url": "/people",
                                                                  "back_label": "Go to people"},
                                          status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        if _is_api(request):
            return JSONResponse({"detail": {"code": "server_error", "message": "Unexpected error. It was logged."}},
                                status_code=500)
        return templates.TemplateResponse(request, "error.html", {
            "status": 500, "title": "Something went wrong",
            "message": "The error was logged. Try again; if it keeps happening, tell the administrator.",
            "back_url": "/people"}, status_code=500)

    # ── REST API (X-API-Key) ────────────────────────────────────────────────
    def require_key(x_api_key: str | None = Header(default=None)) -> None:
        if not keys_match(x_api_key, cfg["api_key"]):
            raise HTTPException(401, detail={"code": "invalid_api_key", "message": "Missing or invalid X-API-Key."})

    def api_actor(x_actor: str | None) -> str:
        safe = "".join(ch for ch in (x_actor or "") if ch.isalnum() or ch in "@._-")[:120]
        return f"api:{safe or 'client'}"

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_key)])

    @app.get("/api/v1/health")
    def health() -> dict:
        return {"status": "ok", "service": "finance-portal"}

    @api.get("/people")
    def api_people(q: str = Query("", max_length=100), department: str = "", status: str = "",
                   employment_type: str = "", currency: str = "",
                   sort: str = Query("full_name", pattern="^(" + "|".join(svc.SORTABLE) + ")$"),
                   order: str = Query("asc", pattern="^(asc|desc)$"), page: int = Query(1, ge=1),
                   page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
        rows, total = svc.query_people(db, q=q, department=department, status=status,
                                       employment_type=employment_type, currency=currency, sort=sort, order=order,
                                       page=page, page_size=page_size)
        return {"items": [svc.person_out(p).model_dump(mode="json") for p in rows], **page_meta(total, page, page_size)}

    @api.post("/people", status_code=201)
    def api_create(body: PersonIn, response: Response, db: Session = Depends(get_db),
                   idempotency_key: str | None = Header(default=None, max_length=100),
                   x_actor: str | None = Header(default=None)) -> dict:
        p, created = svc.create_person(db, body, actor=api_actor(x_actor), via="api", idempotency_key=idempotency_key)
        if not created:
            response.status_code = 200
            response.headers["Idempotent-Replay"] = "true"
        return {"created": created, "person": svc.person_out(p).model_dump(mode="json")}

    @api.get("/people/{person_id}")
    def api_get(person_id: int, db: Session = Depends(get_db)) -> dict:
        return svc.person_out(svc.get_person(db, person_id)).model_dump(mode="json")

    @api.patch("/people/{person_id}")
    def api_update(person_id: int, body: PersonPatch, db: Session = Depends(get_db),
                   x_actor: str | None = Header(default=None)) -> dict:
        return svc.person_out(svc.update_person(db, person_id, body, actor=api_actor(x_actor))).model_dump(mode="json")

    @api.delete("/people/{person_id}")
    def api_delete(person_id: int, db: Session = Depends(get_db), x_actor: str | None = Header(default=None)) -> dict:
        return {"deleted": svc.delete_person(db, person_id, actor=api_actor(x_actor))}

    @api.get("/summary")
    def api_summary(db: Session = Depends(get_db)) -> dict:
        return svc.summary(db)

    @api.get("/payments")
    def api_payments(person_id: int | None = None, month: str = Query("", pattern=r"^(\d{4}-\d{2})?$"),
                     status: str = "", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                     db: Session = Depends(get_db)) -> dict:
        rows, total = svc.query_payments(db, person_id=person_id, month=month, status=status, page=page,
                                         page_size=page_size)
        return {"items": [svc.payment_out(r).model_dump(mode="json") for r in rows], **page_meta(total, page, page_size)}

    @api.post("/people/{person_id}/payments", status_code=201)
    def api_add_payment(person_id: int, body: PaymentIn, db: Session = Depends(get_db),
                        x_actor: str | None = Header(default=None)) -> dict:
        return svc.payment_out(svc.add_payment(db, person_id, body, actor=api_actor(x_actor))).model_dump(mode="json")

    app.include_router(api)

    # ── web screens (staff session) ─────────────────────────────────────────
    class LoginRequired(Exception):
        pass

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, _exc: LoginRequired):
        return RedirectResponse("/login?" + urlencode({"next": request.url.path}), status_code=303)

    def staff(request: Request, db: Session = Depends(get_db)) -> StaffUser:
        sid = request.session.get("staff_id")
        u = db.get(StaffUser, sid) if sid else None
        if u is None:
            raise LoginRequired()
        return u

    def check_csrf(request: Request, token: str | None) -> None:
        if not csrf_ok(request, token):
            raise HTTPException(403, detail="The form expired. Reload the page and try again.")

    def render(request: Request, name: str, ctx: dict[str, Any], status: int = 200) -> HTMLResponse:
        base = {"employment_labels": EMPLOYMENT_LABELS, "departments": DEPARTMENTS, "currencies": CURRENCIES,
                "employment_types": EMPLOYMENT_TYPES, "person_statuses": PERSON_STATUSES,
                "payment_statuses": PAYMENT_STATUSES, "money": from_minor}
        return templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/people", status_code=303)

    @app.get("/login", include_in_schema=False)
    def login_form(request: Request, next: str = "") -> HTMLResponse:
        return render(request, "login.html", {"action": "/login", "next": next})

    @app.post("/login", include_in_schema=False)
    def login_submit(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form(""),
                     csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        user, err = attempt_login(db, StaffUser, email, password)
        if user is None:
            return render(request, "login.html", {"action": "/login", "error": err, "email": email, "next": next},
                          status=401)
        request.session.clear()
        request.session["staff_id"] = user.id
        dest = next if next.startswith("/") and not next.startswith("//") else "/people"
        return RedirectResponse(dest, status_code=303)

    @app.post("/logout", include_in_schema=False)
    def logout(request: Request, csrf: str = Form("")):
        check_csrf(request, csrf)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    def _filters(q, department, status, employment_type, currency, sort, order) -> dict[str, str]:
        return {"q": q, "department": department, "status": status, "employment_type": employment_type,
                "currency": currency, "sort": sort if sort in svc.SORTABLE else "full_name",
                "order": order if order in ("asc", "desc") else "asc"}

    @app.get("/people", include_in_schema=False)
    def people(request: Request, q: str = "", department: str = "", status: str = "", employment_type: str = "",
               currency: str = "", sort: str = "full_name", order: str = "asc", page: int = Query(1, ge=1),
               user: StaffUser = Depends(staff), db: Session = Depends(get_db)) -> HTMLResponse:
        f = _filters(q[:100], department, status, employment_type, currency, sort, order)
        rows, total = svc.query_people(db, **f, page=page, page_size=25)
        return render(request, "people.html", {"user": user, "rows": rows, "f": f, "meta": page_meta(total, page, 25),
                                               "qs": urlencode(f), "qs_nosort": urlencode({k: v for k, v in f.items()
                                                                                           if k not in ("sort", "order")}),
                                               "summary": svc.summary(db), "nav": "people"})

    @app.get("/people/export.csv", include_in_schema=False)
    def export_csv(q: str = "", department: str = "", status: str = "", employment_type: str = "", currency: str = "",
                   sort: str = "full_name", order: str = "asc", user: StaffUser = Depends(staff),
                   db: Session = Depends(get_db)) -> Response:
        f = _filters(q[:100], department, status, employment_type, currency, sort, order)
        rows, _ = svc.query_people(db, **f, page=1, page_size=0)
        return Response(svc.people_csv(rows), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="people.csv"'})

    def _form_errors(exc: ValidationError) -> dict[str, str]:
        out: dict[str, str] = {}
        for e in exc.errors():
            key = str(e["loc"][0]) if e["loc"] else "_"
            msg = e["msg"].removeprefix("Value error, ")
            out.setdefault(key, msg)
        return out

    def _person_form_data(form: dict[str, str]) -> dict[str, Any]:
        keys = ("full_name", "email", "department", "job_title", "employment_type", "monthly_salary", "currency",
                "status", "start_date", "notes")
        return {k: (form.get(k) or "").strip() for k in keys}

    @app.get("/people/new", include_in_schema=False)
    def new_form(request: Request, user: StaffUser = Depends(staff)) -> HTMLResponse:
        return render(request, "person_form.html", {"user": user, "mode": "new", "v": {"employment_type": "full_time",
                      "currency": "PKR", "status": "active"}, "errors": {}, "nav": "people", "form_key": new_token(12)})

    @app.post("/people/new", include_in_schema=False)
    async def new_submit(request: Request, user: StaffUser = Depends(staff), db: Session = Depends(get_db)):
        form = dict(await request.form())
        check_csrf(request, form.get("csrf"))
        v = _person_form_data(form)
        try:
            data = PersonIn(**{k: val for k, val in v.items() if val != "" or k == "notes"})
            p, _ = svc.create_person(db, data, actor=user.email, via="portal",
                                     idempotency_key=("form-" + form["form_key"]) if form.get("form_key") else None)
        except ValidationError as exc:
            return render(request, "person_form.html", {"user": user, "mode": "new", "v": v, "nav": "people",
                                                        "errors": _form_errors(exc), "form_key": form.get("form_key")},
                          status=422)
        except svc.ServiceError as exc:
            return render(request, "person_form.html", {"user": user, "mode": "new", "v": v, "nav": "people",
                                                        "errors": {"email": exc.message}, "form_key": new_token(12)},
                          status=409)
        flash(request, f"{p.full_name} was added.", "ok")
        return RedirectResponse(f"/people/{p.id}", status_code=303)

    @app.get("/people/{person_id}", include_in_schema=False)
    def person_detail(request: Request, person_id: int, user: StaffUser = Depends(staff),
                      db: Session = Depends(get_db)) -> HTMLResponse:
        p = svc.get_person(db, person_id)
        return render(request, "person_detail.html", {"user": user, "p": p, "errors": {}, "pv": {}, "nav": "people"})

    @app.post("/people/{person_id}/payments", include_in_schema=False)
    async def payment_submit(request: Request, person_id: int, user: StaffUser = Depends(staff),
                             db: Session = Depends(get_db)):
        form = dict(await request.form())
        check_csrf(request, form.get("csrf"))
        p = svc.get_person(db, person_id)
        pv = {k: (form.get(k) or "").strip() for k in ("month", "amount", "status", "paid_on", "note")}
        try:
            data = PaymentIn(**{k: val for k, val in pv.items() if val != "" or k == "note"})
            svc.add_payment(db, person_id, data, actor=user.email)
        except ValidationError as exc:
            return render(request, "person_detail.html", {"user": user, "p": p, "errors": _form_errors(exc), "pv": pv,
                                                          "nav": "people"}, status=422)
        except svc.ServiceError as exc:
            return render(request, "person_detail.html", {"user": user, "p": p, "errors": {"month": exc.message},
                                                          "pv": pv, "nav": "people"}, status=409)
        flash(request, f"Payment for {data.month} recorded.", "ok")
        return RedirectResponse(f"/people/{person_id}", status_code=303)

    @app.get("/people/{person_id}/edit", include_in_schema=False)
    def edit_form(request: Request, person_id: int, user: StaffUser = Depends(staff),
                  db: Session = Depends(get_db)) -> HTMLResponse:
        p = svc.get_person(db, person_id)
        v = svc.person_out(p).model_dump(mode="json")
        return render(request, "person_form.html", {"user": user, "mode": "edit", "p": p, "v": v, "errors": {},
                                                    "nav": "people"})

    @app.post("/people/{person_id}/edit", include_in_schema=False)
    async def edit_submit(request: Request, person_id: int, user: StaffUser = Depends(staff),
                          db: Session = Depends(get_db)):
        form = dict(await request.form())
        check_csrf(request, form.get("csrf"))
        p = svc.get_person(db, person_id)
        v = _person_form_data(form)
        try:
            PersonIn(**{k: val for k, val in v.items() if val != "" or k == "notes"})  # full validation
            patch = PersonPatch(**{k: val for k, val in v.items() if val != "" or k == "notes"})
            svc.update_person(db, person_id, patch, actor=user.email)
        except ValidationError as exc:
            return render(request, "person_form.html", {"user": user, "mode": "edit", "p": p, "v": v,
                                                        "errors": _form_errors(exc), "nav": "people"}, status=422)
        except svc.ServiceError as exc:
            return render(request, "person_form.html", {"user": user, "mode": "edit", "p": p, "v": v,
                                                        "errors": {"email": exc.message}, "nav": "people"}, status=409)
        flash(request, "Changes saved.", "ok")
        return RedirectResponse(f"/people/{person_id}", status_code=303)

    @app.get("/people/{person_id}/delete", include_in_schema=False)
    def delete_confirm(request: Request, person_id: int, user: StaffUser = Depends(staff),
                       db: Session = Depends(get_db)) -> HTMLResponse:
        p = svc.get_person(db, person_id)
        return render(request, "person_delete.html", {"user": user, "p": p, "nav": "people", "error": ""})

    @app.post("/people/{person_id}/delete", include_in_schema=False)
    def delete_submit(request: Request, person_id: int, csrf: str = Form(""), confirm_name: str = Form(""),
                      user: StaffUser = Depends(staff), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        p = svc.get_person(db, person_id)
        if " ".join(confirm_name.split()).lower() != p.full_name.lower():
            return render(request, "person_delete.html", {"user": user, "p": p, "nav": "people",
                                                          "error": "Type the full name exactly to confirm."}, status=422)
        info = svc.delete_person(db, person_id, actor=user.email)
        flash(request, f"{info['full_name']} was deleted, with {info['payments_deleted']} payment record(s).", "ok")
        return RedirectResponse("/people", status_code=303)

    @app.get("/payments", include_in_schema=False)
    def payments(request: Request, month: str = "", status: str = "", page: int = Query(1, ge=1),
                 user: StaffUser = Depends(staff), db: Session = Depends(get_db)) -> HTMLResponse:
        if month and not (len(month) == 7 and month[4] == "-"):
            month = ""
        rows, total = svc.query_payments(db, month=month, status=status, page=page, page_size=25)
        f = {"month": month, "status": status}
        return render(request, "payments.html", {"user": user, "rows": rows, "f": f, "qs": urlencode(f),
                                                 "meta": page_meta(total, page, 25), "nav": "payments"})

    return app
