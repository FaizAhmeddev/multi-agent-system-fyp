"""Seed the Finance Portal with SYNTHETIC people and payments.

    python external_systems/finance_portal/seed.py

Safe to re-run: existing emails are skipped. All people are invented; emails use the
reserved example.com domain.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from finance_portal.app import load_config  # noqa: E402
from finance_portal.models import Base, Payment, Person, to_minor  # noqa: E402
from portal_common.core import make_sqlite_engine  # noqa: E402

PEOPLE = [
    # name, department, title, type, salary, currency, status, start
    ("Ahmed Raza", "Finance", "Senior Accountant", "full_time", "185000", "PKR", "active", "2023-03-01"),
    ("Sana Malik", "Finance", "Finance Manager", "full_time", "320000", "PKR", "active", "2021-07-15"),
    ("Bilal Qureshi", "IT", "IT Support Engineer", "full_time", "160000", "PKR", "active", "2022-01-10"),
    ("Hira Siddiqui", "HR", "HR Generalist", "full_time", "150000", "PKR", "active", "2022-09-05"),
    ("Omar Farooq", "Operations", "Operations Coordinator", "full_time", "120000", "PKR", "active", "2024-02-01"),
    ("Zainab Ali", "Engineering", "Backend Developer", "full_time", "260000", "PKR", "active", "2023-11-20"),
    ("Usman Tariq", "Engineering", "Frontend Developer", "full_time", "240000", "PKR", "active", "2024-04-08"),
    ("Mehwish Khan", "Sales", "Account Executive", "full_time", "140000", "PKR", "active", "2023-06-12"),
    ("Faisal Javed", "Marketing", "Content Lead", "part_time", "90000", "PKR", "active", "2024-08-01"),
    ("Nida Hassan", "Administration", "Office Administrator", "full_time", "110000", "PKR", "active", "2020-05-18"),
    ("Kamran Sheikh", "Engineering", "DevOps Contractor", "contract", "2500", "USD", "active", "2025-01-06"),
    ("Ayaan Mirza", "Engineering", "Software Intern", "intern", "45000", "PKR", "active", "2026-06-01"),
    ("Rabia Noor", "Sales", "Sales Manager", "full_time", "280000", "PKR", "inactive", "2019-10-01"),
    ("Saad Iqbal", "IT", "Network Administrator", "full_time", "175000", "PKR", "active", "2021-03-22"),
]
MONTHS = ("2026-07", "2026-08", "2026-09")


def slug_email(name: str) -> str:
    return name.lower().replace(" ", ".") + "@example.com"


def main() -> int:
    cfg = load_config()
    engine = make_sqlite_engine(cfg["db_url"])
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    added = 0
    for name, dept, title, etype, salary, cur, status, start in PEOPLE:
        email = slug_email(name)
        if db.scalar(select(Person.id).where(Person.email == email)):
            continue
        p = Person(full_name=name, email=email, department=dept, job_title=title, employment_type=etype,
                   salary_minor=to_minor(salary), currency=cur, status=status, start_date=date.fromisoformat(start),
                   notes="Synthetic demo record.", created_via="portal")
        db.add(p)
        db.flush()
        if status == "active":
            for i, m in enumerate(MONTHS):
                db.add(Payment(person_id=p.id, month=m, amount_minor=p.salary_minor, currency=cur,
                               status="paid" if i < 2 else "pending",
                               paid_on=date.fromisoformat(m + "-28") if i < 2 else None, note=""))
        added += 1
    db.commit()
    total = len(db.scalars(select(Person)).all())
    db.close()
    print(f"Finance Portal seed: {added} people added, {total} in total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
