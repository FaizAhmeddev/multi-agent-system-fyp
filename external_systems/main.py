"""Start the external systems (separate apps, separate databases):

    python external_systems/main.py        (or double-click Start-External-Systems.bat)

  AgentsMind Finance Portal   http://127.0.0.1:8201   (payroll system: people and payments)
  AgentsMind IT Helpdesk      http://127.0.0.1:8202   (complaint tickets; public form at /)

AgentsMind's main.py also starts them; use this script to run them on their own.
AgentsMind reaches them only through finance-mcp and it-mcp. They share the repository's
.venv and .env with AgentsMind (run main.py once first, or this script sets them up).
With DEMO_MODE=false their sample records (example.com emails) are removed once;
with DEMO_MODE=true the sample records are added. Ctrl+C stops both.
"""
from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
_spec = importlib.util.spec_from_file_location("agentsmind_launcher", ROOT / "main.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)  # type: ignore[union-attr]

PORTALS = [
    ("finance-portal", "finance_portal.app:create_app", 8201, "Finance Portal"),
    ("it-portal", "it_portal.app:create_app", 8202, "IT Helpdesk"),
]
PIDS = L.DATA / "external.pids"


def demo_data() -> None:
    """Remove (DEMO_MODE=false) or add (true) the portals' sample records, once."""
    L.portal_demo_data(L.read_env())


def main() -> int:
    os.chdir(ROOT)
    if not L.in_venv():
        L.ensure_venv("--skip-install" in sys.argv)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        return subprocess.call([str(L.VPY), str(HERE / "main.py"), "--skip-install"])  # noqa: S603
    L.run([str(L.VPY), "scripts/env_setup.py"], quiet=True)
    demo_data()
    if PIDS.exists():
        for line in PIDS.read_text().split():
            if line.isdigit():
                L.kill_tree(int(line))
        PIDS.unlink(missing_ok=True)
    old = L.pids_on_ports((8201, 8202))
    for pid in old:
        L.kill_tree(pid)
    if old:
        time.sleep(2)
    L.step("Starting the external systems")
    procs = {}
    for name, app, port, _title in PORTALS:
        procs[name] = L.start(name, ["-m", "uvicorn", app, "--factory", "--app-dir", "external_systems", "--host",
                                     "127.0.0.1", "--port", str(port)], {})
    PIDS.write_text("\n".join(str(p.pid) for p in procs.values()))
    deadline = time.time() + 40
    up = set()
    while len(up) < len(PORTALS) and time.time() < deadline:
        for name, _app, port, title in PORTALS:
            if name not in up:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=1.5)  # noqa: S310
                    up.add(name)
                    L.say(f"  {title:15} http://127.0.0.1:{port}")
                except Exception:  # noqa: BLE001,S112 - not up yet
                    continue
        time.sleep(0.5)
    for name, _app, _port, title in PORTALS:
        if name not in up:
            L.say(f"  {title:15} NOT UP: see logs\\{name}.log")
    L.say("\nStaff sign-in for the portals: data\\local_credentials.txt\nPress Ctrl+C to stop them.")
    try:
        while True:
            time.sleep(2)
            for name, app, port, _t in PORTALS:
                if procs[name].poll() is not None:
                    L.say(f"  {name} stopped; restarting. See logs\\{name}.log")
                    procs[name] = L.start(name, ["-m", "uvicorn", app, "--factory", "--app-dir", "external_systems",
                                                 "--host", "127.0.0.1", "--port", str(port)], {})
                    time.sleep(3)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs.values():
            L.kill_tree(p.pid)
        PIDS.unlink(missing_ok=True)
        L.say("External systems stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
