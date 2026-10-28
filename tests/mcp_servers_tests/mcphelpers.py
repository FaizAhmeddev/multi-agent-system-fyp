"""Start an MCP server module as a real process and call it over Streamable HTTP."""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx2

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start(module: str, env_extra: dict[str, str], log_path: Path, port: int) -> subprocess.Popen:
    env = dict(os.environ, **env_extra)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")])
    log = open(log_path, "w")  # noqa: SIM115 - closed when the process ends
    p = subprocess.Popen([sys.executable, "-m", module], cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    end = time.time() + 30
    while time.time() < end:
        if p.poll() is not None:
            raise RuntimeError(log_path.read_text())
        try:
            if httpx2.get(f"http://127.0.0.1:{port}/mcp", timeout=1).status_code in (401, 405, 406):
                return p
        except Exception:  # noqa: BLE001 - not up yet
            time.sleep(0.3)
    p.kill()
    raise RuntimeError(log_path.read_text())


def call(url: str, token: str, tool: str, args: dict | None):
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    async def go():
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
            async with Client(streamable_http_client(url, http_client=http)) as c:
                if tool == "__list__":
                    return await c.list_tools()
                return await c.call_tool(tool, args or {})

    return asyncio.run(go())
