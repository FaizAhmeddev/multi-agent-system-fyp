"""Connector hub: plug in ANY MCP server (Slack, WhatsApp, GitHub, Notion, a job board, ...) without code changes.

A connector is one entry in data/connectors.json (edited from Settings > Connectors or by hand):

    {
      "name": "slack",                       short id; its tools are called "slack.<tool>"
      "title": "Slack",
      "enabled": true,
      "transport": "stdio",                  "stdio" (a program, e.g. npx/uvx/python) or "http" (a URL)
      "command": "npx", "args": ["-y", "@modelcontextprotocol/server-slack"],
      "env": {"SLACK_BOT_TOKEN": "${SLACK_BOT_TOKEN}"},          values like ${NAME} come from .env
      "url": "https://example.com/mcp", "headers": {"Authorization": "Bearer ${MY_TOKEN}"},
      "roles": ["hr", "it", "finance", "employee"],             who may use it (admin always may)
      "keywords": ["slack", "channel"],                          words that send a request to it
      "read_tools": [], "write_tools": [], "blocked_tools": [],  optional overrides
      "description": "Read and post Slack messages"
    }

What happens:
  1. discovery: AgentsMind connects, lists the server's tools (MCP tools/list) and registers each one in the
     tool catalog as "<connector>.<tool>", with its risk taken from the server's MCP annotations
     (readOnlyHint -> read, destructiveHint -> destructive, otherwise write) unless overridden.
  2. safety: every call still goes through the tool gateway: role check, per-agent allow-list, and an
     approval card for every write. Blocked tools are never registered.
  3. sessions: one long-lived MCP session per connector, kept in a background event loop (a stdio server is
     started once, not per call) and reopened automatically if it stops.
Secrets never go into connectors.json: write ${NAME} and put NAME=value in .env.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agents.catalog import AGENT_TOOLS, DESTRUCTIVE, READ, TOOLS, WRITE, ToolSpec
from ..rbac import STAFF_ROLES

log = logging.getLogger("agentsmind.connectors")

AGENT = "connectors"  # the assistant agent that uses connector tools
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")
READ_PREFIXES = ("get_", "list_", "search_", "read_", "fetch_", "find_", "query_", "describe_", "lookup_", "view_")
DISCOVERY_TTL = 300.0


REPO_ROOT = Path(__file__).resolve().parents[3]


def config_path() -> Path:
    base = Path(os.environ.get("WORKSPACE_DATA_DIR") or REPO_ROOT / "data")
    return Path(os.environ.get("CONNECTORS_FILE") or base / "connectors.json")


@dataclass
class Connector:
    name: str
    title: str = ""
    enabled: bool = True
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    roles: list[str] = field(default_factory=lambda: sorted(STAFF_ROLES))
    keywords: list[str] = field(default_factory=list)
    read_tools: list[str] = field(default_factory=list)
    write_tools: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    guess_read_by_name: bool = True
    description: str = ""
    timeout_seconds: float = 60.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Connector:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        c = cls(**known)
        c.name = c.name.strip().lower()
        if not NAME_RE.match(c.name):
            raise ValueError(f"Connector name '{c.name}' must be 2-31 lowercase letters, digits, - or _.")
        if c.transport not in ("stdio", "http"):
            raise ValueError(f"{c.name}: transport must be 'stdio' or 'http'.")
        if c.transport == "stdio" and not c.command:
            raise ValueError(f"{c.name}: a stdio connector needs a command (for example npx, uvx or python).")
        if c.transport == "http" and not re.match(r"^https?://", c.url):
            raise ValueError(f"{c.name}: an http connector needs a URL starting with http:// or https://.")
        c.title = c.title or c.name.replace("-", " ").title()
        c.keywords = [k.lower() for k in (c.keywords or [c.name])]
        return c

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    def tool_name(self, tool: str) -> str:
        return f"{self.name}.{tool}"


# ---------------------------------------------------------------------------- config file

_loaded: dict[str, Any] = {"key": None, "items": []}


def load() -> list[Connector]:
    p = config_path()
    if not p.is_file():
        return []
    key = (str(p), p.stat().st_mtime_ns)
    if _loaded["key"] == key:
        return list(_loaded["items"])
    items = _load(p)
    _loaded.update(key=key, items=items)
    return list(items)


def _load(p: Path) -> list[Connector]:
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("connectors.json could not be read", extra={"error": str(exc)})
        return []
    out = []
    for d in raw.get("connectors", []) if isinstance(raw, dict) else []:
        try:
            out.append(Connector.from_dict(d))
        except (TypeError, ValueError) as exc:
            log.error("connector skipped", extra={"error": str(exc)})
    return out


def save(conns: list[Connector]) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"connectors": [c.to_dict() for c in conns]}, indent=2), encoding="utf-8")
    tmp.replace(p)


def get(name: str) -> Connector | None:
    return next((c for c in load() if c.name == name), None)


_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_dotenv: dict[str, Any] = {"key": None, "values": {}}


def env_file() -> Path | None:
    f = os.environ.get("AGENTSMIND_ENV_FILE", str(REPO_ROOT / ".env"))
    return Path(f) if f else None


def _env_values() -> dict[str, str]:
    p = env_file()
    if p is None or not p.is_file():
        return {}
    key = p.stat().st_mtime_ns
    if _dotenv["key"] != key:
        vals = {}
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            t = line.strip()
            if t and not t.startswith("#") and "=" in t:
                k, v = t.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
        _dotenv.update(key=key, values=vals)
    return _dotenv["values"]


def env_value(name: str) -> str:
    return os.environ.get(name) or _env_values().get(name, "")


def expand(value: str) -> str:
    """${NAME} -> the value of NAME from the environment or .env (empty if unset)."""
    return _VAR.sub(lambda m: env_value(m.group(1)), value)


def missing_secrets(c: Connector) -> list[str]:
    names = set()
    for v in [*c.env.values(), *c.headers.values(), c.url, *c.args]:
        names |= set(_VAR.findall(v))
    return sorted(n for n in names if not env_value(n))


def set_secret(name: str, value: str) -> None:
    """Write NAME=value into .env (replacing an existing NAME line). Values never go into connectors.json."""
    if not ENV_KEY.match(name):
        raise ValueError(f"'{name}' is not a valid setting name (use CAPITALS, digits and _).")
    if any(ch in value for ch in "\r\n"):
        raise ValueError("A secret cannot contain line breaks.")
    p = env_file()
    if p is None:
        os.environ[name] = value
        return
    lines = p.read_text(encoding="utf-8-sig").splitlines() if p.is_file() else []
    out, done = [], False
    for line in lines:
        if re.match(rf"^\s*{re.escape(name)}\s*=", line):
            if not done:
                out.append(f"{name}={value}")
                done = True
            continue
        out.append(line)
    if not done:
        out.append(f"{name}={value}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[name] = value


# ---------------------------------------------------------------------------- sessions (background loop)

class _Pool:
    """One open MCP session per connector, owned by a background event loop thread."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}

    def loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or not self._loop.is_running():
                ready = threading.Event()
                holder: dict[str, asyncio.AbstractEventLoop] = {}

                def run() -> None:
                    lp = asyncio.new_event_loop()
                    holder["loop"] = lp
                    asyncio.set_event_loop(lp)
                    ready.set()
                    lp.run_forever()

                threading.Thread(target=run, name="mcp-connectors", daemon=True).start()
                ready.wait(5)
                self._loop = holder["loop"]
                self._sessions.clear()
            return self._loop

    def run(self, c: Connector, op: str, *a: Any, timeout: float | None = None) -> Any:
        lp = self.loop()
        fut = asyncio.run_coroutine_threadsafe(self._do(c, op, *a), lp)
        return fut.result(timeout or c.timeout_seconds + 15)

    async def _do(self, c: Connector, op: str, *a: Any) -> Any:
        s = self._sessions.get(c.name)
        if s is None or s.dead or s.signature != _signature(c):
            if s is not None:
                await s.close()
            s = _Session(c)
            self._sessions[c.name] = s
        return await s.request(op, *a)

    def close(self, name: str) -> None:
        s = self._sessions.pop(name, None)
        if s is not None and self._loop is not None:
            asyncio.run_coroutine_threadsafe(s.close(), self._loop)


