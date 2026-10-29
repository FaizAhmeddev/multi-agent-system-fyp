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

## Quick start (Windows, no Docker)

You need:

- Python 3.11 or 3.12
- Node.js 22 LTS
- git

```powershell
git clone https://github.com/FaizAhmeddev/multi-agent-system-fyp.git
cd multi-agent-system-fyp
powershell -ExecutionPolicy Bypass -File scripts\win\setup.ps1
powershell -ExecutionPolicy Bypass -File scripts\win\run_all.ps1
.venv\Scripts\python scripts\seed.py
.venv\Scripts\python external_systems\finance_portal\seed.py
.venv\Scripts\python external_systems\it_portal\seed.py
.venv\Scripts\python -m mcp_servers.calendar_mcp.seed
```

What these do:

1. `setup.ps1` creates `.venv` and installs the pinned packages.
2. It also creates `.env` with random secrets. There are no default passwords.
3. It applies the database migrations and builds the web app.
4. `run_all.ps1` starts each part in its own window:
   - the two portals
   - the four MCP servers
   - the core API, which also serves the web app
   - the queue worker
5. The seed scripts add synthetic demo data only.

Open **http://127.0.0.1:8000** and sign in:

- **Admin:** the sign-in details are in `data\local_credentials.txt`.
- **Demo users** (HR, IT, Finance, Employee): `seed.py` prints them once and saves them in `data\seed_credentials.txt`.

Both files are gitignored. Stop everything with `scripts\win\stop_all.ps1`.

| Part | Address |
|---|---|
| AgentsMind (web app and API docs at /api/docs) | http://127.0.0.1:8000 |
| AgentsMind Finance Portal | http://127.0.0.1:8201 |
| AgentsMind IT Helpdesk (public complaint form at /) | http://127.0.0.1:8202 |
| finance-mcp, it-mcp, calendar-mcp, workspace-mcp | http://127.0.0.1:8101 to 8104, path /mcp (bearer token) |

macOS and Linux run the same pieces; see `docs/DEPLOYMENT.md`.

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
cd frontend; npm run typecheck; node scripts\contrast.mjs; npm run e2e   # e2e needs run_all.ps1 running
```

`scripts\win\agentsmind-gate.ps1` does all of this on a separate clone and writes one log.

## Connect real services (optional)

- **OpenAI:** put `OPENAI_API_KEY` in `.env` and restart. Answers are no longer labeled Simulated.
- **Google Calendar, Gmail and Drive:** follow the steps in `docs/DEPLOYMENT.md`. You create a Desktop OAuth client, save it as `secrets\google_oauth_client.json`, then run `scripts\google_oauth.py` once. It requests the narrowest scopes, and the token is stored encrypted.

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

| Phase | Content | Verified on the Windows laptop |
|---|---|---|
| 0 | Audit and characterization tests | yes |
| 1a, 1b | Foundation, auth, queue, RBAC, gateway | yes |
| 2 | Portals and MCP servers | yes |
| 3 | Agents, calendar, Gmail, Drive, CV screening | yes |
| 4 | Web app, Playwright, Streamlit removed | build, typecheck and contrast yes; e2e re-run pending |
| 5 | Quality tools and documentation | coverage and bandit yes; pip-audit re-run pending; secrets scan waits for the history purge |

Before publishing: run `scripts\win\finish-agentsmind.ps1` (history purge, see `docs/HISTORY_PURGE.md`).
Credentials still needed for live mode: an OpenAI key and a Google OAuth client.
