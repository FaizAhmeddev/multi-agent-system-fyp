"""AgentsMind core API.

Run (from the repo root):
    uvicorn agentsmind.main:app --app-dir backend --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect

from .admin.router import router as admin_router
from .api.health import router as health_router
from .auth.router import router as auth_router
from .auth.service import AuthError, bootstrap_first_admin
from .db.session import SessionLocal, get_engine
from .log_config import configure_logging, request_id_var
from .settings import get_settings

log = logging.getLogger("agentsmind.api")


def _check_schema() -> None:
    tables = set(inspect(get_engine()).get_table_names())
    if "alembic_version" not in tables or "users" not in tables:
        raise RuntimeError("Database is not migrated. Run:  alembic upgrade head   (from the repo root)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    _check_schema()
    with SessionLocal() as db:
        bootstrap_first_admin(db)
    log.info("startup complete", extra={"env": s.app_env, "db": s.database_url.split("://", 1)[0]})
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="AgentsMind API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs" if s.app_env != "prod" else None, redoc_url=None)

    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid[:64])
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        ms = int((time.perf_counter() - start) * 1000)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        log.info("request", extra={"method": request.method, "path": request.url.path,
                                   "status": response.status_code, "latency_ms": ms, "request_id": rid})
        return response

    @app.exception_handler(AuthError)
    async def _auth_error(_: Request, exc: AuthError):
        return JSONResponse({"detail": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"detail": {"code": "validation_error", "message": "Check the highlighted fields.",
                                        "fields": fields}}, status_code=422)

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(admin_router)
    return app


app = create_app()
