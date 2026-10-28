# Changelog

All notable changes, by phase. Each phase lives on its own `phase/<n>-<name>` branch
and is merged into `main` by the project owner after the phase gate.

## Phase 2: External systems and MCP, branch `phase/2-portals-mcp`

### Added
- **AgentsMind Finance Portal** (`external_systems/finance_portal`): its own FastAPI app, SQLite database, staff sign-in (Argon2id, lockout after 5 failures), and REST API.
  - People CRUD with search, filters, sorting, pagination and CSV export (spreadsheet formulas are neutralised in the export).
  - Payment records per person, one per month.
  - Money is stored as integer minor units, so SQL totals are exact.
  - `GET /api/v1/summary` computes headcount and payroll in SQL.
  - Duplicate emails return 409. An `Idempotency-Key` makes a repeated create return the original record.
  - Data changes are audited in `audit_events`.
  - Web screens: sign-in, people list with stats, add, edit, detail with payments, delete confirmation (type the full name), and payments list. Forms validate inline, carry a CSRF token, and are protected against double submit (form key plus a disabled button).
  - The API needs `X-API-Key`.
- **AgentsMind IT Helpdesk** (`external_systems/it_portal`): its own app, database and API.
  - Public complaint form, with an optional attachment: 5 MB limit, type checked by magic bytes (PDF, PNG, JPEG, text), sanitised name, stored under a random filename.
  - Dedicated "Complaint submitted" screen showing the ticket number (ITK-000123), summary, expected response time and a "Track this ticket" link. The confirmation and tracking pages need the private tracking token.
  - Staff screens: ticket list with filters and sorting, ticket detail with the status workflow (open, in progress, resolved, closed; resolved can be reopened; closed is final), assignee, comments and internal notes, and SLA due time (urgent 4 h, high 8 h, medium 24 h, low 72 h).
  - Tickets created through the API carry `source=agentsmind` and return confirmation and tracking links.
- Both portals share one visual language (`external_systems/portal_common`): light and dark design tokens, a theme toggle that is remembered, no emoji, and 403, 404 and 500 pages that say what to do next.
- **MCP servers** on `mcp==2.3.0`: `mcp_servers/finance_mcp` (8 tools) and `mcp_servers/it_mcp` (5 tools), with typed Pydantic inputs and outputs, read/write/destructive annotations, descriptions written for an LLM, and idempotency keys on create, update and delete. Security and timeouts are described in `docs/MCP_TOOLS.md`.
- **Core MCP client** (`backend/agentsmind/mcp/client.py`): routes the 13 tools through the gateway. Reads retry with backoff, writes pass the approval's idempotency key, and a wrong token is reported as `unauthorized`.
- **Workspace APIs** (`/api/finance/*`, `/api/it/*`) for the UI. They go through the gateway too; the user's own form submissions are recorded as direct approvals, and deletes need `confirm` plus the exact name.
- **Row-level scoping in the gateway**: users outside IT only list, open and comment on their own tickets.
- `GET /api/admin/mcp`: for each MCP server, shows whether it is configured and reachable, its tools, and latency.
- `scripts/env_setup.py`: creates or completes `.env` with random secrets and never overwrites existing values. `scripts/win/run_all.ps1` and `stop_all.ps1` start and stop the whole system, and `scripts/smoke/mcp_smoke.py` checks the MCP servers. Both portals have seed scripts.
- Tests:
  - `tests/portals` (Finance and IT portals: API, web, uploads, workflow, idempotency, SQL total).
  - `tests/backend/test_mcp_integration.py` (real portal and MCP processes: token required, schemas and annotations, approval flow, no duplicates on retry, payroll equals SQL, HR denied, IT confirmation screen, ticket scoping).

