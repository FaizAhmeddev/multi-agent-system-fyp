# AgentsMind

One workspace. Every department. Handled.

AgentsMind is a multi-agent office system for HR, IT, Finance, Documents and Communications
(email and calendar). You ask in plain language. Specialised agents look things up through
MCP servers. Anything that would change data, send an email or book time first appears as an
approval card. Nothing happens until a person approves it.

- **Web app** (React) with light and dark themes and role-based screens.
- **Core API** (FastAPI), with an orchestrator and six LangGraph agents.
- **Persistent work queue.**
- **Two external systems**, each with its own app and database: the AgentsMind Finance Portal and the AgentsMind IT Helpdesk.
- **Four MCP servers:** finance-mcp, it-mcp, calendar-mcp and workspace-mcp (Gmail, Drive).

Without an OpenAI key or a Google account, everything runs in a labeled sandbox. Results are
marked **Simulated**, and nothing reaches real people.

| Read | For |
|---|---|
| `docs/USER_MANUAL.md` | Using AgentsMind, by role |
| `docs/DEMO_SCRIPT.md` | A 12-minute presentation walkthrough of the acceptance scenarios |
| `docs/ARCHITECTURE.md` | How the parts fit, with diagrams |
| `docs/SECURITY.md` | Threat model, controls and known limits |
| `docs/DEPLOYMENT.md` | Install, configure, connect Google and OpenAI, back up, upgrade |
| `docs/ASSISTANT.md`, `docs/MCP_TOOLS.md`, `docs/FRONTEND.md` | Assistant, MCP tools and web app in detail |
| `CHANGELOG.md` | What changed in each phase, including the legacy-bug ledger |

## Start it (Windows, no PowerShell needed)

You need Python 3.11 or 3.12, Node.js 22 LTS and git. Then, in the AgentsMind folder:

1. Double-click **Start-AgentsMind.bat** (or run `python main.py`). The first start takes a few minutes. It:
   - creates `.venv` and installs the pinned packages;
   - creates `.env` with random secrets (your own values are never overwritten);
   - creates the database and builds the web app;
   - opens the Google sign-in once if a Google OAuth client file is configured.

   Every start then runs the external systems (Finance Portal on port 8201 and IT Helpdesk on 8202, each
   a separate app with its own database), the MCP servers, the core API and the worker in that one window, opens
   **http://127.0.0.1:8000**, restarts any part that crashes, and stops everything when you close the
   window or press Ctrl+C.
2. Optional: to run the external systems on their own (for example on another computer), double-click
   **Start-External-Systems.bat**; main.py then uses the running ones (or pass `--no-portals`).
3. If something is left running after a crash, double-click **Stop-AgentsMind.bat**.

Sign in with the admin account in `.env` (`AGENTSMIND_ADMIN_EMAIL`, `AGENTSMIND_ADMIN_PASSWORD`; also in
`data\local_credentials.txt`). To change it later: `.venv\Scripts\python scripts\set_admin.py --email ... --password ...`.

## Run it from VS Code

Open the `agentsmind` folder in VS Code (File > Open Folder). Install the recommended Python extension when asked.
Then **Run and Debug** (Ctrl+Shift+D), pick a configuration and press **F5**:

| Configuration | What it does |
|---|---|
| Run AgentsMind | `main.py`: sets up and starts everything (including the Finance Portal and IT Helpdesk), opens http://127.0.0.1:8000 |
| Run AgentsMind without the external systems | the same, without the Finance Portal and IT Helpdesk |
| Run External Systems | only the Finance Portal (8201) and IT Helpdesk (8202) |
| Run all tests | every test suite and the frontend type check; report in `logs\test-report.txt` |
| Stop AgentsMind | stops anything still running |

Press the red Stop button (Shift+F5) to stop. Or open `main.py` and press the Run button at the top right.

## Configure (`.env`)

| Setting | What it connects |
|---|---|
| `OPENAI_API_KEY` | The model: routing of unclear requests, understanding HR requests, CV rubrics, drafts. Without it answers are labeled Simulated. |
| `GMAIL_EMAIL`, `GMAIL_APP_PASSWORD` | Your Gmail through an app password (IMAP/SMTP): inbox, CV attachments, sending letters. |
| `GOOGLE_OAUTH_CLIENT_FILE` | Your Google OAuth client (`credentials.json`). One sign-in gives Calendar, Drive and Sheets. |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `TWILIO_WHATSAPP_TO`, `TWILIO_CONTENT_SID` | WhatsApp messages (welcome messages, notices). |
| `HR_EXCEL_DIRS`, `HR_CV_DIRS` | Folders with your HR Excel sheets and with CVs (plus `data\hr_sheets` and `data\cvs`). |
| `DEMO_MODE` | `false` (default): only your real data. `true`: sample users, inbox, CVs and calendar for a demo. |

Settings > Connections in the web app shows what is connected and has the Google sign-in button.

## HR

