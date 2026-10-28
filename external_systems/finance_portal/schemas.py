from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import CURRENCIES, DEPARTMENTS, EMPLOYMENT_TYPES

EmploymentType = Literal["full_time", "part_time", "contract", "intern"]
Currency = Literal["PKR", "USD", "EUR", "GBP", "AED"]
Status = Literal["active", "inactive"]
PaymentStatus = Literal["pending", "paid", "failed"]

assert set(EmploymentType.__args__) == set(EMPLOYMENT_TYPES)
assert set(Currency.__args__) == set(CURRENCIES)


def _clean(s: str) -> str:
    return " ".join((s or "").split())


def canonical_department(v: str) -> str:
    v = _clean(v)
    for d in DEPARTMENTS:
        if d.lower() == v.lower():
            return d
    raise ValueError(f"must be one of: {', '.join(DEPARTMENTS)}")


class PersonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    department: str = Field(min_length=2, max_length=80)
    job_title: str = Field(min_length=2, max_length=150)
    employment_type: EmploymentType = "full_time"
    monthly_salary: Decimal = Field(ge=0, le=Decimal("99999999.99"), max_digits=12, decimal_places=2)
    currency: Currency = "PKR"
    status: Status = "active"
    start_date: date
    notes: str = Field(default="", max_length=2000)

    @field_validator("full_name", "department", "job_title")
    @classmethod
    def _norm(cls, v: str) -> str:
        v = _clean(v)
        if len(v) < 2:
            raise ValueError("must be at least 2 characters")
        return v

    @field_validator("department")
    @classmethod
    def _dept(cls, v: str) -> str:
        return canonical_department(v)


class PersonPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    department: str | None = Field(default=None, min_length=2, max_length=80)
    job_title: str | None = Field(default=None, min_length=2, max_length=150)
    employment_type: EmploymentType | None = None
    monthly_salary: Decimal | None = Field(default=None, ge=0, le=Decimal("99999999.99"), max_digits=12,
                                           decimal_places=2)
    currency: Currency | None = None
    status: Status | None = None
    start_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("department")
    @classmethod
    def _dept(cls, v: str | None) -> str | None:
        return None if v is None else canonical_department(v)


class PersonOut(BaseModel):
    id: int
    full_name: str
    email: str
    department: str
    job_title: str
    employment_type: str
    monthly_salary: str  # decimal as string, exact
    currency: str
    status: str
    start_date: date
    notes: str
    created_via: str
    created_at: str
    updated_at: str


class PaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    amount: Decimal = Field(ge=0, le=Decimal("99999999.99"), max_digits=12, decimal_places=2)
    status: PaymentStatus = "pending"
    paid_on: date | None = None
    note: str = Field(default="", max_length=300)


class PaymentOut(BaseModel):
    id: int
    person_id: int
    person_name: str
    month: str
    amount: str
    currency: str
    status: str
    paid_on: date | None
    note: str
