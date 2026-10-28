"""Internal endpoints for the MCP servers (not for browsers).

GET /api/internal/status  used by workspace-mcp's queue_stats and agent_status tools.
Auth: `Authorization: Bearer <WORKSPACE_MCP_TOKEN>`, the same shared secret the core
uses to call workspace-mcp. No user data is returned, only counts.
"""
from __future__ import annotations

import hmac
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import AgentRun, QueueTask
from ..db.session import get_db
from ..queue.core import DEAD, PENDING, get_queue
from ..settings import get_settings

router = APIRouter(prefix="/api/internal", tags=["internal"], include_in_schema=False)


def _require_workspace_token(authorization: str = Header(default="")) -> None:
    tok = get_settings().workspace_mcp_token
    expected = tok.get_secret_value().strip() if tok else ""
    given = authorization.removeprefix("Bearer ").strip()
    if not expected or not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, detail={"code": "unauthorized", "message": "Bad internal token."})


@router.get("/status", dependencies=[Depends(_require_workspace_token)])
def status(db: Session = Depends(get_db)) -> dict:
    from ..agents.registry import AGENTS
    from ..mcp.client import server_configs

    s = get_settings()
    counts: dict[str, int] = {}
    for q in get_queue().stats().values():
        for k, v in q.items():
            counts[k] = counts.get(k, 0) + v
    oldest = None
    if s.queue_backend == "db":
        first = db.scalar(select(func.min(QueueTask.created_at)).where(QueueTask.status == PENDING))
        if first is not None:
            oldest = round((utcnow() - first).total_seconds(), 1)
    since = utcnow() - timedelta(hours=24)
    runs = dict(db.execute(select(AgentRun.agent, func.count(AgentRun.id)).where(AgentRun.started_at >= since)
                           .group_by(AgentRun.agent)).all())
    failed = dict(db.execute(select(AgentRun.agent, func.count(AgentRun.id))
                             .where(AgentRun.started_at >= since, AgentRun.status == "failed")
                             .group_by(AgentRun.agent)).all())
    configured = server_configs()
    return {
        "queue": {"backend": s.queue_backend, "counts": counts, "dead": counts.get(DEAD, 0),
                  "oldest_queued_seconds": oldest},
        "agents": {
            "llm_mode": "openai" if s.llm_configured else "sandbox (Simulated)",
            "agents": [{"name": k, "title": a.title, "runs_last_24h": runs.get(k, 0),
                        "failed_last_24h": failed.get(k, 0)} for k, a in AGENTS.items()],
            "mcp_servers": {n: ("configured" if n in configured else "not configured")
                            for n in ("finance-mcp", "it-mcp", "calendar-mcp", "workspace-mcp")},
        },
    }
