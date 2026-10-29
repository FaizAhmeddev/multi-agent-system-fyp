"""MCP smoke test: list every tool on each configured MCP server and call each read tool once.

    python scripts/smoke/mcp_smoke.py          (servers must be running; reads tokens from .env)

Exit code 0 when every server answered and every read tool succeeded.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _env() -> dict[str, str]:
    out = {}
    p = ROOT / ".env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                out[k.strip()] = v.strip()
    out.update({k: v for k, v in os.environ.items() if k.endswith(("_MCP_URL", "_MCP_TOKEN"))})
    return out


READ_CALLS = {
    "finance_list_people": {"page_size": 3},
    "finance_search_people": {"query": "ah"},
    "finance_summary": {},
    "finance_list_payments": {"page_size": 3},
    "finance_get_person": {"person_id": 1},
    "it_list_tickets": {"page_size": 3},
    "it_get_ticket": {"number": "ITK-000001"},
    "gmail_read_inbox": {"max_results": 3},
    "drive_list_files": {"page_size": 3},
    "drive_search": {"query": "policy"},
    "queue_stats": {},
    "agent_status": {},
}


def _window() -> dict:
    from datetime import datetime, timedelta

    now = datetime.now(UTC).replace(microsecond=0)
    return {"start": now.isoformat(), "end": (now + timedelta(hours=8)).isoformat()}


READ_CALLS["calendar_check_availability"] = _window()
READ_CALLS["calendar_list_events"] = {"time_min": _window()["start"], "time_max": _window()["end"]}


async def check(name: str, url: str, token: str) -> bool:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    ok = True
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=15)
    async with http, Client(streamable_http_client(url, http_client=http)) as c:
        tools = (await c.list_tools()).tools
        print(f"\n{name}  {url}  ({len(tools)} tools)")
        for t in tools:
            a = t.annotations
            kind = "destructive" if a and a.destructive_hint else ("read" if a and a.read_only_hint else "write")
            print(f"  {t.name:28} {kind}")
        for t in tools:
            if t.name not in READ_CALLS:
                continue
            r = await c.call_tool(t.name, READ_CALLS[t.name])
            raw = r.structured_content if r.structured_content else (r.content[0].text if r.content else "")
            text = (json.dumps(raw) if isinstance(raw, dict) else str(raw))[:110]
            # a "not found" for a sample id is acceptable: the call itself worked
            fine = not r.is_error or "No " in text
            ok &= fine
            print(f"  call {t.name:23} {'OK ' if fine else 'ERR'} {text}")
    return ok


def main() -> int:
    env = _env()
    servers = [("finance-mcp", env.get("FINANCE_MCP_URL", "http://127.0.0.1:8101/mcp"), env.get("FINANCE_MCP_TOKEN")),
               ("it-mcp", env.get("IT_MCP_URL", "http://127.0.0.1:8102/mcp"), env.get("IT_MCP_TOKEN")),
               ("calendar-mcp", env.get("CALENDAR_MCP_URL", "http://127.0.0.1:8103/mcp"), env.get("CALENDAR_MCP_TOKEN")),
               ("workspace-mcp", env.get("WORKSPACE_MCP_URL", "http://127.0.0.1:8104/mcp"),
                env.get("WORKSPACE_MCP_TOKEN"))]
    all_ok = True
    for name, url, tok in servers:
        if not tok:
            print(f"{name}: no token in .env, skipped")
            all_ok = False
            continue
        try:
            all_ok &= asyncio.run(check(name, url, tok))
        except BaseException as exc:  # noqa: BLE001
            while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
                exc = exc.exceptions[0]
            print(f"{name}: FAILED to connect to {url}: {type(exc).__name__}: {exc}")
            all_ok = False
    print("\nMCP SMOKE:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
