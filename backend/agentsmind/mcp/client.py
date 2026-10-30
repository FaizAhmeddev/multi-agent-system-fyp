"""MCP client used by the core. External systems are reached ONLY through these calls.

Each call opens a Streamable HTTP session with the server's bearer token, calls one
tool, and returns its structured result. Read-only tools are retried with backoff;
write tools are never retried here (the gateway passes an idempotency key, so a retry
from a higher level cannot create duplicates).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from dataclasses import dataclass
from typing import Any

from ..agents.catalog import READ, TOOLS

log = logging.getLogger("agentsmind.mcp")


class MCPCallError(Exception):
    """The tool ran and reported an error, or the server could not be reached."""

    def __init__(self, message: str, *, code: str = "tool_error"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ServerConfig:
    name: str
    url: str
    token: str


def server_configs() -> dict[str, ServerConfig]:
    from ..settings import get_settings

    s = get_settings()
    out: dict[str, ServerConfig] = {}
    for name, url, tok in (("finance-mcp", s.finance_mcp_url, s.finance_mcp_token),
                           ("it-mcp", s.it_mcp_url, s.it_mcp_token),
                           ("calendar-mcp", s.calendar_mcp_url, s.calendar_mcp_token),
                           ("workspace-mcp", s.workspace_mcp_url, s.workspace_mcp_token)):
        if tok and tok.get_secret_value().strip():
            out[name] = ServerConfig(name, url, tok.get_secret_value().strip())
    return out


def _run(coro):
    """Run a coroutine from sync code, also when an event loop is already running in this thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


async def _call_async(cfg: ServerConfig, tool: str, args: dict[str, Any], timeout: float) -> dict[str, Any]:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {cfg.token}"},
                              timeout=httpx2.Timeout(timeout, connect=3.0))
    async with http, Client(streamable_http_client(cfg.url, http_client=http), read_timeout_seconds=timeout) as c:
        r = await c.call_tool(tool, args)
    if r.is_error:
        text = " ".join(getattr(b, "text", "") for b in r.content).strip()
        text = text.removeprefix(f"Error executing tool {tool}: ")
        raise MCPCallError(text or f"{tool} failed.")
    if r.structured_content is None:
        raise MCPCallError(f"{tool} returned no structured result.", code="bad_result")
    return dict(r.structured_content)


async def _list_async(cfg: ServerConfig, timeout: float) -> list[dict[str, Any]]:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {cfg.token}"},
                              timeout=httpx2.Timeout(timeout, connect=3.0))
    async with http, Client(streamable_http_client(cfg.url, http_client=http), read_timeout_seconds=timeout) as c:
        res = await c.list_tools()
    out = []
    for t in res.tools:
        a = t.annotations
        first_line = (t.description or "").strip().splitlines()[0] if t.description else ""
        out.append({"name": t.name, "description": first_line,
                    "read_only": bool(a and a.read_only_hint), "destructive": bool(a and a.destructive_hint),
                    "input_schema": t.input_schema, "output_schema": t.output_schema})
    return out