### Changed
- Dependency pins: `fastapi==0.118.2`, `starlette==0.48.0`, `pydantic==2.12.0` (mcp 2.3.0 needs pydantic 2.12 or later; FastAPI 0.118.1 added Pydantic 2.12 support), plus `mcp==2.3.0` and `httpx2==2.13.1`. `requirements/portals.txt` adds Jinja2 and itsdangerous.
- The catalog now opens `it_list_tickets` and `it_get_ticket` to all staff, scoped by the gateway.

### Legacy fixes, each flipping a pinned test
- `FYP_FINAL/mcp_server/server.py`:
  - Every request needs `Authorization: Bearer $FYP_MCP_TOKEN`.
  - The server does not start without a token of 24 or more characters.
  - No CORS headers are sent, and OPTIONS returns 405.
  - `gmail_send_email` reports failures.
  - `gmail_read_inbox` passes `max_emails` and `unread_only` through.
  - The Streamlit UI now shows the server's real running state.
- `FYP_FINAL/tools/gmail_read.py`: supports `unseen_only`.

## Phase 1b: Queue, RBAC, tool gateway, wrapped legacy agents, branch `phase/1b-queue-rbac-agents`

### Added
- Persistent work queue `agentsmind.queue` (`QUEUE_BACKEND=db|memory`):
  - Each task is leased by one worker, with an owner token. Only that owner can acknowledge or fail it, so a late answer from a presumed-dead worker is ignored.
  - Failed tasks retry with exponential backoff (2, 4, 8 seconds and so on, up to 5 minutes).
  - After `QUEUE_MAX_ATTEMPTS`, a task moves to a dead-letter state. An admin can send it back to the queue.
  - Idempotency keys stop the same request from being queued twice.
  - Each handler gets a stable `effect_key`, so retries cannot repeat side effects.
  - Migration `0002_queue_tasks` adds the table, plus `agent_runs.action`, `meta` and `task_id`.
- Worker process: `python -m agentsmind.queue.worker` (Windows: `scripts/win/run_worker.ps1`). It extends its lease while a task runs and stops cleanly on Ctrl+C.
- Departments and RBAC (`agentsmind.rbac`): HR, IT, Finance, Documents and Communications, each with the roles that may open it. `GET /api/departments` lists all five, with access and a reason when denied. `GET /api/departments/{slug}` returns 403 when forbidden and writes the denial to the audit log.
- Tool catalog and per-agent allow-lists (`agents/catalog.py`): every tool from the spec is listed with its server, risk level (read, write or destructive) and the roles that may use it.
- Tool gateway (`agents/gateway.py`), the only path from an agent to a tool. It refuses a tool that is unknown, not on the agent's allow-list, or not allowed for the user's role, and records the refusal in `tool_calls` and `audit_logs`. Write and destructive tools first create an approval and do not run until it is approved. On approval, the gateway runs exactly the stored arguments once, with the approval's idempotency key. Tool inputs are redacted in the log.
- Approvals API: `GET /api/approvals` (own requests; admins see all), plus `POST /api/approvals/{id}/approve` and `POST /api/approvals/{id}/reject`. Destructive actions also need `confirm=true`, and the 400 response states exactly what will be changed.
- Agent runs API: `GET /api/agents` lists the agents the user may use. `POST /api/agents/{agent}/runs` (with an optional `Idempotency-Key` header) validates the inputs and queues the run; `GET /api/agents/runs/{id}` returns it, and only to its owner.
- Legacy agents wrapped (`agents/ported.py` and `agents/registry.py`): the HR (interview questions, onboarding checklist, policy answer, job description), IT (troubleshoot) and Documents (summarize, extract, compare) prompts are ported unchanged, with no database, ChromaDB or environment side effects and no emoji. `tests/characterization/test_ported_prompts.py` checks that the legacy and ported prompts are identical.
- Sandbox LLM: until Phase 3, every model answer is labeled `[Simulated]` and the run has `simulated=true`.
- Admin endpoints: `GET /api/admin/queue` (stats), `GET /api/admin/queue/tasks`, `POST /api/admin/queue/tasks/{id}/retry`, and `GET /api/admin/tool-calls`.

