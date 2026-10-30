# Deploy on Render (free plan)

The repository has a `Dockerfile` and a `render.yaml` Blueprint. On Render the whole system runs in **one
process** (`deploy/onebox.py`) so it fits the free plan's 512 MB: the web app, core API, queue worker, the four
MCP servers and both portals share one port, each under its own path, and still talk to each other over MCP
and REST on 127.0.0.1 with their tokens.

## Steps

1. Push the code to GitHub (Push-to-GitHub.bat).
2. On https://dashboard.render.com click **New > Blueprint**, connect GitHub and pick
   `FaizAhmeddev/multi-agent-system-fyp` and the branch (`phase/5-quality`, or `main` after merging).
3. Render reads `render.yaml` and shows a web service **agentsmind** and a free Postgres database
   **agentsmind-db**. Fill in the values it asks for:
   - `AGENTSMIND_ADMIN_EMAIL`, `AGENTSMIND_ADMIN_PASSWORD`: the admin sign-in (use a strong password)
   - `OPENAI_API_KEY`: for live answers (optional)
   - `GMAIL_EMAIL`, `GMAIL_APP_PASSWORD`: to read Gmail (optional)
4. Click **Apply**. The first build takes about 10 minutes. The address is shown at the top, for example
   `https://agentsmind.onrender.com`. Sign in with the admin email and password from step 3.

### Without the Blueprint (New > Web Service)

Either choose **Language: Docker** (nothing else to fill in), or keep **Python 3** and set:

- Build Command: `pip install -r requirements.txt && cd frontend && npm ci && npx vite build`
- Start Command: `python deploy/onebox.py`
- Health Check Path: `/health`
- Environment: `PYTHON_VERSION=3.11.9` plus the values from step 3, and `JWT_SECRET` (Generate)

To try the same one-process setup on your computer first: VS Code > "Run in one process (the Render setup)",
then open http://127.0.0.1:10000.

## What the free plan cannot do (Render's limits)

| Limit | Effect |
|---|---|
| Sleeps after 15 minutes without visitors; waking takes about a minute | the first visit is slow; auto-reply and the worker pause while asleep |
| Files are not kept across restarts and redeploys | letters, uploads, CVs, the local calendar, connectors and the two portals' records start empty again; users, conversations, HR records and approvals are kept in Postgres |
| Outgoing email ports 465 and 587 are blocked | sending email (letters, replies, invitations, auto-reply) fails; reading Gmail works |
| Free Postgres is deleted 30 days after it is created | before then, create a new free database and point `DATABASE_URL` at it (data starts empty), or upgrade it |
| No browser on the server | "Sign in to Google" does not work there; Calendar uses AgentsMind's own calendar, Drive and Sheets are off |
| 0.1 CPU | answers are slower than on a laptop |

For everything to work (email sending, files that stay, always on), use a paid instance with a disk, or run it
on your own computer with Start-Public-Link.bat.
