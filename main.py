"""Start AgentsMind on this computer:   python main.py      (or double-click Start-AgentsMind.bat)

First run (a few minutes, once):
  1. creates .venv and installs the pinned packages (re-installs only when requirements change)
  2. creates or completes .env with random secrets; your own values are never overwritten
  3. creates or upgrades the database, and removes old sample data when DEMO_MODE=false
  4. builds the web app if needed (Node.js 22)
  5. opens the Google sign-in once if a Google OAuth client file is configured
Every run: starts the MCP servers, the core API (web app at http://127.0.0.1:8000) and the queue
worker in this one window, opens the browser, restarts a part that crashes, and stops
everything when you press Ctrl+C or close the window.

The external systems (Finance Portal on 8201, IT Helpdesk on 8202) are separate apps with their own
databases. main.py starts them too, as separate processes, unless they are already running (for
example from Start-External-Systems.bat) or you pass --no-portals.

Options:  --no-browser   --no-google   --skip-install   --no-portals   --stop (stop a running AgentsMind)
          --public   also give a free public https link (Cloudflare Quick Tunnel; no account needed), so
                     others can open AgentsMind while this computer runs it
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"
VENV = ROOT / ".venv"
VPY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
DATA = ROOT / "data"
LOGS = ROOT / "logs"
PIDS = DATA / "agentsmind.pids"
REQS = ROOT / "requirements" / "servers.txt"
STAMP = VENV / ".agentsmind-requirements.sha256"
WEB = "http://127.0.0.1:8000"

PARTS = [
    ("finance-mcp", ["-m", "mcp_servers.finance_mcp.server"], {}, "http://127.0.0.1:8101/mcp"),
    ("it-mcp", ["-m", "mcp_servers.it_mcp.server"], {}, "http://127.0.0.1:8102/mcp"),
    ("calendar-mcp", ["-m", "mcp_servers.calendar_mcp.server"], {}, "http://127.0.0.1:8103/mcp"),
    ("workspace-mcp", ["-m", "mcp_servers.workspace_mcp.server"], {}, "http://127.0.0.1:8104/mcp"),
    ("core-api", ["-m", "uvicorn", "agentsmind.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port",
                  "8000"], {}, f"{WEB}/health"),
    ("worker", ["-m", "agentsmind.queue.worker"], {"PYTHONPATH": "backend"}, None),
]
PORTALS = [
    ("finance-portal", ["-m", "uvicorn", "finance_portal.app:create_app", "--factory", "--app-dir", "external_systems",
                        "--host", "127.0.0.1", "--port", "8201"], {}, "http://127.0.0.1:8201/api/v1/health"),
    ("it-portal", ["-m", "uvicorn", "it_portal.app:create_app", "--factory", "--app-dir", "external_systems",
                   "--host", "127.0.0.1", "--port", "8202"], {}, "http://127.0.0.1:8202/api/v1/health"),
]


def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(msg: str) -> None:
    say(f"\n>>> {msg}")


def run(cmd: list[str], *, check: bool = True, env: dict[str, str] | None = None, quiet: bool = False) -> int:
    e = {**os.environ, **(env or {})}
    r = subprocess.run(cmd, cwd=ROOT, env=e, stdout=subprocess.DEVNULL if quiet else None)  # noqa: S603
    if check and r.returncode != 0:
        raise SystemExit(f"Failed: {' '.join(cmd)} (exit {r.returncode}). See the messages above.")
    return r.returncode


# ---------------------------------------------------------------------------- 1. Python and packages

def ensure_venv(skip_install: bool) -> None:
    if sys.version_info[:2] not in ((3, 11), (3, 12), (3, 13)):
        say(f"Note: Python {sys.version.split()[0]} found; AgentsMind is tested with 3.11 and 3.12.")
    if not VPY.exists():
        step("Creating the Python environment (.venv)")
        run([sys.executable, "-m", "venv", str(VENV)])
    if skip_install:
        return
    want = hashlib.sha256(b"".join(p.read_bytes() for p in sorted((ROOT / "requirements").glob("*.txt")))).hexdigest()
    if STAMP.exists() and STAMP.read_text().strip() == want:
        return
    step("Installing packages (first run or after an update; a few minutes)")
    run([str(VPY), "-m", "pip", "install", "--upgrade", "pip", "--quiet"], check=False)
    run([str(VPY), "-m", "pip", "install", "setuptools==84.1.0", "--quiet"], check=False)
    run([str(VPY), "-m", "pip", "install", "-r", str(REQS)])
    STAMP.write_text(want)


def in_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == VPY.resolve()
    except OSError:
        return False


# ---------------------------------------------------------------------------- 2-5. setup

def setup(no_google: bool) -> dict[str, str]:
    step("Settings (.env)")
    run([str(VPY), "scripts/env_setup.py"])
    env = read_env()
    step("Database")
    run([str(VPY), "-m", "alembic", "upgrade", "head"])
    run([str(VPY), "scripts/demo_data.py", "--auto"], check=False)
    build_web()
    if not no_google:
        google_signin(env)
    return env


def portal_demo_data(env: dict[str, str]) -> None:
    """Remove (DEMO_MODE=false) or add (true) the external systems' sample records, once."""
    demo = env.get("DEMO_MODE", "false").lower() in ("1", "true", "yes")
    mark = DATA / (".demo_external_seeded" if demo else ".demo_external_purged")
    if mark.exists():
        return
    DATA.mkdir(exist_ok=True)
    ext = ROOT / "external_systems"
    if demo:
        for seed in ("finance_portal/seed.py", "it_portal/seed.py"):
            run([str(VPY), str(ext / seed)], check=False)
    else:
        run([str(VPY), str(ext / "demo_cleanup.py")], check=False)
    mark.write_text("done\n")


