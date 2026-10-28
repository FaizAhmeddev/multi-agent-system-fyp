"""Finance Portal business logic, shared by the REST API and the web screens."""
from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AuditEvent, Payment, Person, from_minor, to_minor
from .schemas import PaymentIn, PaymentOut, PersonIn, PersonOut, PersonPatch

SORTABLE = {"full_name": Person.full_name, "department": Person.department, "job_title": Person.job_title,
            "monthly_salary": Person.salary_minor, "start_date": Person.start_date, "status": Person.status,
            "created_at": Person.created_at, "id": Person.id}


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def person_out(p: Person) -> PersonOut:
    return PersonOut(id=p.id, full_name=p.full_name, email=p.email, department=p.department,
                     job_title=p.job_title, employment_type=p.employment_type,
                     monthly_salary=from_minor(p.salary_minor), currency=p.currency, status=p.status,
                     start_date=p.start_date, notes=p.notes, created_via=p.created_via,
                     created_at=p.created_at.isoformat(), updated_at=p.updated_at.isoformat())


def payment_out(pm: Payment) -> PaymentOut:
    return PaymentOut(id=pm.id, person_id=pm.person_id, person_name=pm.person.full_name, month=pm.month,
                      amount=from_minor(pm.amount_minor), currency=pm.currency, status=pm.status,
                      paid_on=pm.paid_on, note=pm.note)


def _audit(db: Session, actor: str, action: str, target: str, detail: dict[str, Any] | None = None) -> None:
    db.add(AuditEvent(actor=actor, action=action, target=target, detail=detail or {}))


def query_people(db: Session, *, q: str = "", department: str = "", status: str = "", employment_type: str = "",
                 currency: str = "", sort: str = "full_name", order: str = "asc", page: int = 1,
                 page_size: int = 25) -> tuple[list[Person], int]:
    stmt = select(Person)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Person.full_name).like(like), func.lower(Person.email).like(like),
                              func.lower(Person.job_title).like(like)))
    if department:
        stmt = stmt.where(Person.department == department)
    if status:
        stmt = stmt.where(Person.status == status)
    if employment_type:
        stmt = stmt.where(Person.employment_type == employment_type)
    if currency:
        stmt = stmt.where(Person.currency == currency)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SORTABLE.get(sort, Person.full_name)
    stmt = stmt.order_by(col.desc() if order == "desc" else col.asc(), Person.id)
    if page_size:
        stmt = stmt.offset((max(page, 1) - 1) * page_size).limit(page_size)
    return list(db.scalars(stmt)), total


def get_person(db: Session, person_id: int) -> Person:
    p = db.get(Person, person_id)
    if p is None:
        raise ServiceError(404, "not_found", f"No person with id {person_id}.")
    return p


def create_person(db: Session, data: PersonIn, *, actor: str, via: str = "portal",
                  idempotency_key: str | None = None) -> tuple[Person, bool]:
    """Returns (person, created). A repeated idempotency key returns the original record."""
    if idempotency_key:
        existing = db.scalar(select(Person).where(Person.idempotency_key == idempotency_key))
        if existing is not None:
            return existing, False
    email = str(data.email).lower()
    if db.scalar(select(Person.id).where(func.lower(Person.email) == email)):
        raise ServiceError(409, "duplicate_email", f"A person with email {email} already exists.")
    p = Person(full_name=data.full_name, email=email, department=data.department, job_title=data.job_title,
               employment_type=data.employment_type, salary_minor=to_minor(data.monthly_salary),
               currency=data.currency, status=data.status, start_date=data.start_date, notes=data.notes,
               idempotency_key=idempotency_key, created_via=via)
    db.add(p)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = db.scalar(select(Person).where(Person.idempotency_key == idempotency_key))
            if existing is not None:
                return existing, False
        raise ServiceError(409, "duplicate_email", f"A person with email {email} already exists.") from None
    _audit(db, actor, "person.create", f"person:{p.id}", {"email": email, "via": via})
    db.commit()
    return p, True


