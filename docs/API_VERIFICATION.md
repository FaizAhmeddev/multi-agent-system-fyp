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
| Google Calendar API v3 | google-api-python-client 2.196.0, google-auth 2.53.0, google-auth-oauthlib 1.3.1 (pinned in requirements/servers.txt) | Official docs: scopes https://developers.google.com/calendar/api/auth ; events.insert https://developers.google.com/calendar/v3/reference/events/insert | 2026-10-29 | Scopes used: `calendar.events.owned` ("View, create, change, and delete events on calendars you own"; listed as sufficient for events.insert) and `calendar.freebusy` ("View your availability in your calendars") for freebusy.query. Client-supplied event id: base32hex characters (a-v, 0-9), 5 to 1024 long, unique per calendar; we use 40 lowercase hex characters derived from the approval's idempotency key, and treat HTTP 409 as a replay. Meet links need `conferenceDataVersion=1` plus `conferenceData.createRequest` (`conferenceSolutionKey.type = hangoutsMeet`). `sendUpdates` is `none` unless the user asked to notify attendees. The Google backend has not run against a live account yet: it is unit tested with a fake client (`tests/mcp_servers_tests/test_google_backends.py`, runs on the laptop gate) and needs the user's OAuth client. |
| Gmail API v1 | same libraries | Scopes `gmail.readonly` (messages.list / messages.get) and `gmail.send` (messages.send with a base64url `raw` MIME message, optional `threadId`) | 2026-10-29 | Gmail has no idempotency key, so workspace-mcp keeps a local ledger (data/workspace_gmail_sent.db) keyed by the approval's key: a replay never sends twice. Not yet run against a live mailbox. |
| Google Drive API v3 | same libraries | Scope `drive.readonly`. Query syntax: https://developers.google.com/drive/api/v2/ref-search-terms (the v3 page refused automated fetches; same grammar): values in single quotes, escape `'` as `\'`; `fullText contains`, `name contains` (prefix match), `trashed = false`, `'<id>' in parents` | 2026-10-29 | Google Docs/Sheets/Slides are read with files.export (text/plain or text/csv); PDF and text with files.get_media (20 MB cap); PDF text via pypdf. Not yet run against a live Drive. |
| OpenAI Python SDK (`openai`) | 2.35.1 (pinned) | piwheels release index lists 2.35.1, released 2026-05-06 (https://www.piwheels.org/project/openai/); the PyPI feed shows 3.x is current (https://pypi.org/rss/project/openai/releases.xml) | 2026-10-29 | Pinned to the 2.x line on purpose (the 3.x line is weeks old). Used surface: `OpenAI(api_key, timeout, max_retries)`, `client.chat.completions.create(model, messages, temperature, response_format={"type": "json_object"})`, exceptions `AuthenticationError`, `RateLimitError`, `APITimeoutError`, `APIConnectionError`, `APIError`. Structured answers are validated with Pydantic and retried once; invalid twice means the answer is refused. Re-verified by the next gate run (import + install). No live call has been made: no key is configured yet. |
| LangGraph | 1.1.0 (pinned) | PyPI https://pypi.org/project/langgraph/1.1.0/ (released 2026-03-10, requires Python >= 3.10; example uses `from langgraph.graph import START, StateGraph` and `graph.compile().invoke(...)`); API reference https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges (`add_conditional_edges(source, path, path_map)`) | 2026-10-29 | Each agent is a `StateGraph` with nodes understand, gather, propose (approval node), respond, clarify and fail, joined by conditional edges. Node names never equal state keys (LangGraph rejects that), so the error node is called `fail`. The cloud workspace cannot install langgraph, so `tests/assistant/conftest.py` provides a minimal stand-in there; the laptop gate runs the same tests against the real 1.1.0. |
| cryptography | 50.0.1 | installed package in the cloud workspace | 2026-10-29 | Fernet (AES-128-CBC + HMAC-SHA256) encrypts the Google token at rest (data/google_token.enc). |
| Frontend packages (npm) | react 19.2.8, react-dom 19.2.8, @types/react 19.2.7, @types/react-dom 19.2.3, typescript 6.0.3, vite 8.2.0, @vitejs/plugin-react 6.1.2, tailwindcss 4.3.3, @tailwindcss/vite 4.3.3, @tanstack/react-query 5.100.0, @radix-ui/react-dialog 1.3.1, @radix-ui/react-dropdown-menu 2.2.1, @radix-ui/react-tabs 1.2.1, lucide-react 1.50.0, @fontsource/ibm-plex-sans 5.3.0, @fontsource/ibm-plex-mono 5.3.0, @playwright/test 1.63.0 | npm registry metadata for each exact version (https://registry.npmjs.org/<name>/<version>); every pin is at least two weeks old on 2026-10-29. Peer ranges checked: plugin-react 6 needs vite ^8; @tailwindcss/vite 4.3.3 accepts vite ^8; react-query 5 and the Radix packages accept React 19; vite 8 needs Node ^20.19 or >=22.12 | 2026-10-29 | The cloud workspace has no npm registry access. There the app was bundled with esbuild using local stand-ins for Radix, TanStack Query and Lucide, styled by the real Tailwind 4.3.3 compiler, and exercised with Playwright 1.63 against a mock API. `npm install`, `tsc` and `vite build` with the real packages run in the phase gate. lucide-react 1.x renamed icons (house, triangle-alert, circle-check, loader-circle); all icon imports are in `src/components/icons.ts`, so a wrong name fails the build in one place. |
| pypdf | 6.17.0 | installed package in the cloud workspace | 2026-10-29 | `PdfReader(...).pages[i].extract_text()` for Drive PDFs (first 50 pages). |

Installation verified means pip resolved and installed the exact pins on Windows. Behaviour
is verified by the backend test suite in the same gate run.

## Security updates, 2026-10-29

pip-audit on the Windows gate (74 findings in 6 packages) led to these pins:

| Package | Pin |
|---|---|
| fastapi | 0.143.1 (released 2026-10-14; `starlette>=0.46.0`, `pydantic>=2.9.0`, per its pyproject at the tag) |
| starlette | 1.7.0 (2026-09-23) |
| PyJWT | 2.15.0 (2026-09-23) |
| python-multipart | 0.0.32 (2026-06-04) |
| langgraph | 1.2.12 (2026-09-21; needs `langgraph-sdk>=0.4.2,<0.5`) |
| langgraph-sdk | 0.4.6 (2026-10-06; fixes CVE-2026-118667, reported by pip-audit on the laptop) |
| pypdf | 6.21.2 (2026-10-21, the release that fixes the reported CVEs; accepted under two weeks old because it is a security fix) |
| setuptools | 84.1.0 (in the venv) |

mcp 2.3.0 declares `starlette>=0.27`, `pyjwt[crypto]>=2.10.1` and `python-multipart>=0.0.9`. The cloud workspace already runs mcp 2.3.0 with starlette 1.7.0, PyJWT 2.15.0 and python-multipart 0.0.32, and the MCP server tests pass there.

Release dates come from the PyPI release feeds and project pages. The next gate run re-checks the full set with pip-audit.


## Added in 0.6.0 (2026-10-30), not re-read this session

The documentation pages below could not be opened from the build workspace (fetch permission timed out), so
these calls follow the long-stable published APIs and are checked by live use on the laptop:

| API | Call used |
|---|---|
| Twilio Messages | `POST https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Messages.json`, basic auth (SID, token), form fields `From`, `To` (`whatsapp:+...`), `Body` or `ContentSid` + `ContentVariables` (JSON) |
| Google Sheets v4 | `spreadsheets.get` (tabs), `spreadsheets.values.get`, `values.append` (`valueInputOption=USER_ENTERED`, `insertDataOption=INSERT_ROWS`), `values.update`; scope `spreadsheets` |
| Google Drive v3 | `files.create` multipart upload; scope `drive.file` |
| Gmail IMAP/SMTP | `imap.gmail.com:993` SSL (read-only mailbox, `BODY.PEEK[]`, `X-GM-RAW`, `X-GM-MSGID`), `smtp.gmail.com:465` SSL, app password |
