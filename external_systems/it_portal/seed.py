"""Seed the IT Helpdesk with SYNTHETIC tickets.

    python external_systems/it_portal/seed.py

Safe to re-run (uses idempotency keys). All requesters are invented; emails use example.com.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from it_portal import service as svc  # noqa: E402
from it_portal.app import load_config  # noqa: E402
from it_portal.models import Base, Ticket  # noqa: E402
from portal_common.core import make_sqlite_engine  # noqa: E402

TICKETS = [
    ("Omar Farooq", "Operations", "printer", "low", "Printer on floor 2 shows offline",
     "The shared printer near the operations desk shows offline since this morning.", "open"),
    ("Mehwish Khan", "Sales", "email", "medium", "Outlook keeps asking for password",
     "Outlook prompts for my password every few minutes after the update yesterday.", "in_progress"),
    ("Zainab Ali", "Engineering", "software", "high", "VPN client fails to install",
     "The VPN installer stops at 80 percent with error 1603 on my laptop.", "open"),
    ("Nida Hassan", "Administration", "hardware", "medium", "Monitor flickers",
     "My second monitor flickers every few seconds. I tried another cable.", "resolved"),
]


def main() -> int:
    cfg = load_config()
    engine = make_sqlite_engine(cfg["db_url"])
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    added = 0
    for i, (name, dept, cat, prio, summary, desc, status) in enumerate(TICKETS, start=1):
        email = name.lower().replace(" ", ".") + "@example.com"
        data = svc.TicketIn(requester_name=name, requester_email=email, department=dept, category=cat, priority=prio,
                            summary=summary, description=desc)
        t, _tok, created = svc.create_ticket(db, data, actor=email, source="portal", idempotency_key=f"seed-{i}")
        if created:
            added += 1
            if status in ("in_progress", "resolved"):
                svc.change_status(db, t.number, svc.StatusChangeIn(status="in_progress", comment="Looking into it."),
                                  actor="it.admin@example.com")
            if status == "resolved":
                svc.change_status(db, t.number, svc.StatusChangeIn(status="resolved", comment="Replaced the cable."),
                                  actor="it.admin@example.com")
    total = db.scalar(select(func.count(Ticket.id)))
    db.close()
    print(f"IT Helpdesk seed: {added} tickets added, {total} in total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
