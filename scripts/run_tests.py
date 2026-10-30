"""Run every AgentsMind test and write one report:  python scripts/run_tests.py

Installs the test tools into .venv the first time (requirements/dev.txt), then runs the
backend, portals, MCP servers, assistant and characterization suites, the frontend type
check, and writes everything to logs/test-report.txt (send that file to whoever fixes bugs).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "logs" / "test-report.txt"
VPY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SUITES = ["tests/assistant", "tests/backend", "tests/portals", "tests/mcp_servers_tests", "tests/characterization"]


def main() -> int:
    if not VPY.exists():
        print("Run main.py once first (it creates .venv).")
        return 1
    if Path(sys.executable).resolve() != VPY.resolve():
        return subprocess.call([str(VPY), __file__, *sys.argv[1:]])  # noqa: S603
    REPORT.parent.mkdir(exist_ok=True)
    out = open(REPORT, "w", encoding="utf-8")  # noqa: SIM115

    def log(s: str) -> None:
        print(s, flush=True)
        out.write(s + "\n")
        out.flush()

    def run(title: str, cmd: list[str], cwd: Path = ROOT, env: dict | None = None) -> int:
        log(f"\n===== {title}\n$ {' '.join(cmd)}")
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,  # noqa: S603
                             encoding="utf-8", errors="replace", env={**os.environ, **(env or {})})
        for line in p.stdout:  # type: ignore[union-attr]
            out.write(line)
            print(line, end="", flush=True)
        rc = p.wait()
        log(f"[exit {rc}] {title}")
        return rc

    log(f"AgentsMind test report {time.strftime('%Y-%m-%d %H:%M:%S')}  python {sys.version.split()[0]}")
    run("git", ["git", "log", "--oneline", "-1"])
    if run("install test tools", [str(VPY), "-m", "pip", "install", "-q", "-r", "requirements/dev.txt"]) != 0:
        log("Could not install the test tools; the tests below may fail to start.")
    failed = []
    for s in SUITES:
        if (ROOT / s).is_dir():
            rc = run(f"pytest {s}", [str(VPY), "-m", "pytest", s, "-q", "-rfE", "--timeout", "300", "-p",
                                     "no:cacheprovider"])
            if rc not in (0, 5):
                failed.append(s)
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    if npm:
        if run("frontend type check", [npm, "run", "typecheck"], cwd=ROOT / "frontend") != 0:
            failed.append("frontend typecheck")
    log("\n===== SUMMARY")
    log("ALL PASSED" if not failed else "FAILED: " + ", ".join(failed))
    log(f"Report: {REPORT}")
    out.close()
    if os.name == "nt" and "--no-pause" not in sys.argv:
        input("\nPress Enter to close.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
