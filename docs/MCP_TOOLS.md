# MCP tools

The core reaches the external systems only through these MCP servers. Every call passes through the core's tool gateway first (`backend/agentsmind/agents/gateway.py`), which enforces four things in code:

- **Allow-lists:** a tool runs only if it is on the calling agent's list.
- **Roles:** the user's role must allow the tool.
- **Approvals:** write and destructive tools need an approval first.
- **Logging:** every call is written to `tool_calls`.

All servers are built on the MCP Python SDK `mcp==2.3.0` (`MCPServer`, Streamable HTTP, endpoint `/mcp`).

## Servers

| Server | Default URL | Backed by | Token setting |
|---|---|---|---|
| finance-mcp | http://127.0.0.1:8101/mcp | Finance Portal REST API (`/api/v1`, X-API-Key) | `FINANCE_MCP_TOKEN` |
| it-mcp | http://127.0.0.1:8102/mcp | IT Helpdesk REST API (`/api/v1`, X-API-Key) | `IT_MCP_TOKEN` |
| calendar-mcp | Phase 3 | Google Calendar API, or a labeled sandbox | `CALENDAR_MCP_TOKEN` |
| workspace-mcp | Phase 3 | Gmail and Drive APIs, plus system tools | `WORKSPACE_MCP_TOKEN` |

Security, verified by tests in `tests/backend/test_mcp_integration.py` and a cloud run against the SDK:

- **Startup:** a server refuses to start without a token of 24 or more characters, and binds to 127.0.0.1 by default.
- **Bearer token:** every request needs `Authorization: Bearer <token>`. Without it the server returns 401 with an RFC 9728 `WWW-Authenticate` header.
- **DNS rebinding:** a request with a foreign `Host` header is answered with 421.
- **Portal calls:** these have a 3 s connect timeout and a 10 s read timeout. Reads are retried twice with backoff; writes are never retried.
- **Idempotency:** create, update and delete calls carry an `idempotency_key`. The portals store the key, so replaying it returns the original record and never creates a duplicate.

## Who may call what

The **Roles** column is enforced by the gateway. Admins pass every role check, but even an admin can only use a tool through an agent whose allow-list includes it.

| Tool | Server | Risk | Roles | Agents allowed |
|---|---|---|---|---|
| finance_list_people | finance-mcp | read | finance | finance |
| finance_get_person | finance-mcp | read | finance | finance |
| finance_search_people | finance-mcp | read | finance | finance |
| finance_summary | finance-mcp | read | finance | finance |
| finance_list_payments | finance-mcp | read | finance | finance |
| finance_create_person | finance-mcp | write (approval) | finance | finance |
| finance_update_person | finance-mcp | write (approval) | finance | finance |
| finance_delete_person | finance-mcp | destructive (approval and confirm) | finance | finance |
| it_create_ticket | it-mcp | write (approval) | all staff | it |
| it_get_ticket | it-mcp | read | all staff (own tickets only, outside IT) | it |
| it_list_tickets | it-mcp | read | all staff (own tickets only, outside IT) | it |
| it_update_ticket_status | it-mcp | write (approval) | it | it |
| it_add_comment | it-mcp | write (approval) | all staff (own tickets only, outside IT) | it |
| calendar_* | calendar-mcp | Phase 3 | all staff | calendar, hr (check availability and create only) |
| drive_* | workspace-mcp | read | hr, it, finance | documents, hr |
| gmail_read_inbox | workspace-mcp | read | all staff | email, hr |
| gmail_send_email | workspace-mcp | write (approval) | all staff | email, hr |
| queue_stats, agent_status | workspace-mcp | read | admin | orchestrator |

Notes on the table:

- **"Own tickets only":** the gateway adds `requester_email=<user>` to list calls. It also hides tickets that belong to someone else, reporting them as not found.
- **"(approval)":** an agent's call creates a pending approval. The tool runs only after `POST /api/approvals/{id}/approve`.
- **"(approval and confirm)":** destructive approvals also need `confirm=true`.
- **Workspace forms:** submissions from the workspace forms (`/api/finance/*`, `/api/it/*`) are the user's own action. They are stored as direct approvals made by that user, so the audit trail is the same either way.

## Tool reference

The full input and output JSON schemas come from the server itself: `tools/list`, or the smoke script below. Money is always an exact decimal string, and totals come only from `finance_summary`, which runs SQL in the portal.

finance-mcp:

- `finance_list_people(page=1, page_size=25, department?, status?, employment_type?, sort=full_name, order=asc)` returns a `PeoplePage`.
- `finance_get_person(person_id)` returns a `Person`.
- `finance_search_people(query, limit=10)` returns a `PeoplePage`. Use it to resolve a name to an id before an update or delete.
- `finance_create_person(full_name, email, department, job_title, monthly_salary, start_date, idempotency_key, employment_type=full_time, currency=PKR, status=active, notes="", actor="")` returns `{created, person}`.
- `finance_update_person(person_id, idempotency_key, <any fields>, actor="")` returns a `Person`.
- `finance_delete_person(person_id, idempotency_key, actor="")` returns `{id, full_name, email, payments_deleted}`.
- `finance_summary()` returns `{people_total, people_active, people_inactive, payroll_by_currency[], payroll_by_department[], payments_by_status[], computed_by, source_tool}`.
- `finance_list_payments(person_id?, month?, status?, page, page_size)` returns a `PaymentsPage`.

it-mcp:

- `it_create_ticket(requester_name, requester_email, department, category, description, idempotency_key, priority=medium, summary="")` returns `{created, ticket, confirmation_url, tracking_url}`. The confirmation link opens the IT Helpdesk "Complaint submitted" screen.
- `it_get_ticket(number)` returns a `Ticket`.
- `it_list_tickets(status?, priority?, category?, query?, requester_email?, page, page_size)` returns a `TicketsPage`.
- `it_update_ticket_status(number, status, comment="", actor="")` returns a `Ticket`. Invalid moves are refused (409), and the error lists the allowed next statuses.
- `it_add_comment(number, body, actor="")` returns a `Ticket`.

## Testing

Smoke test. With the system running (`scripts\win\run_all.ps1`):

```powershell
.venv\Scripts\python scripts\smoke\mcp_smoke.py
```

It lists every tool with its risk level, calls each read tool once, and prints `MCP SMOKE: PASS` or `FAIL`.

MCP Inspector (needs Node.js):

```powershell
npx @modelcontextprotocol/inspector
```

In the Inspector:

1. Choose transport "Streamable HTTP" and URL `http://127.0.0.1:8101/mcp`.
2. Under Authentication, add the header `Authorization: Bearer <FINANCE_MCP_TOKEN from .env>`.
3. Connect, open Tools, and run `finance_summary`.

Without the header the server answers 401, which is expected.