def read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    p = ROOT / ".env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def build_web() -> None:
    fe = ROOT / "frontend"
    dist = fe / "dist" / "index.html"
    src_mtime = max((p.stat().st_mtime for p in (fe / "src").rglob("*") if p.is_file()), default=0)
    if dist.exists() and dist.stat().st_mtime >= src_mtime:
        return
    npm = shutil.which("npm.cmd" if IS_WIN else "npm") or shutil.which("npm")
    if not npm:
        if dist.exists():
            say("Note: the web app sources changed but Node.js is not installed, so the old build is used.")
            return
        raise SystemExit("The web app is not built and Node.js is not installed. Install Node.js 22 LTS from "
                         "https://nodejs.org and run main.py again.")
    step("Building the web app")
    lock = (fe / "package-lock.json").exists()
    if not (fe / "node_modules").is_dir() or lock and (fe / "package-lock.json").stat().st_mtime > (
            fe / "node_modules").stat().st_mtime:
        subprocess.run([npm, "ci" if lock else "install", "--no-audit", "--no-fund"], cwd=fe, check=True)  # noqa: S603
    if subprocess.run([npm, "run", "build"], cwd=fe).returncode != 0:  # noqa: S603 - type check + bundle
        say("The type check reported problems (see above); building without it so AgentsMind can start.")
        npx = shutil.which("npx.cmd" if IS_WIN else "npx") or "npx"
        r = subprocess.run([npx, "vite", "build"], cwd=fe)  # noqa: S603
        if r.returncode != 0 and not dist.exists():
            raise SystemExit("The web app could not be built. See the messages above.")


def google_signin(env: dict[str, str]) -> None:
    client = Path(env.get("GOOGLE_OAUTH_CLIENT_FILE") or "secrets/google_oauth_client.json")
    client = client if client.is_absolute() else ROOT / client
    token = DATA / "google_token.enc"
    if not client.is_file():
        say("Google: no OAuth client file yet (Calendar, Drive and Sheets stay local). See docs/DEPLOYMENT.md.")
        return
    need = run([str(VPY), "-c", "import sys; sys.path.insert(0, '.'); from mcp_servers.common import load_env; "
                                "load_env(); from mcp_servers.google_common import status; s = status(); "
                                "sys.exit(0 if s['signed_in'] and not s['missing'] else 3)"], check=False, quiet=True)
    if need == 0:
        return
    step("Google sign-in (once): a browser window opens; sign in and allow access")
    if not token.exists():
        say("This gives AgentsMind access to your Calendar, Drive (read, plus files it creates) and Sheets.")
    rc = run([str(VPY), "scripts/google_oauth.py"], check=False)
    if rc != 0:
        say("Google sign-in did not finish. AgentsMind still runs; sign in later from Settings > Connections.")


