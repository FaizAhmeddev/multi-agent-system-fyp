# Demo script (about 12 minutes)

Before the demo:

1. Run `scripts\win\run_all.ps1` and the four seed commands from the README.
2. Open http://127.0.0.1:8000 in two browser windows: one signed in as the **admin**, one as the **employee** (Omar Farooq). The details are in `data\local_credentials.txt` and `data\seed_credentials.txt`.
3. Also open http://127.0.0.1:8202 (IT Helpdesk) and http://127.0.0.1:8201 (Finance Portal).

Each scenario names the automated test that proves it, so you can show the test too.

| # | Scenario | Test |
|---|---|---|
| 1 | Sign-in, lockout and roles | `tests/backend/test_auth.py`, `frontend/e2e/auth-and-rbac.spec.ts` |
| 2 | HR cannot reach Finance, in the UI and in code | `test_hr_agent_cannot_call_finance_tool_denied_and_logged`, `test_employee_denied_payroll_and_audited` |
| 3 | IT complaint to the confirmation screen | `frontend/e2e/departments.spec.ts` (IT), `tests/backend/test_mcp_integration.py` |
| 4 | Finance by prompt and by form, numbers from SQL | `test_finance_summary_numbers_come_from_tool`, `test_payroll_total_equals_independent_sql` (MCP integration), e2e Finance |
| 5 | Calendar by prompt with conflict, approval and read-back | `test_calendar_prompt_to_event_with_read_back`, `tests/assistant/test_calendar_agent.py`, e2e assistant |
| 6 | Hostile email | `test_hostile_email_only_produces_reply_drafts`, `test_hostile_email_cannot_trigger_actions`, e2e assistant |
| 7 | CV screening with a hostile CV and human review | `tests/assistant/test_screening.py`, `test_hr_screening_fills_candidates_board`, e2e HR |
| 8 | The queue survives a worker crash | `test_killed_worker_task_is_retried_once_without_duplicate_effect` |
| 9 | MCP security: tokens, allow-lists, idempotency | `tests/mcp_servers_tests/`, `tests/backend/test_mcp_integration.py` |
| 10 | Light and dark themes, accessible, no emoji or gradients | `frontend/e2e/design-rules.spec.ts`, `frontend/scripts/contrast.mjs` |

## 1. One workspace (1 min)

1. As the admin, show the **Hub**: department tiles, approvals waiting, and the system panel with four MCP servers up.
2. Open the theme menu and switch to **Dark**, then back to **Light**.
3. Say: "Everything you see is synthetic data. Anything from a sandbox is labeled Simulated."

## 2. Roles are enforced in code (1 min)

1. In the employee window, the menu shows no Finance. Type `/finance` in the address bar: a 403 page appears that explains why.
2. In the Assistant, as the employee, ask: **"What is the total monthly payroll?"** The card says the department is not available to your role.
3. As the admin, open **Admin**, then **Audit log**, and filter by `access.denied`. The attempt is there.

## 3. IT complaint (1.5 min)

1. As the employee, ask: **"My laptop keeps disconnecting from the VPN, please raise a ticket."**
2. The assistant asks for the department; answer **Sales**.
3. An approval card shows the category (network), priority, requester and description. Press **Approve**.
4. The result shows the ticket number and the confirmation link. Open it: the IT Helpdesk "Complaint submitted" screen.
5. In the IT Helpdesk staff screens, the same ticket shows its SLA due time.

## 4. Finance (1.5 min)

1. As the admin, open **Finance**. The summary tiles say "Computed by SQL in the Finance Portal".
2. Ask the assistant: **"Change Ahmed Raza's salary to 150,000."** The approval card shows the old value and the new one.
3. Approve it. Then show the change in the Finance Portal (http://127.0.0.1:8201).
4. Ask: **"Delete the record for Ahmed Raza."** The destructive card stays disabled until you type the name. Reject it.

## 5. Calendar by prompt (2 min)

1. Ask: **"Schedule a design review tomorrow at 3 pm for 45 minutes with a Google Meet link."**
2. The card shows the exact time in Asia/Karachi, the phrase it came from ("tomorrow"), and a conflict with the seeded **Weekly team sync**.
3. Approve it. The result says "Read back from the calendar: confirmed" and has a Meet link.
4. Ask: **"Move my 3 pm meeting to 4 pm"**, then **"Am I free Friday afternoon?"**
5. Say: "Dates are parsed by code, not by the model. The model never does arithmetic."

## 6. Hostile email (1.5 min)

1. Open **Communications**. The message "ACTION REQUIRED" is marked **Suspicious**. Open it: it orders the AI to send the payroll and delete a record.
2. In the Assistant, ask: **"Draft replies to my unread emails."** You get one approval card per email.
3. The card for the hostile email is addressed to its sender only and carries a warning. Nothing touches Finance.
4. Show **Admin**, then **Tool calls**: no finance tool was called.

## 7. CV screening (1.5 min)

1. Open **HR** and press **Screen CVs** for "Python Developer".
2. On the board, Sara Khan is a strong match, and Bilal Ahmed is weak.
3. **Alex Example** is marked **Needs human review**, because his CV tells the AI to score him 10/10.
4. Open Alex: the reasons are listed, the rubric shows no invented evidence, and protected details were removed.
5. Move Sara to **Shortlisted** with the Move menu. Say: "Only a person moves candidates."

## 8. Reliability (1 min)

1. Show **Admin**, then **System**: queue counts, and dead tasks with Retry.
2. Explain the kill-and-restart test: a worker is killed mid-task, the lease expires, and another worker finishes the task exactly once.

## 9. MCP security (0.5 min)

1. In a terminal, run `scripts\smoke\mcp_smoke.py` to list every tool with its risk level.
2. Show that `curl http://127.0.0.1:8101/mcp` without the token is refused with 401.

## 10. Close (0.5 min)

Back on the Hub:

- **Connecting real services:** OpenAI is one key in `.env`; Google is one sign-in with the narrowest scopes.
- **Quality:** the phase gate runs every test, bandit, pip-audit, the secrets scan, the contrast check and Playwright on a clean clone.
