"""Create and execute agent runs. Execution happens in the queue worker."""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import AgentRun, User
from ..db.session import SessionLocal
from ..queue.core import get_queue
from ..rbac import has_any
from .llm import get_llm
from .registry import AGENTS

log = logging.getLogger("agentsmind.agents")


class AgentAccessError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def check_agent_access(user: User, agent: str, action: str | None = None) -> None:
    spec = AGENTS.get(agent)
    if spec is None:
        raise AgentAccessError("unknown_agent", f"There is no agent named '{agent}'.", 404)
    if not has_any(user.role_names, spec.roles):
        raise AgentAccessError("forbidden", f"Your role cannot use the {spec.title}.", 403)
    if action is not None and action not in spec.actions:
        raise AgentAccessError("unknown_action", f"The {spec.title} has no action '{action}'.", 404)


def create_run(db: Session, *, user: User, agent: str, action: str, inputs: dict[str, Any],
               idempotency_key: str | None = None) -> AgentRun:
    check_agent_access(user, agent, action)
    schema = AGENTS[agent].actions[action].schema
    clean = schema.model_validate(inputs).model_dump()  # raises ValidationError on bad input
    run = AgentRun(user_id=user.id, agent=agent, action=action, status="queued",
                   input_text=json.dumps(clean, ensure_ascii=False), output_text="", error="", meta={})
    db.add(run)
    db.commit()
    key = f"agent-run:{user.id}:{idempotency_key}" if idempotency_key else f"agent-run:{run.id}"
    task = get_queue().enqueue("agent.run", {"run_id": run.id}, queue="default", idempotency_key=key,
                               created_by_user_id=user.id)
    if task.payload.get("run_id") != run.id:
        # Same Idempotency-Key as an earlier request: return the original run, drop this one.
        db.delete(run)
        db.commit()
        existing = db.get(AgentRun, task.payload["run_id"])
        assert existing is not None
        return existing
    run.task_id = task.id
    db.commit()
    return run


def execute_run(run_id: int) -> dict[str, Any]:
    """Queue handler body. Safe to call twice: a finished run is returned unchanged."""
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        if run is None:
            raise LookupError(f"agent run {run_id} not found")
        if run.status in ("done", "failed"):
            return {"run_id": run.id, "status": run.status, "repeat": True}
        user = db.get(User, run.user_id) if run.user_id else None
        if user is None or not user.is_active:
            run.status, run.error, run.finished_at = "failed", "requesting user no longer active", utcnow()
            db.commit()
            return {"run_id": run.id, "status": run.status}
        spec = AGENTS[run.agent]
        action = spec.actions[run.action]
        run.status = "running"
        db.commit()
        try:
            check_agent_access(user, run.agent, run.action)  # roles may have changed since enqueue
            inputs = action.schema.model_validate(json.loads(run.input_text))
            out = action.run(inputs, user.full_name, get_llm())
        except (AgentAccessError, ValidationError) as exc:
            run.status, run.error, run.finished_at = "failed", str(exc), utcnow()
            db.commit()
            return {"run_id": run.id, "status": run.status}
        run.output_text = out.text
        run.meta = {"simulated": out.simulated, "model": out.model, **out.meta}
        run.status, run.finished_at = "done", utcnow()
        db.commit()
        log.info("agent run done", extra={"run_id": run.id, "agent": run.agent, "action": run.action,
                                          "simulated": out.simulated})
        return {"run_id": run.id, "status": run.status, "simulated": out.simulated}
