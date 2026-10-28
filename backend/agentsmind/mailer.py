"""Outbound email.

Phase 1a ships only the sandbox mailer: messages are stored in `outbound_emails`
with `simulated=True` and are visible to admins. Nothing leaves the machine.
The Gmail API mailer arrives in Phase 3 behind the approval gate.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .db.models import OutboundEmail


def send_system_email(db: Session, *, to: str, subject: str, body: str, purpose: str) -> OutboundEmail:
    msg = OutboundEmail(to_address=to, subject=subject, body=body, purpose=purpose,
                        simulated=True, status="stored")
    db.add(msg)
    db.flush()
    return msg