def _signature(c: Connector) -> str:
    return json.dumps([c.transport, c.command, c.args, c.env, c.url, c.headers, c.cwd,
                       [expand(v) for v in (*c.env.values(), *c.headers.values())]], sort_keys=True)


class _Session:
    def __init__(self, c: Connector):
        self.c = c
        self.signature = _signature(c)
        self.dead = False
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task = asyncio.get_running_loop().create_task(self._runner())

    def _transport(self) -> Any:
        c = self.c
        if c.transport == "stdio":
            from mcp.client.stdio import StdioServerParameters

            cmd = shutil.which(expand(c.command)) or expand(c.command)
            return StdioServerParameters(command=cmd, args=[expand(x) for x in c.args],
                                         env={k: expand(v) for k, v in c.env.items()} or None,
                                         cwd=expand(c.cwd) or None)
        import httpx2
        from mcp.client.streamable_http import streamable_http_client

        http = httpx2.AsyncClient(headers={k: expand(v) for k, v in c.headers.items()},
                                  timeout=httpx2.Timeout(c.timeout_seconds, connect=10.0))
        self._http = http
        return streamable_http_client(expand(c.url), http_client=http)

    async def _runner(self) -> None:
        from mcp import Client

        try:
            async with Client(self._transport(), read_timeout_seconds=self.c.timeout_seconds) as client:
                while True:
                    item = await self.queue.get()
                    if item is None:
                        break
                    fut, op, a = item
                    try:
                        res = await getattr(client, op)(*a)
                        if not fut.done():
                            fut.set_result(res)
                    except BaseException as exc:  # noqa: BLE001 - handed to the caller
                        if not fut.done():
                            fut.set_exception(exc)
                        if not isinstance(exc, Exception):
                            raise
        except BaseException as exc:  # noqa: BLE001 - the connection failed or the server stopped
            self.dead = True
            err = _unwrap(exc)
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item is not None and not item[0].done():
                    item[0].set_exception(ConnectorError(f"{self.c.title} could not be reached: "
                                                         f"{type(err).__name__}: {err}"))
            self._failure = err
        finally:
            self.dead = True
            http = getattr(self, "_http", None)
            if http is not None:
                await http.aclose()

    async def request(self, op: str, *a: Any) -> Any:
        if self.dead:
            raise ConnectorError(f"{self.c.title} could not be reached: {getattr(self, '_failure', 'stopped')}")
        fut = asyncio.get_running_loop().create_future()
        await self.queue.put((fut, op, a))
        done, _ = await asyncio.wait({fut, self.task}, timeout=self.c.timeout_seconds,
                                     return_when=asyncio.FIRST_COMPLETED)
        if fut in done:
            return fut.result()
        if self.task in done:
            err = getattr(self, "_failure", None)
            raise ConnectorError(f"{self.c.title} could not be reached"
                                 + (f": {type(err).__name__}: {err}" if err else "."))
        raise ConnectorError(f"{self.c.title} did not answer within {int(self.c.timeout_seconds)} seconds.")

    async def close(self) -> None:
        if not self.dead:
            await self.queue.put(None)
            try:
                await asyncio.wait_for(self.task, 10)
            except (TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                self.task.cancel()


def _unwrap(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


class ConnectorError(Exception):
    code = "connector_error"


POOL = _Pool()


# ---------------------------------------------------------------------------- discovery and registration

@dataclass
class Discovered:
    tools: list[dict[str, Any]]
    at: float
    error: str = ""
    server: str = ""


_cache: dict[str, Discovered] = {}


def _risk(c: Connector, t: dict[str, Any]) -> str:
    n = t["name"]
    if n in c.read_tools:
        return READ
    if n in c.write_tools:
        return WRITE
    if t.get("destructive"):
        return DESTRUCTIVE
    if t.get("read_only"):
        return READ
    if c.guess_read_by_name and n.lower().startswith(READ_PREFIXES):
        return READ
    return WRITE


def discover(c: Connector, *, force: bool = False) -> Discovered:
    """List the connector's tools and (re)register them in the catalog."""
    d = _cache.get(c.name)
    if d is not None and not force and not d.error and time.time() - d.at < DISCOVERY_TTL:
        return d
    if not c.enabled:
        unregister(c.name)
        d = Discovered([], time.time(), error="disabled")
        _cache[c.name] = d
        return d
    miss = missing_secrets(c)
    if miss:
        unregister(c.name)
        d = Discovered([], time.time(), error=f"Set {', '.join(miss)} in .env first.")
        _cache[c.name] = d
        return d
    try:
        res = POOL.run(c, "list_tools")
        tools = []
        for t in res.tools:
            a = t.annotations
            tools.append({"name": t.name, "description": (t.description or "").strip()[:600],
                          "read_only": bool(a and a.read_only_hint), "destructive": bool(a and a.destructive_hint),
                          "input_schema": t.input_schema or {"type": "object", "properties": {}}})
        tools = [t for t in tools if t["name"] not in c.blocked_tools]
        for t in tools:
            t["risk"] = _risk(c, t)
        d = Discovered(tools, time.time())
    except Exception as exc:  # noqa: BLE001 - shown in Settings > Connectors
        unregister(c.name)
        d = Discovered([], time.time(), error=str(_unwrap(exc))[:500] or type(exc).__name__)
        log.warning("connector discovery failed", extra={"connector": c.name, "error": d.error})
        _cache[c.name] = d
        return d
    _cache[c.name] = d
    register(c, d.tools)
    return d


def register(c: Connector, tools: list[dict[str, Any]]) -> None:
    from ..agents.gateway import register_executor

    unregister(c.name)
    roles = frozenset(r for r in c.roles if r != "admin")
    for t in tools:
        full = c.tool_name(t["name"])
        TOOLS[full] = ToolSpec(full, f"connector:{c.name}", t["risk"], roles,
                               (t["description"].splitlines() or [t["name"]])[0][:200])

        def _exec(args: dict[str, Any], key: str, _c: str = c.name, _t: str = t["name"]) -> dict[str, Any]:
            return call(_c, _t, args)

        register_executor(full, _exec)
    _refresh_allow_list()


def unregister(name: str) -> None:
    from ..agents import gateway

    for full in [k for k, v in TOOLS.items() if v.server == f"connector:{name}"]:
        TOOLS.pop(full, None)
        gateway.EXECUTORS.pop(full, None)
    _refresh_allow_list()


def _refresh_allow_list() -> None:
    AGENT_TOOLS[AGENT] = frozenset(k for k, v in TOOLS.items() if v.server.startswith("connector:"))


def discover_all(force: bool = False) -> dict[str, Discovered]:
    return {c.name: discover(c, force=force) for c in load()}


def start_background_discovery() -> None:
    """Connect to every enabled connector shortly after start-up (without delaying the API)."""
    def work() -> None:
        try:
            for name, d in discover_all(force=True).items():
                log.info("connector ready" if not d.error else "connector not ready",
                         extra={"connector": name, "tools": len(d.tools), "error": d.error})
        except Exception:  # noqa: BLE001 - logged
            log.exception("connector discovery failed")

    threading.Thread(target=work, name="connector-discovery", daemon=True).start()


# ---------------------------------------------------------------------------- calling a tool

def call(connector: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    c = get(connector)
    if c is None or not c.enabled:
        raise ConnectorError(f"The connector '{connector}' is not enabled.")
    r = POOL.run(c, "call_tool", tool, args)
    text = "\n".join(getattr(b, "text", "") for b in (r.content or []) if getattr(b, "text", "")).strip()
    if r.is_error:
        raise ConnectorError(text or f"{c.title}: {tool} failed.")
    out: dict[str, Any] = {"connector": c.name, "tool": tool, "text": text[:20000], "untrusted": True}
    if r.structured_content is not None:
        out["structured"] = r.structured_content
    return out


HIDDEN = "(hidden)"


def _redact(v: str) -> str:
    """Show a value only when it is a ${NAME} reference (plus fixed text like 'Bearer '), never a literal secret."""
    rest = _VAR.sub("", v).strip()
    return v if rest in ("", "Bearer", "Token", "Basic") else HIDDEN


def status() -> list[dict[str, Any]]:
    out = []
    for c in load():
        d = _cache.get(c.name)
        out.append({**{k: v for k, v in c.to_dict().items() if k not in ("env", "headers")},
                    "env": {k: _redact(v) for k, v in c.env.items()},
                    "headers": {k: _redact(v) for k, v in c.headers.items()},
                    "env_keys": sorted(c.env), "header_keys": sorted(c.headers),
                    "missing_secrets": missing_secrets(c),
                    "state": "disabled" if not c.enabled else ("error" if d and d.error else
                                                              "connected" if d else "not checked"),
                    "error": d.error if d else "", "checked_at": d.at if d else None,
                    "tools": [{"name": t["name"], "risk": t["risk"], "description": t["description"][:200]}
                              for t in (d.tools if d else [])]})
    return out


def ensure_tool(full: str) -> None:
    name = full.split(".", 1)[0]
    c = get(name)
    if c is not None:
        try:
            discover(c)
        except Exception:  # noqa: BLE001 - the gateway reports the unknown tool
            log.warning("connector discovery failed", extra={"connector": name})


def tools_of(c: Connector) -> list[dict[str, Any]]:
    return discover(c).tools
