# Deployment and operations

AgentsMind targets one Windows computer without Docker (the FYP demo laptop). Every part
runs as a separate process bound to 127.0.0.1.

## Requirements

- Python 3.11 or 3.12. `tzdata` is pinned so time zones work on Windows.
- Node.js 22 LTS, to build the web app and run Playwright.
- git.
- About 1.5 GB of disk for `.venv`, `node_modules` and the Playwright Chromium download.

## Install

```powershell
powershell -ExecutionPolicy Bypass -File scripts\win\setup.ps1        # add -Dev for tests and quality tools
```

`setup.ps1` does the following:

1. Creates `.venv`.
2. Installs `requirements\servers.txt`, or `requirements\dev.txt` with `-Dev`. Every version is exact.
3. Runs `scripts\env_setup.py`, which creates or completes `.env` with random secrets. It never overwrites an existing value, so re-running it after an upgrade only adds new settings.
4. Writes the generated sign-in details to `data\local_credentials.txt`.
5. Runs `alembic upgrade head`.
6. Runs `npm install` and `npm run build` in `frontend\`.

## Run

```powershell
powershell -ExecutionPolicy Bypass -File scripts\win\run_all.ps1     # all parts, one window each
powershell -ExecutionPolicy Bypass -File scripts\win\stop_all.ps1    # stop them
```

Seed synthetic data once:

```powershell
.venv\Scripts\python scripts\seed.py
.venv\Scripts\python external_systems\finance_portal\seed.py
.venv\Scripts\python external_systems\it_portal\seed.py
.venv\Scripts\python -m mcp_servers.calendar_mcp.seed
```

## Configuration (`.env`)

The full list with comments is in `.env.example`.

| Setting | Meaning |
|---|---|
| `JWT_SECRET` | 32 or more random characters (generated) |
| `AGENTSMIND_ADMIN_EMAIL`, `AGENTSMIND_ADMIN_PASSWORD` | First admin, used only while the users table is empty |
| `DATABASE_URL` | Default `sqlite:///data/agentsmind.db`. For PostgreSQL: `pip install -r requirements\postgres.txt` and `postgresql+psycopg://user:pass@host:5432/agentsmind` |
| `TIMEZONE` | Default `Asia/Karachi`. Used to read "tomorrow at 3 pm" |
| `QUEUE_BACKEND` | `db` (durable, default) or `memory` (tests only) |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Empty means sandbox mode, with output labeled Simulated |
| `*_MCP_TOKEN`, `*_MCP_URL`, `*_MCP_PORT` | One bearer token per MCP server (generated). The core and the server read the same value |
| `FINANCE_PORTAL_*`, `IT_PORTAL_*` | Portal API keys, session keys and staff admin accounts (generated) |
| `CALENDAR_MODE`, `WORKSPACE_MODE` | `auto` (Google when signed in, otherwise sandbox), `sandbox` or `google` |
| `GOOGLE_OAUTH_CLIENT_FILE`, `GOOGLE_TOKEN_ENCRYPTION_KEY` | Google client file location, and the key that encrypts `data\google_token.enc` |

## Connect OpenAI

1. Put `OPENAI_API_KEY=...` in `.env`.
2. Restart `run_all.ps1`.

The assistant then uses the model to route requests with no clear match, to draft emails, to rate CV rubrics and to summarise documents. Every structured answer is validated, and invalid answers are refused rather than used. Totals, dates and scores are still computed in code.

## Connect Google (Calendar, Gmail, Drive)

1. In Google Cloud Console, create or choose a project and enable three APIs: **Google Calendar API**, **Gmail API** and **Google Drive API**.
2. Configure the OAuth consent screen. For a demo, External with yourself as a test user is enough.
3. Create an **OAuth client ID** of type **Desktop app**. Download the JSON and save it as `secrets\google_oauth_client.json`. The `secrets\` folder is gitignored.
4. Run `.venv\Scripts\python scripts\google_oauth.py`. A browser opens; sign in and approve.

   The script requests only these scopes:
   - `calendar.events.owned`
   - `calendar.freebusy`
   - `gmail.readonly`
   - `gmail.send`
   - `drive.readonly`

   The token is stored only encrypted, in `data\google_token.enc`.
5. Restart `run_all.ps1`. Admin, then System, should show calendar-mcp and workspace-mcp as reachable, and cards no longer say Simulated.

To go back to sandbox mode, set `CALENDAR_MODE=sandbox` and `WORKSPACE_MODE=sandbox`, or delete `data\google_token.enc`.

## Backups

Everything stateful is in `data\`:

| File | Contents |
|---|---|
| `agentsmind.db` | Core database |
| `finance_portal.db`, `it_portal.db` | Portal databases |
| `calendar_sandbox.db` | Sandbox calendar |
| `workspace_*_sent.db` | Gmail send ledgers |
| `google_token.enc` | Encrypted Google token |
| `local_credentials.txt`, `seed_credentials.txt` | Sign-in details |

Stop the system and copy `data\` together with `.env`. The encryption key in `.env` is needed to read the Google token.

## Upgrade

```powershell
git pull
powershell -ExecutionPolicy Bypass -File scripts\win\setup.ps1     # new pins, new .env settings, migrations, web app build
```

Migrations are forward-only in normal use. Each one has a `downgrade` for development.

## Beyond one laptop

The defaults are for a single computer. Before putting AgentsMind on a network:

- **TLS and network:** put a TLS reverse proxy (for example Caddy or nginx) in front of port 8000. Keep the MCP servers and portal APIs on 127.0.0.1 or a private network, never on the internet.
- **Database:** use PostgreSQL (`DATABASE_URL`) and run more than one queue worker if needed. Leases make that safe.
- **Settings:** set `APP_ENV=prod`, which hides `/api/docs`, and set `CORS_ORIGINS` to the real web address.
- **Refresh tokens:** consider moving the refresh token to an HttpOnly cookie (see `docs/SECURITY.md`).

## Phase gate

`scripts\win\agentsmind-gate.ps1`, run next to `agentsmind.bundle`:

1. Clones the repository into `.\agentsmind` and checks out the newest phase branch.
2. Runs setup, lint, every test suite with coverage, the quality checks (bandit, secrets scan, pip-audit), migrations on a clean database, the seeds, and the web app build with the contrast check.
3. Starts the whole system in sandbox mode and runs the MCP smoke test, API checks, assistant prompts and the Playwright suite.
4. Writes everything to `gate-logs\gate-<time>.log`.
