"""Append-only audit log helper."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from .db.models import AuditLog
from .log_config import redact, request_id_var

log = logging.getLogger("agentsmind.audit")


def audit(
    db: Session,
    action: str,
    *,
    actor_user_id: int | None = None,
    actor_email: str = "",
    target_type: str = "",
    target_id: str | int = "",
    outcome: str = "success",
    ip: str = "",
    detail: dict[str, Any] | None = None,
    commit: bool = True,
) -> AuditLog:
    row = AuditLog(
        action=action,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        target_type=target_type,
        target_id=str(target_id),
        outcome=outcome,
        ip=ip,
        request_id=request_id_var.get(),
        detail=redact(detail or {}),
    )
    db.add(row)
    if commit:
        db.commit()
    log.info("audit", extra={"action": action, "outcome": outcome, "actor": actor_email,
                             "target": f"{target_type}:{target_id}"})
    return row
