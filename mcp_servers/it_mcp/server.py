"""it-mcp: MCP tools over the AgentsMind IT Helpdesk REST API.

Run from the repo root:
    python -m mcp_servers.it_mcp.server
Environment: IT_MCP_TOKEN (required), IT_MCP_PORT (8102), IT_PORTAL_URL, IT_PORTAL_API_KEY.
"""
from __future__ import annotations

from typing import Annotated, Literal

from mcp_types import ToolAnnotations
from pydantic import BaseModel, EmailStr, Field

from mcp_servers.common import PortalClient, make_server, run, setting

INSTRUCTIONS = (
    "Tools for IT complaint tickets in the IT Helpdesk. it_create_ticket raises a new complaint and returns the "
    "ticket number and a confirmation link to show the user. Status changes follow the workflow "
    "open -> in_progress -> resolved -> closed (resolved can be reopened; closed is final)."
)

server, CFG = make_server(name="it-mcp", title="AgentsMind IT Helpdesk tools", instructions=INSTRUCTIONS,
                          prefix="IT", default_port=8102)
portal = PortalClient(
    name="IT Helpdesk", base_url=setting("IT_PORTAL_URL", "http://127.0.0.1:8202"),
    api_key=setting("IT_PORTAL_API_KEY", required=True, min_len=24),
    start_hint="Start it with scripts\\win\\run_all.ps1 or: uvicorn it_portal.app:create_app --factory "
               "--app-dir external_systems --port 8202",
)

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE_NONIDEM = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

Category = Literal["network", "hardware", "software", "account", "email", "printer", "other"]
Priority = Literal["low", "medium", "high", "urgent"]
Status = Literal["open", "in_progress", "resolved", "closed"]
Department = Literal["Finance", "HR", "IT", "Operations", "Sales", "Marketing", "Engineering", "Administration"]
TicketNo = Annotated[str, Field(pattern=r"^ITK-\d{6}$", description="Ticket number, e.g. ITK-000123")]


class TicketComment(BaseModel):
    author: str
    body: str
    internal: bool
    created_at: str


class Ticket(BaseModel):
    number: str
    requester_name: str
    requester_email: str
    department: str
    category: str
    priority: str
    summary: str
    description: str
    status: str
    assignee: str
    source: str
    sla_due_at: str
    sla_breached: bool
    expected_response: str
    created_at: str
    updated_at: str
    comments: list[TicketComment] = []


class CreatedTicket(BaseModel):
    created: bool = Field(description="False when the idempotency key was already used; the original ticket is returned.")
    ticket: Ticket
    confirmation_url: str | None = Field(default=None, description="Link to the 'Complaint submitted' screen. "
                                                                   "Only returned when the ticket was created now.")
    tracking_url: str | None = None


class TicketsPage(BaseModel):
    items: list[Ticket]
    total: int
    page: int
    page_size: int
    pages: int


def _ticket(d: dict) -> Ticket:
    return Ticket(**{k: d[k] for k in Ticket.model_fields if k in d})


@server.tool(annotations=WRITE)
def it_create_ticket(
    requester_name: Annotated[str, Field(min_length=2, max_length=200)],
    requester_email: EmailStr,
    department: Department,
    category: Category,
    description: Annotated[str, Field(min_length=10, max_length=5000)],
    idempotency_key: Annotated[str, Field(min_length=8, max_length=100,
                                          description="Unique key; re-sending it never creates a second ticket.")],
    priority: Priority = "medium",
    summary: Annotated[str, Field(max_length=200)] = "",
) -> CreatedTicket:
    """Raise an IT complaint. Returns the ticket number and the confirmation link for the requester."""
    body = {"requester_name": requester_name, "requester_email": str(requester_email), "department": department,
            "category": category, "priority": priority, "summary": summary, "description": description}
    d = portal.write("POST", "/api/v1/tickets", body, idempotency_key=idempotency_key, actor=str(requester_email))
    return CreatedTicket(created=d["created"], ticket=_ticket(d["ticket"]), confirmation_url=d.get("confirmation_url"),
                         tracking_url=d.get("tracking_url"))


@server.tool(annotations=READ)
def it_get_ticket(number: TicketNo) -> Ticket:
    """Get one ticket with its status, SLA due time and comments."""
    return _ticket(portal.get(f"/api/v1/tickets/{number}"))


@server.tool(annotations=READ)
def it_list_tickets(
    status: Status | None = None,
    priority: Priority | None = None,
    category: Category | None = None,
    query: Annotated[str | None, Field(max_length=100, description="Text or ticket number")] = None,
    requester_email: EmailStr | None = None,
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=100)] = 25,
) -> TicketsPage:
    """List tickets, newest first, with optional filters."""
    d = portal.get("/api/v1/tickets", {"status": status, "priority": priority, "category": category, "q": query,
                                       "requester_email": str(requester_email) if requester_email else None,
                                       "page": page, "page_size": page_size})
    return TicketsPage(items=[_ticket(t) for t in d["items"]], total=d["total"], page=d["page"],
                       page_size=d["page_size"], pages=d["pages"])


@server.tool(annotations=WRITE)
def it_update_ticket_status(
    number: TicketNo,
    status: Status,
    comment: Annotated[str, Field(max_length=5000, description="Message for the requester (optional)")] = "",
    actor: Annotated[str, Field(max_length=120, description="Email of the IT staff member")] = "",
) -> Ticket:
    """Move a ticket along the workflow. Invalid moves are refused with the allowed next statuses."""
    return _ticket(portal.write("PATCH", f"/api/v1/tickets/{number}/status", {"status": status, "comment": comment},
                                actor=actor or None))


@server.tool(annotations=WRITE_NONIDEM)
def it_add_comment(
    number: TicketNo,
    body: Annotated[str, Field(min_length=1, max_length=5000)],
    actor: Annotated[str, Field(max_length=120)] = "",
) -> Ticket:
    """Add a comment to an open ticket."""
    return _ticket(portal.write("POST", f"/api/v1/tickets/{number}/comments", {"body": body, "internal": False},
                                actor=actor or None))


if __name__ == "__main__":
    run(server, CFG)
