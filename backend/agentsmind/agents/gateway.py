"""The only path from an agent to a tool.

Order of checks, all in code:
  1. the tool exists in the catalog
  2. the tool is on the calling agent's allow-list
  3. the signed-in user's roles allow the tool
  4. write/destructive tools need an approved Approval (created here as pending)
Every attempt, allowed or not, is written to `tool_calls` (inputs redacted).
Denials are also written to `audit_logs`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db.base import utcnow
from ..db.models import Approval, ToolCall, User
from ..log_config import redact
from ..rbac import has_any
from .catalog import AGENT_TOOLS, READ, TOOLS

log = logging.getLogger("agentsmind.tools")

Executor = Callable[[dict[str, Any], str], dict[str, Any]]  # (args, idempotency_key) -> result
EXECUTORS: dict[str, Executor] = {}


def register_executor(tool: str, fn: Executor) -> None:
    if tool not in TOOLS:
        raise KeyError(f"unknown tool {tool}")
    EXECUTORS[tool] = fn


@dataclass
class ToolOutcome:
    status: str  # ok | error | denied | approval_required
    tool: str
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    code: str = ""
    approval_id: int | None = None


def _canonical(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)


def approval_key(user_id: int, agent: str, tool: str, args: dict[str, Any]) -> str:
    h = hashlib.sha256(f"{user_id}|{agent}|{tool}|{_canonical(args)}".encode()).hexdigest()
    return f"appr-{h[:48]}"


def _log_call(db: Session, *, agent, tool, user, args, status, error="", latency_ms=0, approval_id=None,
              idempotency_key=None) -> None:
    spec = TOOLS.get(tool)
    db.add(ToolCall(agent=agent, tool=tool, server=spec.server if spec else "", user_id=user.id,
                    approval_id=approval_id, inputs_redacted=redact(args), status=status, error=error[:2000],
                    latency_ms=latency_ms, idempotency_key=idempotency_key))
    db.commit()
    log.info("tool call", extra={"agent": agent, "tool": tool, "status": status, "user": user.email,
                                 "latency_ms": latency_ms})


def _deny(db, *, agent, tool, user, args, code, message, ip) -> ToolOutcome:
    _log_call(db, agent=agent, tool=tool, user=user, args=args, status="denied", error=f"{code}: {message}")
    audit(db, "tool.denied", actor_user_id=user.id, actor_email=user.email, outcome="denied", ip=ip,
          target_type="tool", target_id=tool, detail={"agent": agent, "code": code})
    return ToolOutcome(status="denied", tool=tool, code=code, error=message)


def call_tool(db: Session, *, agent: str, tool: str, args: dict[str, Any], user: User,
              approval_id: int | None = None, summary: str = "", ip: str = "") -> ToolOutcome:
    spec = TOOLS.get(tool)
    if spec is None:
        return _deny(db, agent=agent, tool=tool, user=user, args=args, code="unknown_tool",
                     message=f"There is no tool named '{tool}'.", ip=ip)
    if tool not in AGENT_TOOLS.get(agent, frozenset()):
        return _deny(db, agent=agent, tool=tool, user=user, args=args, code="not_allowed_for_agent",
                     message=f"The {agent} agent is not allowed to use {tool}.", ip=ip)
    if not has_any(user.role_names, spec.roles):
        return _deny(db, agent=agent, tool=tool, user=user, args=args, code="role_forbidden",
                     message=f"Your role cannot use {tool}.", ip=ip)

    exec_args = args
    idem = None
    if spec.risk != READ:
        if approval_id is None:
            key = approval_key(user.id, agent, tool, args)
            appr = db.scalar(select(Approval).where(Approval.idempotency_key == key))
            if appr is None or appr.status in ("rejected", "failed", "executed"):
                if appr is not None:  # previous decision is final; a new request gets a new card
                    key = f"{key[:40]}-{int(time.time())}"
                appr = Approval(requested_by_user_id=user.id, agent=agent, tool=tool, risk=spec.risk,
                                summary=(summary or f"{tool} requested by {agent} agent")[:500],
                                arguments=args, status="pending", idempotency_key=key, result={})
                db.add(appr)
                db.commit()
                audit(db, "approval.requested", actor_user_id=user.id, actor_email=user.email, ip=ip,
                      target_type="approval", target_id=appr.id, detail={"tool": tool, "risk": spec.risk})
            _log_call(db, agent=agent, tool=tool, user=user, args=args, status="approval_required",
                      approval_id=appr.id)
            return ToolOutcome(status="approval_required", tool=tool, approval_id=appr.id,
                               code="approval_required", error="This action needs your approval first.")
        appr = db.get(Approval, approval_id)
        if appr is None or appr.tool != tool or appr.agent != agent:
            return _deny(db, agent=agent, tool=tool, user=user, args=args, code="approval_mismatch",
                         message="The approval does not match this action.", ip=ip)
        if appr.status == "executed":
            return ToolOutcome(status="ok", tool=tool, result=appr.result, approval_id=appr.id)
        if appr.status != "approved":
            return _deny(db, agent=agent, tool=tool, user=user, args=args, code="not_approved",
                         message="This action has not been approved.", ip=ip)
        exec_args = appr.arguments  # never trust re-sent arguments; run exactly what was approved
        idem = appr.idempotency_key

    fn = EXECUTORS.get(tool)
    start = time.perf_counter()
    if fn is None:
        outcome = ToolOutcome(status="error", tool=tool, code="tool_unavailable",
                              error=f"{tool} is not connected yet (its MCP server arrives in a later phase).")
    else:
        try:
            outcome = ToolOutcome(status="ok", tool=tool, result=fn(exec_args, idem or ""))
        except Exception as exc:  # noqa: BLE001 - reported to the user and logged
            outcome = ToolOutcome(status="error", tool=tool, code="tool_error", error=f"{type(exc).__name__}: {exc}")
    ms = int((time.perf_counter() - start) * 1000)
    if spec.risk != READ:
        appr.status = "executed" if outcome.status == "ok" else "failed"
        appr.result = outcome.result if outcome.status == "ok" else {"error": outcome.error}
        appr.updated_at = utcnow()
        outcome.approval_id = appr.id
    _log_call(db, agent=agent, tool=tool, user=user, args=exec_args, status=outcome.status, error=outcome.error,
              latency_ms=ms, approval_id=outcome.approval_id, idempotency_key=idem)
    return outcome
