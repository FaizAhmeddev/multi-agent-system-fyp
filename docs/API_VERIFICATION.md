# API and library verification log

Rule: before code depends on an external API or library, record where its behaviour was
verified, which version, and when. "Installed" means checked against the installed
package, not a tutorial.

| Dependency | Pinned version | Verified against | Date | Notes |
|---|---|---|---|---|
| MCP Python SDK (`mcp`) | 2.3.0 (pinned) | PyPI release history (https://pypi.org/project/mcp/1.30.0/ lists 2.3.0 as latest, 2026-10-02), plus the installed 2.3.0 package | 2026-10-28 | In 2.x `mcp.server.fastmcp` no longer exists: importing it raises "FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer)". Phase 2 uses `MCPServer`. Verified against the installed package on 2026-10-28: `MCPServer(token_verifier=, auth=AuthSettings(issuer_url, resource_server_url))`, `@server.tool(annotations=ToolAnnotations(...))`, Pydantic return types give `structured_content` plus `output_schema`, `ToolError` messages reach the client, `run('streamable-http', transport_security=TransportSecuritySettings(...))`, `mcp.Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers=...)))`. No token gives 401 with RFC 9728 `WWW-Authenticate`; a foreign Host gives 421. Requires pydantic>=2.12. Migration guide: https://py.sdk.modelcontextprotocol.io/v2/migration/ |
| FastAPI / Starlette / Uvicorn | 0.118.2 / 0.48.0 / 0.34.0 (Phase 2; 1a ran on 0.115.6 / 0.41.3) | installed in a clean Windows venv, Python 3.11.9 (`pip freeze` in gate log 2026-10-28 22:41) | 2026-10-28 | Only core features used: routers, dependencies, lifespan, exception handlers, TestClient. |
| Pydantic / pydantic-settings / email-validator | 2.12.0 / 2.7.1 / 2.2.0 (Phase 2; 1a ran on 2.10.4) | 1a: installed (pydantic_core 2.27.2). 2.12.0 is required by mcp 2.3.0; FastAPI release notes: 0.118.1 'Ensure compatibility with Pydantic 2.12.0' (https://unh-pfem-gitlab.ara.inrae.fr/nguilhot/goslin-api/-/merge_requests/41, which quotes the FastAPI notes). Re-verified by the next gate run | 2026-10-28 | `Settings(_env_file=...)` override used for tests. |
| SQLAlchemy / Alembic | 2.0.36 / 1.14.0 | installed, same gate log | 2026-10-28 | 2.0-style `Mapped` models; `compare_metadata` drift test. |
| argon2-cffi | 23.1.0 (bindings 26.1.0) | installed, same gate log | 2026-10-28 | `PasswordHasher()` defaults (argon2id). |
| PyJWT | 2.10.1 | installed, same gate log | 2026-10-28 | HS256 with required claims exp, iat, sub, iss, jti; `alg=none` rejected (test). |
| Jinja2 / itsdangerous | 3.1.6 / 2.2.0 | portal templates and signed session cookies; templates compiled with Jinja2 3.1.6 in the cloud workspace | 2026-10-28 | |
| httpx2 | 2.13.1 | dependency of mcp 2.3.0; used by the MCP servers to call the portals | 2026-10-28 | |
| tzdata | 2024.2 | added after the first gate run: Windows has no IANA database, so `zoneinfo` could not resolve Asia/Karachi | 2026-10-28 | |
| Google Calendar / Gmail / Drive APIs | Phase 3 | n/a | n/a | Scopes to be chosen from official docs (narrowest that works), shared OAuth client. |
| OpenAI API | Phase 3 | n/a | n/a | |

Installation verified means pip resolved and installed the exact pins on Windows. Behaviour
is verified by the backend test suite in the same gate run.
