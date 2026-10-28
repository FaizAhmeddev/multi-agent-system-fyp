# AgentsMind

One workspace. Every department. Handled.

AgentsMind is a multi-agent office system for HR, IT, Finance, Documents and Communications.
This repository is mid-upgrade: the new core lives in `backend/`. The legacy Streamlit
prototype is still in `FYP_FINAL/` until Phase 4 replaces it.

## Status

| Part | State |
|---|---|
| Core API: settings, database, migrations, auth | Phase 1a |
| Persistent queue, department RBAC, tool gateway, wrapped legacy agents | Phase 1b |
| Finance Portal, IT Helpdesk, MCP servers (finance-mcp, it-mcp) | Phase 2 |
| Agents through MCP, Google Calendar | Phase 3 |
| React UI (replaces Streamlit) | Phase 4 |

See `CHANGELOG.md`, `docs/AUDIT_REPORT.md` and `docs/MCP_TOOLS.md`.

## Run the core API on Windows (no Docker)

Requires Python 3.11 or 3.12 and git.

```powershell
git clone https://github.com/FaizAhmeddev/multi-agent-system-fyp.git
cd multi-agent-system-fyp
powershell -ExecutionPolicy Bypass -File scripts\win\setup.ps1 -Dev
powershell -ExecutionPolicy Bypass -File scripts\win\run_backend.ps1
```

`setup.ps1` creates `.venv`, installs the pinned packages and creates `.env` from
`.env.example`. The `.env` gets a random `JWT_SECRET` and a random first-admin password; the
password is printed once and saved in `data\first_admin.txt`. The script then runs the migrations.

Start everything (two portals, two MCP servers, the core API and the queue worker,
each in its own window):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\win\run_all.ps1
.venv\Scripts\python scripts\seed.py                              # synthetic core users
.venv\Scripts\python external_systems\finance_portal\seed.py      # synthetic people and payments
.venv\Scripts\python external_systems\it_portal\seed.py           # synthetic tickets
.venv\Scripts\python scripts\smoke\mcp_smoke.py                   # MCP check: prints MCP SMOKE: PASS
```

| Part | URL |
|---|---|
| Core API (docs) | http://127.0.0.1:8000/api/docs |
| AgentsMind Finance Portal | http://127.0.0.1:8201 |
| AgentsMind IT Helpdesk (public complaint form) | http://127.0.0.1:8202 |
| finance-mcp / it-mcp | http://127.0.0.1:8101/mcp, http://127.0.0.1:8102/mcp (bearer token) |

Sign-in details for the core and both portals are generated into `data\local_credentials.txt`.
Stop everything with `scripts\win\stop_all.ps1`. Only the core API and worker, without
the external systems: `run_backend.ps1` and `run_worker.ps1`.

Then open http://127.0.0.1:8000/health or the API docs at http://127.0.0.1:8000/api/docs.

Optional synthetic demo data:

```powershell
.venv\Scripts\python scripts\seed.py
```

## Run on macOS or Linux

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements/dev.txt
python scripts/env_setup.py   # creates .env with random secrets
alembic upgrade head
uvicorn agentsmind.main:app --app-dir backend --host 127.0.0.1 --port 8000
PYTHONPATH=backend python -m agentsmind.queue.worker     # second terminal
```

## Tests

```bash
python -m pytest tests/backend -q          # includes real portal + MCP processes
python -m pytest tests/portals -q
python -m pytest tests/characterization -q
ruff check backend db scripts mcp_servers external_systems tests/backend tests/portals
```

## Configuration

All settings come from environment variables or `.env` (see `.env.example`).
Secrets are never committed: `.env`, `credentials.json`, token files, `data/` and databases
are all gitignored. There are no default passwords. The first admin is created from
`AGENTSMIND_ADMIN_EMAIL` and `AGENTSMIND_ADMIN_PASSWORD` when the users table is empty.

PostgreSQL: `pip install -r requirements/postgres.txt`, then set
`DATABASE_URL=postgresql+psycopg://user:pass@host:5432/agentsmind`.

## Legacy prototype

The original Streamlit app is in `FYP_FINAL/` (see `FYP_FINAL/README.md`). It is kept for
reference and characterization tests only, and has the known security issues listed in
`docs/AUDIT_REPORT.md`. Do not expose it on a network.
