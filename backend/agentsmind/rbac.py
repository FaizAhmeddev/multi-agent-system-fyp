"""Departments, roles and who may use what. Enforced in code, never only in prompts."""
from __future__ import annotations

from dataclasses import dataclass

STAFF_ROLES = frozenset({"hr", "it", "finance", "employee"})


@dataclass(frozen=True)
class Department:
    slug: str
    name: str
    description: str
    roles: frozenset[str]  # roles that may open the department workspace (admin always may)


DEPARTMENTS: dict[str, Department] = {
    d.slug: d
    for d in (
        Department("hr", "HR", "Candidates, CV screening, onboarding and HR policy.", frozenset({"hr"})),
        Department("it", "IT", "Support tickets, status workflow and SLAs.", frozenset({"it"})),
        Department("finance", "Finance", "People records, payroll summary and payments.", frozenset({"finance"})),
        Department("documents", "Documents", "Search, summarize and ask questions about company files.",
                   frozenset({"hr", "it", "finance"})),
        Department("communications", "Communications", "Inbox, reply drafts and calendar.", STAFF_ROLES),
    )
}


def has_any(user_roles: list[str] | tuple[str, ...] | set[str], allowed: frozenset[str]) -> bool:
    roles = set(user_roles)
    return "admin" in roles or bool(roles & allowed)


def can_open_department(user_roles, slug: str) -> bool:
    d = DEPARTMENTS.get(slug)
    return d is not None and has_any(user_roles, d.roles)


def department_denial_reason(slug: str) -> str:
    d = DEPARTMENTS[slug]
    names = ", ".join(sorted(d.roles))
    return f"{d.name} is available to these roles: {names}. Ask an administrator if you need access."
