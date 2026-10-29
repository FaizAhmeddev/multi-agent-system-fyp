"""Phase 5 quality checks, one command:

    python scripts/quality.py          coverage report (at least COVERAGE_MIN percent), bandit, pip-audit, secrets scan
    python scripts/quality.py --fast   skip pip-audit (needs network)

Run after the test suites (the gate runs them with coverage first). Exit code 1 if any check fails.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
COVERAGE_MIN = 60


def run(label: str, cmd: list[str]) -> bool:
    print(f"\n=== {label}: {' '.join(cmd)}", flush=True)
    code = subprocess.run(cmd, cwd=ROOT).returncode  # noqa: S603 - fixed argument lists
    print(f"=== {label}: {'ok' if code == 0 else f'FAILED (exit {code})'}", flush=True)
    return code == 0


def main() -> int:
    fast = "--fast" in sys.argv
    results = {
        # Combined over all suites (the gate runs them with --cov-append). Code that only runs inside
        # MCP and portal subprocesses is not counted, so the bar is set from the measured total.
        "coverage": run("coverage report", [PY, "-m", "coverage", "report", f"--fail-under={COVERAGE_MIN}"]),
        "bandit": run("bandit (medium and high)", [PY, "-m", "bandit", "-c", "pyproject.toml", "-r", "backend",
                                                   "mcp_servers", "external_systems", "scripts", "-ll", "-q"]),
        "secrets": run("secrets scan", [PY, "scripts/secrets_scan.py"]),
    }
    if not fast:
        results["pip-audit"] = run("pip-audit (installed packages)", [PY, "-m", "pip_audit", "--progress-spinner", "off",
                                                                     "--skip-editable"])
    print("\nQUALITY:", ", ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