# ---------------------------------------------------------------------------- 6. run everything

def port_open(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=1.5)  # noqa: S310 - fixed local URLs
        return True
    except urllib.error.HTTPError:
        return True  # the server answered (e.g. 401 without a token)
    except Exception:  # noqa: BLE001 - not up yet
        return False


def kill_tree(pid: int) -> None:
    if IS_WIN:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)  # noqa: S603,S607
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass


PORTS = (8000, 8101, 8102, 8103, 8104)


def pids_on_ports(ports: tuple[int, ...]) -> set[int]:
    """Processes listening on AgentsMind ports (for example an older version still running)."""
    out: set[int] = set()
    try:
        if IS_WIN:
            r = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=15)  # noqa: S603,S607
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].rsplit(":", 1)[-1].isdigit():
                    if int(parts[1].rsplit(":", 1)[-1]) in ports and parts[4].isdigit() and int(parts[4]) > 0:
                        out.add(int(parts[4]))
        else:
            for port in ports:
                r = subprocess.run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True)  # noqa: S603,S607
                out |= {int(x) for x in r.stdout.split() if x.isdigit()}
    except (OSError, subprocess.SubprocessError):
        pass
    return out - {os.getpid()}


def stop_previous(ports: tuple[int, ...] = PORTS) -> None:
    for f in (PIDS, DATA / "run_all.pids"):  # this launcher's, and the old run_all.ps1 windows
        if f.exists():
            for line in f.read_text(errors="replace").split():
                if line.isdigit():
                    kill_tree(int(line))
            f.unlink(missing_ok=True)
            time.sleep(1)
    left = pids_on_ports(ports)
    if left:
        say(f"Stopping an older AgentsMind still using its ports (process {', '.join(map(str, sorted(left)))}).")
        for pid in left:
            kill_tree(pid)
        for _ in range(20):
            if not pids_on_ports(ports):
                break
            time.sleep(0.5)
        still = pids_on_ports(ports)
        if still:
            raise SystemExit(f"Ports {', '.join(map(str, ports))} are still in use by process(es) {sorted(still)}. "
                             "Close the other AgentsMind windows (or restart the computer) and start again.")


def start(name: str, args: list[str], extra: dict[str, str]) -> subprocess.Popen:
    LOGS.mkdir(exist_ok=True)
    log = open(LOGS / f"{name}.log", "a", encoding="utf-8")  # noqa: SIM115 - kept open for the child's lifetime
    log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} start {name}\n")
    log.flush()
    kw: dict = {}
    if IS_WIN:
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    env = {**os.environ, "PYTHONUNBUFFERED": "1", **extra}
    return subprocess.Popen([str(VPY), *args], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, **kw)  # noqa: S603


def last_error(name: str) -> str:
    """The most useful line from the end of a part's log (the error, not the shutdown chatter)."""
    f = LOGS / f"{name}.log"
    if not f.is_file():
        return ""
    lines = [x.strip() for x in f.read_text(encoding="utf-8", errors="replace").splitlines()[-60:] if x.strip()]
    for x in reversed(lines):
        if any(k in x for k in ("Error", "error", "Refusing", "Traceback", "Exception", "refused")):
            return x[:300]
    return lines[-1][:300] if lines else ""


# ---------------------------------------------------------------------------- free public link

TOOLS = ROOT / "tools"
CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/" + (
    "cloudflared-windows-amd64.exe" if IS_WIN else "cloudflared-linux-amd64")
PUBLIC_FILE = DATA / "public_url.txt"


