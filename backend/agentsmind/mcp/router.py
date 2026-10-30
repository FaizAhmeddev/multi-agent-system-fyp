"""Settings > Connectors: add, change, test and remove MCP connectors (administrators)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..audit import audit
from ..auth.deps import require_roles
from ..db.models import User
from ..db.session import get_db
from . import connectors as C

router = APIRouter(prefix="/api", tags=["connectors"])
ADMIN = require_roles("admin")


class ConnectorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=31)
    title: str = Field(default="", max_length=80)
    enabled: bool = True
    transport: str = Field(pattern="^(stdio|http)$")
    command: str = Field(default="", max_length=300)
    args: list[str] = Field(default_factory=list, max_length=30)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = Field(default="", max_length=500)
    url: str = Field(default="", max_length=500)
    headers: dict[str, str] = Field(default_factory=dict)
    roles: list[str] = Field(default_factory=lambda: ["hr", "it", "finance", "employee"])
    keywords: list[str] = Field(default_factory=list, max_length=20)
    read_tools: list[str] = Field(default_factory=list)
    write_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    guess_read_by_name: bool = True
    description: str = Field(default="", max_length=300)
    timeout_seconds: float = Field(default=60.0, ge=5, le=300)
    secrets: dict[str, str] = Field(default_factory=dict, description="NAME -> value, written to .env only")


def _bad(msg: str) -> HTTPException:
    return HTTPException(422, detail={"code": "validation_error", "message": msg})


def _save(body: ConnectorIn, user: User, db: Session, *, replace: str | None) -> dict[str, Any]:
    d = body.model_dump(exclude={"secrets"})
    old = C.get(replace) if replace else None
    for part in ("env", "headers"):  # "(hidden)" means: keep the value already saved
        d[part] = {k: (getattr(old, part, {}).get(k, "") if v == C.HIDDEN else v) for k, v in d[part].items()}
    try:
        c = C.Connector.from_dict(d)
        for k, v in body.secrets.items():
            if v:
                C.set_secret(k, v)
    except ValueError as exc:
        raise _bad(str(exc)) from None
    conns = C.load()
    if replace is None and any(x.name == c.name for x in conns):
        raise _bad(f"A connector named '{c.name}' already exists.")
    conns = [x for x in conns if x.name not in (c.name, replace)] + [c]
    C.save(conns)
    if replace and replace != c.name:
        C.unregister(replace)
        C.POOL.close(replace)
    C.POOL.close(c.name)
    d2 = C.discover(c, force=True)
    audit(db, "connector.saved", actor_user_id=user.id, actor_email=user.email, target_type="connector",
          target_id=c.name, detail={"transport": c.transport, "tools": len(d2.tools), "error": d2.error[:200],
                                    "secrets": sorted(body.secrets)})
    return next(x for x in C.status() if x["name"] == c.name)


@router.get("/connectors")
def list_connectors(user: User = Depends(ADMIN)) -> dict:
    tpl = C.REPO_ROOT / "config" / "connector_templates.json"
    templates = json.loads(tpl.read_text(encoding="utf-8")).get("templates", []) if tpl.is_file() else []
    return {"items": C.status(), "templates": templates, "file": str(C.config_path())}


@router.post("/connectors", status_code=201)
def add_connector(body: ConnectorIn, user: User = Depends(ADMIN), db: Session = Depends(get_db)) -> dict:
    return _save(body, user, db, replace=None)


@router.put("/connectors/{name}")
def update_connector(name: str, body: ConnectorIn, user: User = Depends(ADMIN), db: Session = Depends(get_db)) -> dict:
    if C.get(name) is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "No such connector."})
    return _save(body, user, db, replace=name)


@router.post("/connectors/{name}/refresh")
def refresh_connector(name: str, user: User = Depends(ADMIN)) -> dict:
    c = C.get(name)
    if c is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "No such connector."})
    C.POOL.close(name)
    C.discover(c, force=True)
    return next(x for x in C.status() if x["name"] == name)


@router.delete("/connectors/{name}", status_code=204)
def delete_connector(name: str, user: User = Depends(ADMIN), db: Session = Depends(get_db)) -> None:
    conns = C.load()
    if not any(x.name == name for x in conns):
        raise HTTPException(404, detail={"code": "not_found", "message": "No such connector."})
    C.save([x for x in conns if x.name != name])
    C.unregister(name)
    C.POOL.close(name)
    audit(db, "connector.deleted", actor_user_id=user.id, actor_email=user.email, target_type="connector",
          target_id=name, detail={})
