# API and library verification log

Rule: before code depends on an external API or library, record where its behaviour was
verified, which version, and when. "Installed" means checked against the installed
package, not a tutorial.

| Dependency | Pinned version | Verified against | Date | Notes |
|---|---|---|---|---|
| MCP Python SDK (`mcp`) | 2.3.0 (to be pinned in Phase 2) | PyPI release history (https://pypi.org/project/mcp/1.30.0/ lists 2.3.0 as latest, 2026-10-02), plus the installed 2.3.0 package | 2026-10-28 | In 2.x `mcp.server.fastmcp` no longer exists: importing it raises "FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer)". Phase 2 uses `MCPServer`. Migration guide: https://py.sdk.modelcontextprotocol.io/v2/migration/ |
| FastAPI / Starlette / Uvicorn | 0.115.6 / 0.41.3 / 0.34.0 | installed in a clean Windows venv, Python 3.11.9 (`pip freeze` in gate log 2026-10-28 22:41) | 2026-10-28 | Only core features used: routers, dependencies, lifespan, exception handlers, TestClient. |
| Pydantic / pydantic-settings / email-validator | 2.10.4 / 2.7.1 / 2.2.0 | installed, same gate log (pydantic_core 2.27.2) | 2026-10-28 | `Settings(_env_file=...)` override used for tests. |
| SQLAlchemy / Alembic | 2.0.36 / 1.14.0 | installed, same gate log | 2026-10-28 | 2.0-style `Mapped` models; `compare_metadata` drift test. |
| argon2-cffi | 23.1.0 (bindings 26.1.0) | installed, same gate log | 2026-10-28 | `PasswordHasher()` defaults (argon2id). |
| PyJWT | 2.10.1 | installed, same gate log | 2026-10-28 | HS256 with required claims exp, iat, sub, iss, jti; `alg=none` rejected (test). |
| tzdata | 2024.2 | added after the first gate run: Windows has no IANA database, so `zoneinfo` could not resolve Asia/Karachi | 2026-10-28 | |
| Google Calendar / Gmail / Drive APIs | Phase 3 | n/a | n/a | Scopes to be chosen from official docs (narrowest that works), shared OAuth client. |
| OpenAI API | Phase 3 | n/a | n/a | |

Installation verified means pip resolved and installed the exact pins on Windows. Behaviour
is verified by the backend test suite in the same gate run.