def cloudflared() -> Path:
    """Cloudflare's tunnel program (downloaded once into tools/)."""
    found = shutil.which("cloudflared")
    if found:
        return Path(found)
    exe = TOOLS / ("cloudflared.exe" if IS_WIN else "cloudflared")
    if not exe.exists():
        step("Downloading Cloudflare's tunnel program (once, about 40 MB)")
        TOOLS.mkdir(exist_ok=True)
        tmp = exe.with_suffix(".part")
        try:
            urllib.request.urlretrieve(CLOUDFLARED_URL, tmp)  # noqa: S310 - fixed official release URL
        except Exception as exc:  # noqa: BLE001 - explained to the user
            raise SystemExit(f"Could not download cloudflared ({exc}). Download it from {CLOUDFLARED_URL}, save it as "
                             f"{exe} and start again.") from exc
        tmp.replace(exe)
        if not IS_WIN:
            exe.chmod(0o755)
    return exe


def public_link(procs: dict[str, subprocess.Popen]) -> str:
    """Start a Cloudflare Quick Tunnel to the web app and return its https address."""
    import re

    exe = cloudflared()
    LOGS.mkdir(exist_ok=True)
    logf = LOGS / "public-link.log"
    log = open(logf, "w", encoding="utf-8")  # noqa: SIM115 - kept open for the child's lifetime
    kw: dict = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WIN else {"start_new_session": True}
    procs["public-link"] = subprocess.Popen([str(exe), "tunnel", "--no-autoupdate", "--url", WEB],  # noqa: S603
                                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, **kw)
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(1)
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", logf.read_text(encoding="utf-8", errors="replace"))
        if m:
            PUBLIC_FILE.write_text(m.group(0) + "\n")
            return m.group(0)
        if procs["public-link"].poll() is not None:
            break
    return ""


def status_line(env: dict[str, str]) -> None:
    llm = "connected" if env.get("OPENAI_API_KEY") else "not set (answers are labeled Simulated)"
    mail = f"{env.get('GMAIL_EMAIL')} (app password)" if env.get("GMAIL_EMAIL") and env.get("GMAIL_APP_PASSWORD") \
        else "not connected"
    google = "signed in" if (DATA / "google_token.enc").exists() else "not signed in"
    wa = "connected" if env.get("TWILIO_ACCOUNT_SID") and env.get("TWILIO_AUTH_TOKEN") else "not connected"
    say(f"  OpenAI: {llm}\n  Gmail: {mail}\n  Google Calendar/Drive/Sheets: {google}\n  WhatsApp: {wa}\n"
        f"  Sample data: {'on' if env.get('DEMO_MODE', '').lower() in ('1', 'true', 'yes') else 'off'}")


