"""Shared plumbing for the AgentsMind MCP servers (MCP Python SDK 2.3.0, MCPServer).

Security defaults:
  - bound to 127.0.0.1 unless <PREFIX>_MCP_HOST says otherwise
  - every request needs `Authorization: Bearer <PREFIX>_MCP_TOKEN` (24+ chars); the
    server refuses to start without a token
  - DNS-rebinding protection: only the configured host:port is accepted as Host
Reliability:
  - calls to the backing portal have connect/read timeouts
  - reads are retried with backoff; writes are never retried here (callers pass an
    idempotency key, so the core can retry safely)
"""
from __future__ import annotations

import hmac
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx2
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

REPO_ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("mcp_servers")

READ_RETRIES = 2
READ_BACKOFF = 0.3


def load_env() -> None:
    p = REPO_ROOT / ".env"
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def setting(name: str, default: str | None = None, *, required: bool = False, min_len: int = 0) -> str:
    v = (os.environ.get(name) or "").strip()
    if not v:
        if required:
            raise SystemExit(f"Refusing to start: set {name} (see .env.example).")
        return default or ""
    if min_len and len(v) < min_len:
        raise SystemExit(f"Refusing to start: {name} must be at least {min_len} characters.")
    return v


class StaticTokenVerifier:
    """Accepts exactly one shared bearer token (constant-time compare)."""

    def __init__(self, token: str, client_id: str = "agentsmind-core"):
        self._token = token.encode()
        self._client_id = client_id

    async def verify_token(self, token: str) -> AccessToken | None:
        if token and hmac.compare_digest(token.encode(), self._token):
            return AccessToken(token=token, client_id=self._client_id, scopes=["tools"])
        return None


def make_server(*, name: str, title: str, instructions: str, prefix: str, default_port: int) -> tuple[MCPServer, dict]:
    load_env()
    host = setting(f"{prefix}_MCP_HOST", "127.0.0.1")
    port = int(setting(f"{prefix}_MCP_PORT", str(default_port)))
    token = setting(f"{prefix}_MCP_TOKEN", required=True, min_len=24)
    base = f"http://{host}:{port}"
    server = MCPServer(
        name=name, title=title, instructions=instructions, version="1.0.0",
        token_verifier=StaticTokenVerifier(token),
        auth=AuthSettings(issuer_url=base, resource_server_url=f"{base}/mcp"),
    )
    cfg = {"host": host, "port": port, "base": base}
    return server, cfg


def run(server: MCPServer, cfg: dict) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", stream=sys.stdout)
    hostport = f"{cfg['host']}:{cfg['port']}"
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[hostport, f"localhost:{cfg['port']}", f"127.0.0.1:{cfg['port']}"],
        allowed_origins=[cfg["base"], f"http://localhost:{cfg['port']}"],
    )
    log.info("starting %s on %s/mcp (bearer token required)", server.name, cfg["base"])
    server.run("streamable-http", host=cfg["host"], port=cfg["port"], transport_security=security)


class PortalClient:
    """HTTP client for a portal REST API, with timeouts and read retries."""

    def __init__(self, *, name: str, base_url: str, api_key: str, start_hint: str):
        self.name, self.base_url, self.start_hint = name, base_url.rstrip("/"), start_hint
        self._client = httpx2.Client(base_url=self.base_url, headers={"X-API-Key": api_key},
                                     timeout=httpx2.Timeout(10.0, connect=3.0))

    def _raise_for(self, r: httpx2.Response) -> None:
        if r.status_code < 400:
            return
        try:
            d = r.json().get("detail", {})
        except Exception:  # noqa: BLE001 - non-JSON error page
            d = {}
        if isinstance(d, dict) and d.get("code") == "validation_error":
            fields = "; ".join(f"{f['field']}: {f['message']}" for f in d.get("fields", []))
            raise ToolError(f"Invalid input. {fields}")
        msg = d.get("message") if isinstance(d, dict) else str(d)
        if r.status_code == 401:
            raise ToolError(f"{self.name} rejected this server's API key. Check the *_PORTAL_API_KEY setting.")
        raise ToolError(msg or f"{self.name} returned HTTP {r.status_code}.")

    def _send(self, method: str, path: str, *, retry: bool, **kw: Any) -> Any:
        attempts = 1 + (READ_RETRIES if retry else 0)
        last: Exception | None = None
        for i in range(attempts):
            start = time.perf_counter()
            try:
                r = self._client.request(method, path, **kw)
            except (httpx2.ConnectError, httpx2.TimeoutException, httpx2.NetworkError) as exc:
                last = exc
                log.warning("%s %s failed (%s), attempt %d/%d", method, path, type(exc).__name__, i + 1, attempts)
                if i + 1 < attempts:
                    time.sleep(READ_BACKOFF * (2 ** i))
                continue
            log.info("%s %s -> %s in %d ms", method, path, r.status_code, int((time.perf_counter() - start) * 1000))
            if retry and r.status_code >= 500 and i + 1 < attempts:
                time.sleep(READ_BACKOFF * (2 ** i))
                continue
            self._raise_for(r)
            return r.json()
        raise ToolError(f"{self.name} is not reachable at {self.base_url} ({type(last).__name__}). {self.start_hint}")

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        return self._send("GET", path, retry=True, params=clean)

    def write(self, method: str, path: str, body: dict[str, Any] | None = None, *, idempotency_key: str | None = None,
              actor: str | None = None) -> Any:
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if actor:
            headers["X-Actor"] = actor
        return self._send(method, path, retry=False, json=body, headers=headers)