def _unwrap(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


SLOW_PREFIXES = ("gmail_", "cv_folder_", "sheets_", "drive_", "docs_", "whatsapp_", "email_")


def _timeout_for(tool: str, default: float) -> float:
    """Tools that talk to Gmail, Drive or Sheets (or read many CVs) get more time than local portal calls."""
    return max(default, 60.0) if tool.startswith(SLOW_PREFIXES) else default


def call_tool(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    from ..settings import get_settings

    spec = TOOLS[tool]
    cfg = server_configs().get(spec.server)
    if cfg is None:
        raise MCPCallError(f"{spec.server} is not configured (set its URL and token in .env).", code="not_configured")
    s = get_settings()
    attempts = 1 + (s.mcp_read_retries if spec.risk == READ else 0)
    last: BaseException | None = None
    for i in range(attempts):
        start = time.perf_counter()
        try:
            out = _run(_call_async(cfg, tool, args, _timeout_for(tool, s.mcp_timeout_seconds)))
            log.info("mcp call", extra={"tool": tool, "server": cfg.name, "status": "ok",
                                        "latency_ms": int((time.perf_counter() - start) * 1000)})
            return out
        except MCPCallError:
            raise  # the tool answered: retrying will not help
        except BaseException as exc:  # noqa: BLE001 - transport failures (connection, auth, timeout)
            last = _unwrap(exc)
            if isinstance(last, KeyboardInterrupt | SystemExit):
                raise
            log.warning("mcp call failed", extra={"tool": tool, "server": cfg.name, "attempt": i + 1,
                                                  "error": f"{type(last).__name__}: {last}"})
            if "Timeout" in type(last).__name__ and tool.startswith(SLOW_PREFIXES):
                break  # a slow external service: waiting another minute rarely helps
            if i + 1 < attempts:
                time.sleep(0.4 * (2 ** i))
    if _probe_status(cfg) == 401:
        raise MCPCallError(f"{cfg.name} rejected the token. Check {cfg.name.split('-')[0].upper()}_MCP_TOKEN.",
                           code="unauthorized")
    if "Timeout" in type(last).__name__:
        raise MCPCallError(f"{cfg.name} did not answer {tool} within {int(_timeout_for(tool, s.mcp_timeout_seconds))} "
                           "seconds (the external service was slow). Try again in a moment.", code="timeout")
    raise MCPCallError(f"{cfg.name} is not reachable at {cfg.url} ({type(last).__name__}). Start AgentsMind with "
                       "main.py (Start-AgentsMind.bat), which starts every part.", code="unreachable")


def _probe_status(cfg: ServerConfig) -> int | None:
    """After a failed call, find out whether the server is up but refused our token."""
    import httpx2

    try:
        r = httpx2.post(cfg.url, json={}, timeout=3.0, headers={
            "Authorization": f"Bearer {cfg.token}", "Accept": "application/json, text/event-stream"})
        return r.status_code
    except Exception:  # noqa: BLE001 - unreachable
        return None


def list_tools(server: str) -> list[dict[str, Any]]:
    from ..settings import get_settings

    cfg = server_configs().get(server)
    if cfg is None:
        raise MCPCallError(f"{server} is not configured.", code="not_configured")
    return _run(_list_async(cfg, get_settings().mcp_timeout_seconds))


def register_mcp_executors() -> list[str]:
    """Route every catalog tool of a configured MCP server through the MCP client."""
    from ..agents.gateway import register_executor

    configured = server_configs()
    names = []
    for name, spec in TOOLS.items():
        if spec.server in configured and spec.server != "core":
            def _exec(args: dict[str, Any], key: str, _tool: str = name) -> dict[str, Any]:
                a = dict(args)
                if key and "idempotency_key" in _WRITE_WITH_KEY.get(_tool, ()):
                    a["idempotency_key"] = key
                return call_tool(_tool, a)
            register_executor(name, _exec)
            names.append(name)
    return names


# Write tools whose MCP schema takes an idempotency key. The approval's key is passed through.
_WRITE_WITH_KEY = {
    "finance_create_person": ("idempotency_key",),
    "finance_update_person": ("idempotency_key",),
    "finance_delete_person": ("idempotency_key",),
    "it_create_ticket": ("idempotency_key",),
    "calendar_create_event": ("idempotency_key",),
    "calendar_update_event": ("idempotency_key",),
    "calendar_cancel_event": ("idempotency_key",),
    "gmail_send_email": ("idempotency_key",),
    "sheets_append": ("idempotency_key",),
    "drive_upload_file": ("idempotency_key",),
    "whatsapp_send": ("idempotency_key",),
    "payroll_enroll_employee": ("idempotency_key",),
    "payroll_end_employment": ("idempotency_key",),
    "payroll_record_payment": ("idempotency_key",),
}