### Legacy fixes (FYP_FINAL), each flipping a pinned test
- `config.py`: no default passwords; an unknown role now gets the Assistant tab and the general agent only; the `Assistant` role is limited to general, email and inbox agents.
- `database/sqlite_db.py`: empty passwords are refused, and accounts without a configured password are never created or accepted.
- `ui/auth_pages.py`: removed the "Demo accounts" hint from the login page.
- `auth/otp_service.py`: codes now use `secrets`, and the on-screen code fallback is off by default.
- `message_queue/queue.py`: `consume()` marks messages in flight. Use `ack()` to confirm; anything not acknowledged is delivered again after the visibility timeout.
- `Orchestrator/orchestrator_brain.py`: the shared singleton is removed. `new_orchestrator()` gives each caller its own instance, and the Streamlit UI keeps one per session.

### Fixed
- The worker task-handler registry moved to `queue/registry.py`. With the registry inside `worker.py`, running the worker as `python -m ...worker` would have created a second, empty copy of it.

## Phase 1a: Foundation (layout, settings, database, migrations, auth), branch `phase/1a-foundation`

### Added
- `backend/agentsmind/`: new FastAPI core, separate from the legacy `FYP_FINAL/` app (which is unchanged in 1a).
  - `settings.py`: typed settings (pydantic-settings). `JWT_SECRET` is required (32+ characters). Timezone is validated (default `Asia/Karachi`).
  - `log_config.py`: JSON logs with a request id, plus automatic redaction of password, token, secret and key fields.
  - `GET /health`: checks the database and returns 503 when it is down.
  - Auth API under `/api/auth`: login, refresh (rotating opaque tokens with reuse detection), logout, me, password change, forgot and reset.
  - Admin API under `/api/admin`: list and create users, unlock a user, and the sandbox mail outbox.
  - `require_roles()` dependency that enforces roles on the server. Denials return 403 and are written to `audit_logs`.
- Security behaviour:
  - Argon2id password hashing.
  - Password policy: 12+ characters, not a common password, not repetitive, and must not contain the email name.
  - Lockout: 5 failed sign-ins lock the account for 15 minutes (both configurable). An admin can unlock.
  - Login errors are generic, and unknown emails take the same time as known ones (no account enumeration).
  - Password change and reset sign out all other sessions, and access tokens issued before the change stop working.
  - Reset codes are random, stored as SHA-256 hashes, single-use, and expire after 30 minutes. They are delivered through the sandbox outbox (`simulated=true`) until the Gmail API mailer lands in Phase 3.
  - No default passwords. The first admin comes only from `AGENTSMIND_ADMIN_EMAIL` and `AGENTSMIND_ADMIN_PASSWORD`, and the policy also applies to it.
- Database: SQLAlchemy 2 models for users, roles, user_roles, refresh_tokens, password_reset_tokens, outbound_emails, audit_logs, conversations, messages, agent_runs, approvals, tool_calls, documents, candidates and cv_records. Datetimes are always timezone-aware UTC, including on SQLite.
- Alembic (`alembic.ini`, `db/migrations`) with migration `0001_initial`. A test checks that the migrations match the models (no drift) and that downgrade and upgrade both work.
- `scripts/seed.py`: synthetic demo users (one per department role) and candidates. Passwords are random, printed once, and saved to the gitignored `data/seed_credentials.txt`. Safe to re-run.
- Windows, no-Docker path: `scripts/win/setup.ps1`, `scripts/win/run_backend.ps1`, and the phase-gate runner `scripts/win/agentsmind-gate.ps1`.
- Exact dependency pins in `requirements/backend.txt`, `requirements/dev.txt` and `requirements/postgres.txt` (optional PostgreSQL driver).
- Root `.gitignore` covering secrets, `data/`, `*.db`, logs, `FYP_FINAL/database/fyp_data.db` and `FYP_FINAL/logs/`.
- `tests/backend/`: auth, RBAC, health, settings, migrations, seed and unit tests.

