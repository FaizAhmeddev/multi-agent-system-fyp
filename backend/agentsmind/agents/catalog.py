"""Tool catalog and per-agent allow-lists (least privilege).

The catalog lists every tool the core may call. Implementations live behind MCP
servers (Phase 2); this module only declares names, risk levels and who may use
them, so the gateway can refuse calls before anything leaves the process.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..rbac import STAFF_ROLES

READ, WRITE, DESTRUCTIVE = "read", "write", "destructive"
ALL_STAFF = STAFF_ROLES
DOC_ROLES = frozenset({"hr", "it", "finance"})
ADMIN_ONLY: frozenset[str] = frozenset()  # admin passes every role check


@dataclass(frozen=True)
class ToolSpec:
    name: str
    server: str
    risk: str  # read | write | destructive
    roles: frozenset[str]
    description: str


def _t(name, server, risk, roles, description):
    return ToolSpec(name, server, risk, frozenset(roles), description)


TOOLS: dict[str, ToolSpec] = {t.name: t for t in (
    # finance-mcp (Finance Portal)
    _t("finance_list_people", "finance-mcp", READ, {"finance"}, "List people records."),
    _t("finance_get_person", "finance-mcp", READ, {"finance"}, "Get one person record."),
    _t("finance_search_people", "finance-mcp", READ, {"finance"}, "Search people records."),
    _t("finance_summary", "finance-mcp", READ, {"finance"}, "Payroll totals and counts computed by SQL."),
    _t("finance_list_payments", "finance-mcp", READ, {"finance"}, "List payment records."),
    _t("finance_create_person", "finance-mcp", WRITE, {"finance"}, "Create a person record."),
    _t("finance_update_person", "finance-mcp", WRITE, {"finance"}, "Update a person record."),
    _t("finance_delete_person", "finance-mcp", DESTRUCTIVE, {"finance"}, "Delete a person record."),
    # it-mcp (IT Helpdesk)
    _t("it_create_ticket", "it-mcp", WRITE, ALL_STAFF, "Raise an IT complaint ticket."),
    _t("it_get_ticket", "it-mcp", READ, ALL_STAFF, "Get one ticket (non-IT users: own tickets only)."),
    _t("it_list_tickets", "it-mcp", READ, ALL_STAFF, "List tickets (non-IT users: own tickets only)."),
    _t("it_update_ticket_status", "it-mcp", WRITE, {"it"}, "Change ticket status."),
    _t("it_add_comment", "it-mcp", WRITE, ALL_STAFF, "Comment on a ticket (non-IT users: own tickets only)."),
    # calendar-mcp
    _t("calendar_list_events", "calendar-mcp", READ, ALL_STAFF, "List calendar events."),
    _t("calendar_check_availability", "calendar-mcp", READ, ALL_STAFF, "Free/busy check."),
    _t("calendar_create_event", "calendar-mcp", WRITE, ALL_STAFF, "Create an event."),
    _t("calendar_update_event", "calendar-mcp", WRITE, ALL_STAFF, "Move or edit an event."),
    _t("calendar_cancel_event", "calendar-mcp", DESTRUCTIVE, ALL_STAFF, "Cancel an event."),
    # workspace-mcp (Drive, Gmail, system)
    _t("drive_list_files", "workspace-mcp", READ, DOC_ROLES, "List Drive files."),
    _t("drive_read_file", "workspace-mcp", READ, DOC_ROLES, "Read a Drive file."),
    _t("drive_search", "workspace-mcp", READ, DOC_ROLES, "Search Drive."),
    _t("gmail_read_inbox", "workspace-mcp", READ, ALL_STAFF, "Read recent inbox messages."),
    _t("gmail_send_email", "workspace-mcp", WRITE, ALL_STAFF, "Send an email."),
    _t("queue_stats", "workspace-mcp", READ, ADMIN_ONLY, "Queue statistics."),
    _t("agent_status", "workspace-mcp", READ, ADMIN_ONLY, "Agent health."),
)}


# Which tools each agent may ever call. Anything not listed is denied in code.
AGENT_TOOLS: dict[str, frozenset[str]] = {
    "hr": frozenset({"drive_search", "drive_read_file", "drive_list_files", "gmail_read_inbox",
                     "gmail_send_email", "calendar_check_availability", "calendar_create_event"}),
    "it": frozenset({"it_create_ticket", "it_get_ticket", "it_list_tickets", "it_update_ticket_status",
                     "it_add_comment"}),
    "finance": frozenset({"finance_list_people", "finance_get_person", "finance_search_people",
                          "finance_summary", "finance_list_payments", "finance_create_person",
                          "finance_update_person", "finance_delete_person"}),
    "documents": frozenset({"drive_list_files", "drive_read_file", "drive_search"}),
    "email": frozenset({"gmail_read_inbox", "gmail_send_email"}),
    "calendar": frozenset({"calendar_list_events", "calendar_check_availability", "calendar_create_event",
                           "calendar_update_event", "calendar_cancel_event"}),
    "orchestrator": frozenset({"queue_stats", "agent_status"}),
}

assert all(t in TOOLS for tools in AGENT_TOOLS.values() for t in tools), "allow-list names an unknown tool"
