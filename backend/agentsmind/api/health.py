from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import __version__
from ..db.session import db_ping
from ..settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> JSONResponse:
    db_ok = db_ping()
    body = {
        "status": "ok" if db_ok else "degraded",
        "service": "agentsmind-core",
        "version": __version__,
        "env": get_settings().app_env,
        "checks": {"database": "ok" if db_ok else "error"},
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)
