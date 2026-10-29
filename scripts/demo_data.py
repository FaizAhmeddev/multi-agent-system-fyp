"""Sample (synthetic) data on or off, for the AgentsMind core.

    python scripts/demo_data.py --auto    what main.py runs: follows DEMO_MODE in .env, once
    python scripts/demo_data.py --purge   remove the sample data now
    python scripts/demo_data.py --seed    add the sample data now (demo users, candidates, calendar)

Sample records are recognised by their reserved example.com / example.net email domains and
the "Synthetic demo record." note; nothing else is touched. Your admin account and your
real records are never removed. The external systems clean their own sample data
(external_systems/main.py does the same for the Finance Portal and IT Helpdesk).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"
MARK_PURGED = DATA / ".demo_purged"
MARK_SEEDED = DATA / ".demo_seeded"
SAMPLE_DOMAINS = ("@example.com", "@example.net", "@example.org")


def _env_demo() -> bool:
    from mcp_servers.common import load_env

    load_env()
    return (os.environ.get("DEMO_MODE") or "false").strip().lower() in ("1", "true", "yes")


def purge() -> dict[str, int]:
    from sqlalchemy import or_, select

    from agentsmind.db.hr_models import Employee
    from agentsmind.db.models import Candidate, CVRecord, User
    from agentsmind.db.session import SessionLocal
    from agentsmind.settings import get_settings

    admin = (get_settings().agentsmind_admin_email or "").lower()
    out = {"users": 0, "candidates": 0, "employees": 0}
    with SessionLocal() as db:
        like = or_(*[User.email.like(f"%{d}") for d in SAMPLE_DOMAINS])
        for u in db.scalars(select(User).where(like)):
            if u.email.lower() == admin or "admin" in u.role_names:
                continue
            db.delete(u)
            out["users"] += 1
        clike = or_(*[Candidate.email.like(f"%{d}") for d in SAMPLE_DOMAINS], Candidate.notes == "Synthetic demo record.")
        for c in db.scalars(select(Candidate).where(clike)):
            for r in db.scalars(select(CVRecord).where(CVRecord.candidate_id == c.id)):
                db.delete(r)
            db.delete(c)
            out["candidates"] += 1
        elike = or_(*[Employee.email.like(f"%{d}") for d in SAMPLE_DOMAINS])
        for e in db.scalars(select(Employee).where(elike)):
            db.delete(e)
            out["employees"] += 1
        db.commit()
    cal = DATA / "calendar_sandbox.db"
    if cal.exists():
        try:
            cal.unlink()
        except OSError:
            pass  # in use by a running calendar-mcp; it is not used when DEMO_MODE=false anyway
    sc = DATA / "seed_credentials.txt"
    if sc.exists():
        sc.unlink()
    return out


def seed() -> None:
    import subprocess

    py = sys.executable
    subprocess.run([py, str(ROOT / "scripts" / "seed.py"), "--demo"], cwd=ROOT, check=False)  # noqa: S603
    subprocess.run([py, "-m", "mcp_servers.calendar_mcp.seed"], cwd=ROOT, check=False)  # noqa: S603


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--auto", action="store_true")
    g.add_argument("--purge", action="store_true")
    g.add_argument("--seed", action="store_true")
    a = ap.parse_args(argv)
    DATA.mkdir(exist_ok=True)
    if a.purge or (a.auto and not _env_demo() and not MARK_PURGED.exists()):
        out = purge()
        MARK_PURGED.write_text("sample data removed\n")
        MARK_SEEDED.unlink(missing_ok=True)
        print(f"Sample data removed: {out['users']} user(s), {out['candidates']} candidate(s), "
              f"{out['employees']} employee record(s).")
    elif a.seed or (a.auto and _env_demo() and not MARK_SEEDED.exists()):
        seed()
        MARK_SEEDED.write_text("sample data added\n")
        MARK_PURGED.unlink(missing_ok=True)
        print("Sample data added (DEMO_MODE=true).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
