# Changelog

All notable changes, by phase. Each phase lives on its own `phase/<n>-<name>` branch
and is merged into `main` by the project owner after the phase gate.

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
| test_default_demo_passwords_exist_when_env_not_set | default `admin123`-style passwords | new auth: no defaults, env-only first admin (`test_no_users_and_no_admin_env_fails_clearly`) | 1b, when legacy login is routed to the new auth | open |
| test_unknown_role_has_unrestricted_agents | fail-open role allow-list | `require_roles` (server-side) | 1b | open |
| test_assistant_role_can_reach_finance_and_hr_agents | over-broad role | per-agent allow-lists | 1b | open |
| test_consume_is_destructive_no_ack_no_redelivery | lossy in-memory queue | DB queue with ack and retry | 1b | open |
| test_orchestrator_is_a_process_wide_singleton_with_per_request_state | shared request state | per-request orchestrator | 1b | open |
| test_otp_uses_non_crypto_random_and_dev_fallback_on_by_default | weak OTP, code shown on screen | hashed single-use reset codes plus sandbox outbox (`test_forgot_password_no_enumeration_and_sandbox_outbox`) | 1b | open |
| test_no_auth_and_wildcard_cors | open tool server | authenticated MCP servers | 2 | open |
| test_gmail_send_reports_success_even_when_send_failed | false success | typed MCP results | 2 | open |
| test_gmail_read_inbox_ignores_its_parameters | ignored params | typed MCP inputs | 2 | open |
| test_email_is_sent_without_approval_when_address_in_prompt | no approval gate | approval gate | 3 | open |
| test_auto_reply_hardcodes_shortlist_for_any_mern_email | hard-coded auto reply | "Suggest reply" with approval | 3 | open |
| test_smtp_fallback_can_send_twice | duplicate send | Gmail API plus idempotency | 3 | open |
| test_hostile_cv_text_is_inlined_undelimited | prompt injection | delimited input plus schema validation | 3 | open |
| test_llm_error_silently_rejects_candidate | silent rejection | "needs human review" | 3 | open |
| test_payroll_question_routes_to_hr_not_finance | misrouting | new orchestrator | 3 | open |
| test_no_calendar_agent_exists | no calendar | Calendar agent | 3 | open |

## Phase 0: Audit, branch `phase/0-audit`
- `docs/AUDIT_REPORT.md` and 51 characterization tests in `tests/characterization/`. No application code changed.