### Fixed (from gate run 2026-10-28 22:41)
- Windows: `zoneinfo` had no time zone data (`TIMEZONE 'Asia/Karachi' is not a valid IANA time zone`), which failed setup, 27 backend tests and the API start. Added `tzdata==2024.2`.

### Changed
- `tests/characterization/conftest.py` now points the legacy database at a temp file, so tests never write to `FYP_FINAL/database/fyp_data.db`.

### Not in 1a (planned)
- Persistent DB queue, per-department RBAC routes, and wrapping the legacy agents: Phase 1b.
- docker-compose: Phase 1b (optional; the Windows no-Docker path is the primary run path).

### legacy_bug ledger
Every `legacy_bug` characterization test is flipped on purpose in the phase that replaces the behaviour, and recorded here.

| Test | Legacy behaviour pinned | Replaced by | Flip planned in | Status |
|---|---|---|---|---|
| test_default_demo_passwords_exist_when_env_not_set | default `admin123`-style passwords | new auth: no defaults, env-only first admin (`test_no_users_and_no_admin_env_fails_clearly`) | 1b, when legacy login is routed to the new auth | flipped in 1b -> test_no_default_passwords_when_env_not_set, test_legacy_login_refuses_empty_and_unset_passwords |
| test_unknown_role_has_unrestricted_agents | fail-open role allow-list | `require_roles` (server-side) | 1b | flipped in 1b -> test_unknown_role_gets_general_agent_only (also test_unknown_role_sees_everything -> test_unknown_role_sees_only_assistant) |
| test_assistant_role_can_reach_finance_and_hr_agents | over-broad role | per-agent allow-lists | 1b | flipped in 1b -> test_assistant_role_limited_to_email_and_inbox |
| test_consume_is_destructive_no_ack_no_redelivery | lossy in-memory queue | DB queue with ack and retry | 1b | flipped in 1b -> test_unacked_message_is_redelivered_and_ack_is_final |
| test_orchestrator_is_a_process_wide_singleton_with_per_request_state | shared request state | per-request orchestrator | 1b | flipped in 1b -> test_each_caller_gets_its_own_orchestrator |
| test_otp_uses_non_crypto_random_and_dev_fallback_on_by_default | weak OTP, code shown on screen | hashed single-use reset codes plus sandbox outbox (`test_forgot_password_no_enumeration_and_sandbox_outbox`) | 1b | flipped in 1b -> test_otp_uses_secrets_and_dev_fallback_is_off_by_default |
| test_no_auth_and_wildcard_cors | open tool server | authenticated MCP servers | 2 | flipped in 2 -> test_token_required_and_no_cors, test_server_refuses_to_start_without_token |
| test_gmail_send_reports_success_even_when_send_failed | false success | typed MCP results | 2 | flipped in 2 -> test_gmail_send_reports_failure_when_send_failed |
| test_gmail_read_inbox_ignores_its_parameters | ignored params | typed MCP inputs | 2 | flipped in 2 -> test_gmail_read_inbox_passes_its_parameters |
| test_email_is_sent_without_approval_when_address_in_prompt | no approval gate | approval gate | 3 | open |
| test_auto_reply_hardcodes_shortlist_for_any_mern_email | hard-coded auto reply | "Suggest reply" with approval | 3 | open |
| test_smtp_fallback_can_send_twice | duplicate send | Gmail API plus idempotency | 3 | open |
| test_hostile_cv_text_is_inlined_undelimited | prompt injection | delimited input plus schema validation | 3 | open |
| test_llm_error_silently_rejects_candidate | silent rejection | "needs human review" | 3 | open |
| test_payroll_question_routes_to_hr_not_finance | misrouting | new orchestrator | 3 | open |
| test_no_calendar_agent_exists | no calendar | Calendar agent | 3 | open |

## Phase 0: Audit, branch `phase/0-audit`
- `docs/AUDIT_REPORT.md` and 51 characterization tests in `tests/characterization/`. No application code changed.
