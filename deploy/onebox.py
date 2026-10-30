"""All of AgentsMind in ONE process, for small hosts such as Render's free plan (512 MB).

    python deploy/onebox.py            (the Docker image runs this)

On a laptop main.py starts 8 programs (core API, worker, 4 MCP servers, 2 portals). Here the same apps run
inside one uvicorn server on $PORT, each under its own path, and talk to each other over HTTP on 127.0.0.1
exactly as before (MCP over Streamable HTTP with bearer tokens, portals over their REST API with API keys):

    /                       the web app and core API
    /_mcp/finance/mcp       finance-mcp        /_mcp/it/mcp         it-mcp
    /_mcp/calendar/mcp      calendar-mcp       /_mcp/workspace/mcp  workspace-mcp
    /_portal/finance        Finance Portal     /_portal/it          IT Helpdesk

The MCP endpoints accept only requests addressed to 127.0.0.1 (DNS-rebinding protection) with the right
token, so they are not usable from outside even though they share the port. The queue worker and the
auto-reply checker run as background threads.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("PORT", "10000"))
LOCAL = f"http://127.0.0.1:{PORT}"
MCPS = {"finance": "FINANCE", "it": "IT", "calendar": "CALENDAR", "workspace": "WORKSPACE"}


def prepare_env() -> None:
    """Internal addresses and per-start secrets; the host's environment variables always win."""
    os.chdir(ROOT)
    for p in (ROOT / "backend", ROOT, ROOT / "external_systems"):
        sys.path.insert(0, str(p))
    if not (ROOT / ".env").exists():
        subprocess.run([sys.executable, "scripts/env_setup.py"], cwd=ROOT, check=False,  # noqa: S603
                       stdout=subprocess.DEVNULL)
    env = os.environ
    for short, prefix in MCPS.items():
        env[f"{prefix}_MCP_URL"] = f"{LOCAL}/_mcp/{short}/mcp"
        env[f"{prefix}_MCP_HOST"] = "127.0.0.1"
        env[f"{prefix}_MCP_PORT"] = str(PORT)
        env.setdefault(f"{prefix}_MCP_TOKEN", secrets.token_urlsafe(32))
    env["FINANCE_PORTAL_URL"] = f"{LOCAL}/_portal/finance"
    env["IT_PORTAL_URL"] = f"{LOCAL}/_portal/it"
    for k in ("FINANCE_PORTAL_API_KEY", "IT_PORTAL_API_KEY"):
        env.setdefault(k, secrets.token_urlsafe(32))
    for k in ("FINANCE_PORTAL_SECRET_KEY", "IT_PORTAL_SECRET_KEY"):
        env.setdefault(k, secrets.token_urlsafe(48))
    env.setdefault("CALENDAR_MODE", "auto")
    db = env.get("DATABASE_URL", "")
    if db.startswith("postgresql://"):
        env["DATABASE_URL"] = "postgresql+psycopg://" + db[len("postgresql://"):]


def migrate() -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True)  # noqa: S603
    email, pw = os.environ.get("AGENTSMIND_ADMIN_EMAIL", ""), os.environ.get("AGENTSMIND_ADMIN_PASSWORD", "")
    if email and pw:  # set on the host (Render > Environment): that is the admin sign-in, also after a change
        r = subprocess.run([sys.executable, "scripts/set_admin.py", "--email", email.strip(),  # noqa: S603
                            "--password", pw.strip(), "--if-changed", "--allow-weak"], cwd=ROOT, check=False)
        print(f"ADMIN SIGN-IN: {email.strip().lower()} with the password set in AGENTSMIND_ADMIN_PASSWORD"
              + ("" if r.returncode == 0 else " (NOT applied, see the message above)"), flush=True)
    else:
        print("AGENTSMIND_ADMIN_EMAIL and AGENTSMIND_ADMIN_PASSWORD are not set in the host's environment, so a "
              "random admin password was generated. Set both and redeploy to choose the admin sign-in.", flush=True)
    subprocess.run([sys.executable, "scripts/demo_data.py", "--auto"], cwd=ROOT, check=False)  # noqa: S603
    subprocess.run([sys.executable, "external_systems/demo_cleanup.py"], cwd=ROOT, check=False,  # noqa: S603
                   stdout=subprocess.DEVNULL)


def build_app():
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.routing import Mount

    subs = []
    routes = []
    for short in MCPS:
        mod = __import__(f"mcp_servers.{short}_mcp.server", fromlist=["server"])
        sec = TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                        allowed_hosts=[f"127.0.0.1:{PORT}", f"localhost:{PORT}"],
                                        allowed_origins=[LOCAL, f"http://localhost:{PORT}"])
        app = mod.server.streamable_http_app(streamable_http_path="/mcp", transport_security=sec,
                                             host="127.0.0.1")
        subs.append(app)
        routes.append(Mount(f"/_mcp/{short}", app=app))
    from finance_portal.app import create_app as finance_app
    from it_portal.app import create_app as it_app

    for path, factory in (("/_portal/finance", finance_app), ("/_portal/it", it_app)):
        app = factory()
        subs.append(app)
        routes.append(Mount(path, app=app))
    from agentsmind.main import create_app as core_app

    core = core_app()
    subs.append(core)
    routes.append(Mount("/", app=core))

    @asynccontextmanager
    async def lifespan(_app):
        async with AsyncExitStack() as stack:
            for sub in subs:  # mounted apps do not get their own start-up otherwise
                await stack.enter_async_context(sub.router.lifespan_context(sub))
            start_worker()
            yield

    return Starlette(routes=routes, lifespan=lifespan)


def start_worker() -> None:
    from agentsmind.queue import handlers  # noqa: F401 - registers the built-in task handlers
    from agentsmind.queue.worker import Worker

    w = Worker(queue="default")
    threading.Thread(target=w.run_forever, name="queue-worker", daemon=True).start()


def main() -> None:
    prepare_env()
    migrate()
    import uvicorn

    uvicorn.run(build_app(), host="0.0.0.0", port=PORT, proxy_headers=True, forwarded_allow_ips="*",  # noqa: S104
                log_level="info", timeout_keep_alive=30)


if __name__ == "__main__":
    main()