def serve(env: dict[str, str], open_browser: bool, portals: bool = True, public: bool = False) -> None:
    stop_previous()
    parts = list(PARTS)
    if portals:
        portal_demo_data(env)
        running = [p for p in PORTALS if port_open(p[3])]
        for p in running:
            say(f"  {p[0]:14} already running (started separately)")
        if not running:  # an old portal process that does not answer is stopped first
            old = pids_on_ports((8201, 8202))
            for pid in old:
                kill_tree(pid)
            if old:
                time.sleep(2)
        parts = [p for p in PORTALS if p not in running] + parts
    step("Starting AgentsMind")
    procs: dict[str, subprocess.Popen] = {}
    restarts: dict[str, int] = {}
    for name, args, extra, _ in parts:
        procs[name] = start(name, args, extra)
        time.sleep(0.6)
    DATA.mkdir(exist_ok=True)
    PIDS.write_text("\n".join(str(p.pid) for p in procs.values()))
    deadline = time.time() + 60
    pending = {n: url for n, _, _, url in parts if url}
    while pending and time.time() < deadline:
        for n in list(pending):
            if procs[n].poll() is not None:  # our process exited: never count another program's port as ours
                break
            if port_open(pending[n]):
                say(f"  {n:14} up")
                pending.pop(n)
        if any(procs[n].poll() is not None for n in pending):
            break
        time.sleep(0.5)
    for n in pending:
        say(f"  {n:14} NOT UP: {last_error(n) or 'see logs'}  (logs\\{n}.log)")
    for name, _a, _e, _u in parts:
        if procs[name].poll() is not None and name not in pending:
            say(f"  {name:14} STOPPED: {last_error(name)}")
    fp = env.get("FINANCE_PORTAL_URL", "http://127.0.0.1:8201")
    if not port_open(f"{fp}/api/v1/health"):
        say("  Finance Portal and IT Helpdesk are not running: start Start-External-Systems.bat (or run main.py "
            "without --no-portals) for payroll and IT tickets.")
    say("")
    status_line(env)
    say(f"\nAgentsMind is running: {WEB}\n  Finance Portal: http://127.0.0.1:8201   IT Helpdesk: "
        "http://127.0.0.1:8202\nSign-in details: data\\local_credentials.txt\n"
        "Logs: logs\\<part>.log\nPress Ctrl+C (or close this window) to stop everything.")
    if public and "core-api" not in pending:
        url = public_link(procs)
        PIDS.write_text("\n".join(str(p.pid) for p in procs.values()))
        if url:
            say("\n" + "=" * 70 + f"\n  PUBLIC LINK (share it):  {url}\n" + "=" * 70)
            say("  Anyone with this link sees the AgentsMind sign-in page. It works while this window is open,\n"
                "  and a new link is made each time you start. Saved in data\\public_url.txt.")
            if (env.get("AGENTSMIND_ADMIN_PASSWORD") or "") in ("", "Correct-Horse-Battery-42", "admin", "password"):
                say("  WARNING: change the admin password first (scripts\\set_admin.py or Settings > Change password).")
        else:
            say(f"  Public link: could not start. See logs\\public-link.log. AgentsMind still runs at {WEB}")
    if open_browser and "core-api" not in pending:
        webbrowser.open(WEB)
    try:
        while True:
            time.sleep(2)
            for name, args, extra, _ in parts:
                p = procs[name]
                if p.poll() is not None:
                    restarts[name] = restarts.get(name, 0) + 1
                    if restarts[name] > 3:
                        if restarts[name] == 4:
                            say(f"  {name} keeps stopping; not restarting it again. Reason: {last_error(name)}")
                        continue
                    say(f"  {name} stopped (exit {p.returncode}): {last_error(name)}  Restarting ({restarts[name]} "
                        "of 3).")
                    procs[name] = start(name, args, extra)
                    PIDS.write_text("\n".join(str(x.pid) for x in procs.values()))
    except KeyboardInterrupt:
        pass
    finally:
        say("\nStopping AgentsMind...")
        for p in procs.values():
            kill_tree(p.pid)
        PIDS.unlink(missing_ok=True)
        say("Stopped.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Start AgentsMind")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-google", action="store_true")
    ap.add_argument("--skip-install", action="store_true")
    ap.add_argument("--no-portals", action="store_true", help="do not start the Finance Portal and IT Helpdesk")
    ap.add_argument("--public", action="store_true", help="also make a free public https link (Cloudflare)")
    ap.add_argument("--stop", action="store_true", help="stop a running AgentsMind")
    a = ap.parse_args()
    os.chdir(ROOT)
    if a.stop:
        stop_previous()
        say("Stopped.")
        return 0
    if in_venv():
        ensure_venv(a.skip_install)  # started with the .venv Python (e.g. VS Code): still install new packages
    else:
        ensure_venv(a.skip_install)
        # Continue inside .venv so every import uses the pinned packages. Ctrl+C reaches both processes;
        # this one ignores it and waits, so the inner one can stop every part cleanly.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        args = [x for x in sys.argv[1:] if x != "--skip-install"]
        return subprocess.call([str(VPY), str(ROOT / "main.py"), "--skip-install", *args])  # noqa: S603
    env = setup(a.no_google)
    serve(env, not a.no_browser, not a.no_portals, a.public)
    return 0


if __name__ == "__main__":
    sys.exit(main())