Everything is in **HR** in the web app, and in the **Assistant** in plain language:

- **Recruitment:** gather CVs from Gmail attachments, the CV folders and Drive; only candidates in Karachi
  (configurable) are screened against the job opening; rubric plus keyword check, protected details removed.
- **Offer letters, contracts and ready-made letters** (welcome/onboarding, conduct, resignation acceptance,
  final settlement, experience): Word and PDF, your own Word templates in `data\hr_templates`, emailed after approval.
- **Onboarding in one approval:** record, checklists, contract, welcome letter and email, IT ticket, payroll in the
  Finance Portal, induction invites, probation review, WhatsApp, and a row in your new-joiners sheet.
- **Induction, compliance (EOBI, SESSI, tax, NDA...) and separation checklists** with due dates; failed steps can be retried.
- **Attendance and leave:** check in/out, leave requests and balances (pro-rated), approvals, import from your sheet.
- **Payroll:** monthly run from salaries, attendance and unpaid leave; posting to the Finance Portal after approval.
- **Separation and final settlement** with every line shown.
- **Reports** (new joiners, induction, onboarding, separations, attendance, leave, compliance, payroll, headcount) with Excel export.
- **Your sheets:** register your Google Sheets and Excel files with what they hold; ask "Where do I keep the
  leave records?" or "Show Ahmed's leaves from my leave sheet".

## Check it

```powershell
.venv\Scripts\python scripts\smoke\mcp_smoke.py     # every MCP server and read tool: MCP SMOKE: PASS
```

Full test run (what the phase gate does):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\win\setup.ps1 -Dev
.venv\Scripts\python -m pytest tests\backend tests\portals tests\mcp_servers_tests tests\assistant -q
.venv\Scripts\python -m pytest tests\characterization -q
.venv\Scripts\python scripts\quality.py             # coverage, bandit, secrets scan, pip-audit
cd frontend; npm run typecheck; node scripts\contrast.mjs; npm run e2e   # e2e needs AgentsMind running
```

`scripts\win\agentsmind-gate.ps1` does all of this on a separate clone and writes one log.

## Attach files in the chat

Click the paperclip next to the message box to attach up to 5 files (PDF, Word, Excel, CSV or text, 15 MB each),
then ask, for example: "Analyze the attached campaign report and prepare a management summary", "Compare the two
attached documents", "Analyze these expenses and export it as PDF", or "Find the attached CV, summarize it, and
email it to Huzaifa". Files stay on this computer (`data\chat_uploads`) and only you can open them.

## Connect real services

- **OpenAI:** put `OPENAI_API_KEY` in `.env` and start again.
- **Gmail:** Google Account > Security > 2-Step Verification > App passwords; put the address and the 16-letter
  app password in `GMAIL_EMAIL` and `GMAIL_APP_PASSWORD`.
- **Google Calendar, Drive and Sheets:** set `GOOGLE_OAUTH_CLIENT_FILE` to your OAuth client JSON (Desktop app),
  enable the Calendar, Drive and Sheets APIs in its Google Cloud project, then start AgentsMind: the sign-in opens
  once (or use Settings > Connections). The token is stored encrypted in `data\google_token.enc`.
  The APIs are enabled at https://console.cloud.google.com/apis/library (Google Calendar API, Google Drive API,
  Google Sheets API). Until the Calendar API is on, meetings go to AgentsMind's local calendar.
- **WhatsApp:** the Twilio settings above.
- **Email auto-reply:** Settings > Email auto-reply (admin or HR). *Draft replies for approval* puts a drafted reply
  for each new email in Approvals; *Send replies automatically* sends them from Gmail. Only emails that arrive after
  you switch it on are answered, each once; your own, no-reply and newsletter emails are skipped, emails with text
  addressed to an AI always wait for approval, and at most 40 are sent per day. "Check the inbox now" runs it at once.

## Repository layout

```
backend/agentsmind/   core API: auth, RBAC, queue, tool gateway, MCP client, assistant and agents
external_systems/     Finance Portal and IT Helpdesk (separate apps and databases)
mcp_servers/          finance-mcp, it-mcp, calendar-mcp, workspace-mcp
frontend/             React web app and Playwright tests
db/migrations/        Alembic migrations for the core database
sandbox_data/         synthetic inbox and Drive used in sandbox mode
scripts/              setup, run, seed, smoke, quality, secrets scan, Google sign-in
tests/                backend, portals, MCP servers, assistant, characterization
assets/brand/         logo artwork (theme versions generated by scripts/brand/make_brand_assets.py)
FYP_FINAL/            the original prototype, kept only for characterization tests
```

## Status

Phases 0 to 5 were verified on the Windows laptop with the phase gate. The HR ecosystem, the real Gmail,
Sheets, Excel and WhatsApp connections, the launchers and DEMO_MODE (version 0.6) are covered by new tests
(`tests/assistant/test_hr_logic.py`, `tests/backend/test_hr.py`); see CHANGELOG.md for what was verified where.
