"""Seed the core database with SYNTHETIC demo data.

    python scripts/seed.py

- Requires a migrated database (alembic upgrade head) and a configured .env.
- Creates the first admin from AGENTSMIND_ADMIN_* if no users exist.
- Creates one demo user per department role. Passwords are random, printed once,
  and written to data/seed_credentials.txt (gitignored). Nothing is hard-coded.
- Safe to re-run: existing emails and candidates are skipped.
- All names and emails are invented (example.com is a reserved domain).
"""
from __future__ import annotations

import os
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from agentsmind.auth.service import bootstrap_first_admin, create_user  # noqa: E402
from agentsmind.db.models import Candidate, User  # noqa: E402
from agentsmind.db.session import SessionLocal  # noqa: E402

DEMO_USERS = [
    ("hira.siddiqui@example.com", "Hira Siddiqui", ["hr"]),
    ("bilal.qureshi@example.com", "Bilal Qureshi", ["it"]),
    ("sana.malik@example.com", "Sana Malik", ["finance"]),
    ("omar.farooq@example.com", "Omar Farooq", ["employee"]),
]

DEMO_CANDIDATES = [
    ("Zara Hussain", "zara.hussain@example.com", "Python Developer", "new"),
    ("Danish Iqbal", "danish.iqbal@example.com", "Python Developer", "screened"),
    ("Maryam Aslam", "maryam.aslam@example.com", "Accounts Officer", "shortlisted"),
    ("Hamza Tariq", "hamza.tariq@example.com", "IT Support Engineer", "interview"),
    ("Noor Fatima", "noor.fatima@example.com", "HR Generalist", "rejected"),
]


def _password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4))


def main() -> int:
    created: list[tuple[str, str, str]] = []
    with SessionLocal() as db:
        admin = bootstrap_first_admin(db)
        if admin:
            print(f"Created first admin {admin.email} (password from AGENTSMIND_ADMIN_PASSWORD).")
        for email, name, roles in DEMO_USERS:
            if db.scalar(select(User).where(User.email == email)):
                print(f"skip user {email} (exists)")
                continue
            pw = _password()
            create_user(db, email=email, full_name=name, password=pw, roles=roles)
            created.append((email, ",".join(roles), pw))
        for name, email, title, stage in DEMO_CANDIDATES:
            if db.scalar(select(Candidate).where(Candidate.email == email)):
                continue
            db.add(Candidate(full_name=name, email=email, job_title=title, stage=stage,
                             notes="Synthetic demo record."))
        db.commit()
        n_users = len(db.scalars(select(User)).all())
        n_cands = len(db.scalars(select(Candidate)).all())

    if created:
        # AGENTSMIND_SEED_CREDENTIALS lets the phase gate keep a throwaway database's
        # passwords out of the real data/seed_credentials.txt.
        out = Path(os.environ.get("AGENTSMIND_SEED_CREDENTIALS") or ROOT / "data" / "seed_credentials.txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as f:
            for email, roles, pw in created:
                f.write(f"{email}\t{roles}\t{pw}\n")
        print(f"\nDemo users (shown once; also appended to {out}):")
        for email, roles, pw in created:
            print(f"  {email:32} {roles:10} {pw}")
    print(f"\nSeed complete: {n_users} users, {n_cands} candidates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