def update_person(db: Session, person_id: int, patch: PersonPatch, *, actor: str) -> Person:
    p = get_person(db, person_id)
    changes = patch.model_dump(exclude_unset=True)
    if "email" in changes and changes["email"]:
        email = str(changes["email"]).lower()
        clash = db.scalar(select(Person.id).where(func.lower(Person.email) == email, Person.id != p.id))
        if clash:
            raise ServiceError(409, "duplicate_email", f"A person with email {email} already exists.")
        changes["email"] = email
    before = person_out(p).model_dump(mode="json")
    for k, v in changes.items():
        if v is None:
            continue
        if k == "monthly_salary":
            p.salary_minor = to_minor(v)
        elif k in ("full_name", "job_title"):
            setattr(p, k, " ".join(str(v).split()))
        else:
            setattr(p, k, v)
    db.flush()
    after = person_out(p).model_dump(mode="json")
    diff = {k: {"from": before[k], "to": after[k]} for k in after if before.get(k) != after[k] and k != "updated_at"}
    _audit(db, actor, "person.update", f"person:{p.id}", diff)
    db.commit()
    return p


def delete_person(db: Session, person_id: int, *, actor: str) -> dict[str, Any]:
    p = get_person(db, person_id)
    info = {"id": p.id, "full_name": p.full_name, "email": p.email, "payments_deleted": len(p.payments)}
    db.delete(p)
    _audit(db, actor, "person.delete", f"person:{person_id}", info)
    db.commit()
    return info


def summary(db: Session) -> dict[str, Any]:
    """Totals and counts, computed in SQL. Money is returned as exact decimal strings."""
    by_status = dict(db.execute(select(Person.status, func.count(Person.id)).group_by(Person.status)).all())
    payroll = [
        {"currency": cur, "active_people": n, "total_monthly_payroll": from_minor(total or 0)}
        for cur, n, total in db.execute(
            select(Person.currency, func.count(Person.id), func.sum(Person.salary_minor))
            .where(Person.status == "active").group_by(Person.currency).order_by(Person.currency))
    ]
    by_dept = [
        {"department": d, "active_people": n, "currency": cur, "total_monthly_payroll": from_minor(total or 0)}
        for d, cur, n, total in db.execute(
            select(Person.department, Person.currency, func.count(Person.id), func.sum(Person.salary_minor))
            .where(Person.status == "active").group_by(Person.department, Person.currency)
            .order_by(Person.department, Person.currency))
    ]
    pay = [
        {"status": st, "count": n, "currency": cur, "total": from_minor(total or 0)}
        for st, cur, n, total in db.execute(
            select(Payment.status, Payment.currency, func.count(Payment.id), func.sum(Payment.amount_minor))
            .group_by(Payment.status, Payment.currency).order_by(Payment.status, Payment.currency))
    ]
    return {"people_total": sum(by_status.values()), "people_active": by_status.get("active", 0),
            "people_inactive": by_status.get("inactive", 0), "payroll_by_currency": payroll,
            "payroll_by_department": by_dept, "payments_by_status": pay,
            "computed_by": "SQL aggregate over the people table (status = active)"}


def query_payments(db: Session, *, person_id: int | None = None, month: str = "", status: str = "", page: int = 1,
                   page_size: int = 25) -> tuple[list[Payment], int]:
    stmt = select(Payment).join(Person)
    if person_id:
        stmt = stmt.where(Payment.person_id == person_id)
    if month:
        stmt = stmt.where(Payment.month == month)
    if status:
        stmt = stmt.where(Payment.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(Payment.month.desc(), Person.full_name).offset((page - 1) * page_size).limit(page_size)
    return list(db.scalars(stmt)), total


def add_payment(db: Session, person_id: int, data: PaymentIn, *, actor: str) -> Payment:
    p = get_person(db, person_id)
    if db.scalar(select(Payment.id).where(Payment.person_id == p.id, Payment.month == data.month)):
        raise ServiceError(409, "duplicate_payment", f"{p.full_name} already has a payment for {data.month}.")
    pm = Payment(person_id=p.id, month=data.month, amount_minor=to_minor(data.amount), currency=p.currency,
                 status=data.status, paid_on=data.paid_on, note=data.note)
    db.add(pm)
    db.flush()
    _audit(db, actor, "payment.create", f"payment:{pm.id}", {"person_id": p.id, "month": data.month})
    db.commit()
    return pm


CSV_FIELDS = ["id", "full_name", "email", "department", "job_title", "employment_type", "monthly_salary",
              "currency", "status", "start_date", "notes"]


def people_csv(rows: list[Person]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    for p in rows:
        d = person_out(p).model_dump(mode="json")
        # Neutralise spreadsheet formula injection in free-text fields.
        for k in ("full_name", "job_title", "notes", "email"):
            if str(d[k])[:1] in ("=", "+", "-", "@"):
                d[k] = "'" + str(d[k])
        w.writerow(d)
    return buf.getvalue()
