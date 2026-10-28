"""Add synthetic demo events to the sandbox calendar (never touches Google).

    python -m mcp_servers.calendar_mcp.seed
"""
from __future__ import annotations

import os

from mcp_servers.calendar_mcp.backends import SandboxCalendar
from mcp_servers.common import load_env

if __name__ == "__main__":
    load_env()
    cal = SandboxCalendar()
    n = cal.seed(os.environ.get("TIMEZONE", "Asia/Karachi"))
    print(f"calendar sandbox: {n} synthetic events added ({cal.path})")
