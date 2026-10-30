"""finance-mcp: MCP tools over the AgentsMind Finance Portal REST API.

Run from the repo root:
    python -m mcp_servers.finance_mcp.server
Environment: FINANCE_MCP_TOKEN (required), FINANCE_MCP_PORT (8101), FINANCE_PORTAL_URL, FINANCE_PORTAL_API_KEY.

All money values are exact decimal strings. Totals come from the portal's SQL
aggregates (finance_summary); never compute them from listed rows.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from mcp_types import ToolAnnotations
from pydantic import BaseModel, EmailStr, Field

from mcp_servers.common import PortalClient, make_server, run, setting

INSTRUCTIONS = (
    "Tools for the company's people and payroll records in the Finance Portal. "
    "Use finance_summary for any total, count or payroll figure; do not add numbers yourself. "
    "Create, update and delete change real records and are only called after a human approved them."
)

server, CFG = make_server(name="finance-mcp", title="AgentsMind Finance Portal tools", instructions=INSTRUCTIONS,
                          prefix="FINANCE", default_port=8101)
portal = PortalClient(
    name="Finance Portal", base_url=setting("FINANCE_PORTAL_URL", "http://127.0.0.1:8201"),
    api_key=setting("FINANCE_PORTAL_API_KEY", required=True, min_len=24),
    start_hint="Start AgentsMind with main.py (it starts the portal too) or Start-External-Systems.bat, "
               "or: uvicorn finance_portal.app:create_app --factory "
               "--app-dir external_systems --port 8201",
)

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)

Department = Literal["Finance", "HR", "IT", "Operations", "Sales", "Marketing", "Engineering", "Administration"]
EmploymentType = Literal["full_time", "part_time", "contract", "intern"]
Currency = Literal["PKR", "USD", "EUR", "GBP", "AED"]
Status = Literal["active", "inactive"]
Money = Annotated[str, Field(pattern=r"^\d{1,8}(\.\d{1,2})?$", description="Amount as a decimal string, e.g. 150000.00")]
IdemKey = Annotated[str, Field(min_length=8, max_length=100,
                               description="Unique key for this request. Re-sending the same key never creates a "
                                           "second record.")]


class Person(BaseModel):
    id: int
    full_name: str
    email: str
    department: str
    job_title: str
    employment_type: str
    monthly_salary: str
    currency: str
    status: str
    start_date: date
    notes: str
    created_via: str
    created_at: str
    updated_at: str


class PeoplePage(BaseModel):
    items: list[Person]
    total: int
    page: int
    page_size: int
    pages: int


class CreateResult(BaseModel):
    created: bool = Field(description="False when the idempotency key was already used; the original record is returned.")
    person: Person


class DeleteResult(BaseModel):
    id: int
    full_name: str
    email: str
    payments_deleted: int


class CurrencyTotal(BaseModel):
    currency: str
    active_people: int
    total_monthly_payroll: str


class DepartmentTotal(BaseModel):
    department: str
    currency: str
    active_people: int
    total_monthly_payroll: str


class PaymentTotal(BaseModel):
    status: str
    currency: str
    count: int
    total: str


class Summary(BaseModel):
    people_total: int
    people_active: int
    people_inactive: int
    payroll_by_currency: list[CurrencyTotal]
    payroll_by_department: list[DepartmentTotal]
    payments_by_status: list[PaymentTotal]
    computed_by: str
    source_tool: str = "finance_summary"


class Payment(BaseModel):
    id: int
    person_id: int
    person_name: str
    month: str
    amount: str
    currency: str
    status: str
    paid_on: date | None
    note: str


class PaymentsPage(BaseModel):
    items: list[Payment]
    total: int
    page: int
    page_size: int
    pages: int


SortField = Literal["full_name", "department", "job_title", "monthly_salary", "start_date", "status", "created_at"]


@server.tool(annotations=READ)
def finance_list_people(
    page: Annotated[int, Field(ge=1, description="Page number, from 1")] = 1,
    page_size: Annotated[int, Field(ge=1, le=100)] = 25,
    department: Department | None = None,
    status: Status | None = None,
    employment_type: EmploymentType | None = None,
    sort: SortField = "full_name",
    order: Literal["asc", "desc"] = "asc",
) -> PeoplePage:
    """List people records, one page at a time, with optional filters and sorting."""
    d = portal.get("/api/v1/people", {"page": page, "page_size": page_size, "department": department, "status": status,
                                      "employment_type": employment_type, "sort": sort, "order": order})
    return PeoplePage(**{k: d[k] for k in ("items", "total", "page", "page_size", "pages")})


@server.tool(annotations=READ)
def finance_get_person(person_id: Annotated[int, Field(ge=1)]) -> Person:
    """Get one person record by its numeric id."""
    return Person(**portal.get(f"/api/v1/people/{person_id}"))


@server.tool(annotations=READ)
def finance_search_people(
    query: Annotated[str, Field(min_length=2, max_length=100, description="Part of a name, email or job title")],
    limit: Annotated[int, Field(ge=1, le=50)] = 10,
) -> PeoplePage:
    """Find people by name, email or job title. Use this to resolve a name to a person id before update or delete."""
    d = portal.get("/api/v1/people", {"q": query, "page": 1, "page_size": limit})
    return PeoplePage(**{k: d[k] for k in ("items", "total", "page", "page_size", "pages")})


@server.tool(annotations=WRITE)
def finance_create_person(
    full_name: Annotated[str, Field(min_length=2, max_length=200)],
    email: EmailStr,
    department: Department,
    job_title: Annotated[str, Field(min_length=2, max_length=150)],
    monthly_salary: Money,
    start_date: Annotated[date, Field(description="ISO date, e.g. 2026-12-01")],
    idempotency_key: IdemKey,
    employment_type: EmploymentType = "full_time",
    currency: Currency = "PKR",
    status: Status = "active",
    notes: Annotated[str, Field(max_length=2000)] = "",
    actor: Annotated[str, Field(max_length=120, description="Email of the approving AgentsMind user")] = "",
) -> CreateResult:
    """Create a person record in the Finance Portal. Only call after a human approved the exact fields."""
    body = {"full_name": full_name, "email": str(email), "department": department, "job_title": job_title,
            "employment_type": employment_type, "monthly_salary": monthly_salary, "currency": currency,
            "status": status, "start_date": start_date.isoformat(), "notes": notes}
    d = portal.write("POST", "/api/v1/people", body, idempotency_key=idempotency_key, actor=actor or None)
    return CreateResult(created=d["created"], person=Person(**d["person"]))


@server.tool(annotations=WRITE)
def finance_update_person(
    person_id: Annotated[int, Field(ge=1)],
    idempotency_key: IdemKey,
    full_name: Annotated[str | None, Field(min_length=2, max_length=200)] = None,
    email: EmailStr | None = None,
    department: Department | None = None,
    job_title: Annotated[str | None, Field(min_length=2, max_length=150)] = None,
    employment_type: EmploymentType | None = None,
    monthly_salary: Money | None = None,
    currency: Currency | None = None,
    status: Status | None = None,
    start_date: date | None = None,
    notes: Annotated[str | None, Field(max_length=2000)] = None,
    actor: Annotated[str, Field(max_length=120)] = "",
) -> Person:
    """Change fields of an existing person. Only the fields you pass are changed."""
    body = {k: v for k, v in {
        "full_name": full_name, "email": str(email) if email else None, "department": department,
        "job_title": job_title, "employment_type": employment_type, "monthly_salary": monthly_salary,
        "currency": currency, "status": status, "start_date": start_date.isoformat() if start_date else None,
        "notes": notes}.items() if v is not None}
    if not body:
        from mcp.server.mcpserver.exceptions import ToolError

        raise ToolError("Nothing to update: pass at least one field.")
    return Person(**portal.write("PATCH", f"/api/v1/people/{person_id}", body, idempotency_key=idempotency_key,
                                 actor=actor or None))


@server.tool(annotations=DESTRUCTIVE)
def finance_delete_person(
    person_id: Annotated[int, Field(ge=1)],
    idempotency_key: IdemKey,
    actor: Annotated[str, Field(max_length=120)] = "",
) -> DeleteResult:
    """Permanently delete a person record and its payments. Only after an explicit human confirmation."""
    d = portal.write("DELETE", f"/api/v1/people/{person_id}", idempotency_key=idempotency_key, actor=actor or None)
    return DeleteResult(**d["deleted"])


@server.tool(annotations=READ)
def finance_summary() -> Summary:
    """Headcount and total monthly payroll (per currency and department) computed by SQL in the Finance Portal.
    Use this for every total or count question."""
    return Summary(**portal.get("/api/v1/summary"))


@server.tool(annotations=READ)
def finance_list_payments(
    person_id: Annotated[int | None, Field(ge=1)] = None,
    month: Annotated[str | None, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")] = None,
    status: Literal["pending", "paid", "failed"] | None = None,
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=100)] = 25,
) -> PaymentsPage:
    """List payment records, optionally for one person, month or status."""
    d = portal.get("/api/v1/payments", {"person_id": person_id, "month": month, "status": status, "page": page,
                                        "page_size": page_size})
    return PaymentsPage(**{k: d[k] for k in ("items", "total", "page", "page_size", "pages")})


# ---------------------------------------------------------------------------- payroll (used by HR automation)

class PayrollEnrolled(BaseModel):
    created: bool
    person: Person


@server.tool(annotations=WRITE)
def payroll_enroll_employee(
    full_name: Annotated[str, Field(min_length=2, max_length=200)],
    email: EmailStr,
    department: Department,
    job_title: Annotated[str, Field(min_length=2, max_length=150)],
    monthly_salary: Money,
    start_date: Annotated[date, Field(description="Joining date, ISO")],
    idempotency_key: IdemKey,
    employment_type: EmploymentType = "full_time",
    currency: Currency = "PKR",
    notes: Annotated[str, Field(max_length=2000)] = "",
    actor: Annotated[str, Field(max_length=120)] = "",
) -> PayrollEnrolled:
    """Add a new joiner to payroll (a person record in the Finance Portal). Only after HR approved it.
    A repeated idempotency key returns the original record instead of creating a second one."""
    body = {"full_name": full_name, "email": str(email), "department": department, "job_title": job_title,
            "employment_type": employment_type, "monthly_salary": monthly_salary, "currency": currency,
            "status": "active", "start_date": start_date.isoformat(), "notes": notes or "Added by AgentsMind HR"}
    d = portal.write("POST", "/api/v1/people", body, idempotency_key=idempotency_key, actor=actor or None)
    return PayrollEnrolled(created=d["created"], person=Person(**d["person"]))


@server.tool(annotations=WRITE)
def payroll_end_employment(
    person_id: Annotated[int, Field(ge=1)],
    idempotency_key: IdemKey,
    note: Annotated[str, Field(max_length=500)] = "",
    actor: Annotated[str, Field(max_length=120)] = "",
) -> Person:
    """Mark a leaver inactive in payroll (the record and its payments are kept). Only after HR approved it."""
    body: dict = {"status": "inactive"}
    if note:
        body["notes"] = note[:2000]
    return Person(**portal.write("PATCH", f"/api/v1/people/{person_id}", body, idempotency_key=idempotency_key,
                                 actor=actor or None))


class PaymentRecorded(BaseModel):
    recorded: bool = Field(description="False when this person already had a payment for the month")
    payment: Payment | None = None
    message: str = ""


@server.tool(annotations=WRITE)
def payroll_record_payment(
    person_id: Annotated[int, Field(ge=1)],
    month: Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
    amount: Money,
    idempotency_key: IdemKey,
    status: Literal["pending", "paid"] = "pending",
    note: Annotated[str, Field(max_length=300)] = "",
    actor: Annotated[str, Field(max_length=120)] = "",
) -> PaymentRecorded:
    """Record one employee's net pay for a month (from an approved AgentsMind payroll run).
    Safe to repeat: a second call for the same person and month records nothing."""
    from mcp.server.mcpserver.exceptions import ToolError

    try:
        d = portal.write("POST", f"/api/v1/people/{person_id}/payments",
                         {"month": month, "amount": amount, "status": status, "note": note or "AgentsMind payroll"},
                         idempotency_key=idempotency_key, actor=actor or None)
    except ToolError as exc:
        if "already has a payment" in str(exc):
            return PaymentRecorded(recorded=False, message=str(exc))
        raise
    return PaymentRecorded(recorded=True, payment=Payment(**d))


if __name__ == "__main__":
    run(server, CFG)
