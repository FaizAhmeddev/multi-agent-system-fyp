# Browser authentication

Run `python main.py` from `FYP_FINAL`, or `python -m ui.server --port 8501`.
The launcher uses Streamlit 1.66.1's public `st.App` ASGI API to mount same-origin
HTTP cookie endpoints alongside the existing UI. Bare `streamlit run ui/app.py`
does not mount these endpoints and cannot complete secure sign-in. For a reverse
proxy, use `uvicorn ui.server:app` or the module launcher with the desired host.
Serve public deployments over HTTPS.

## Root causes and fixes

- Theme SVGs lacked intrinsic dimensions and their CSS was outside the component
  boundary. The switcher now owns isolated styles and explicit 16px icons; login
  icons also have explicit dimensions and scoped rules.
- A readiness selector hid the whole page until JavaScript finished. That gate
  was removed. Theme initialization never hides the authentication form or workspace.
- Authentication previously depended on connection-local Streamlit state, which
  is recreated on refresh or a new tab. State is now restored only after validating
  an opaque browser session against the database.
- A separate hosted-configuration warning added height outside the login card.
  Its guidance is now an expandable notice inside the form footer.

## Session lifecycle

The existing credential verifier still handles username/password login. After it
accepts credentials, `persistent_sessions.py` issues a one-use, 45-second grant.
`auth_cookie_bridge.js` exchanges that grant through `http_routes.py`; the server
sets `office_session` as a host-only HttpOnly, SameSite=Lax cookie with an explicit
expiry. HTTPS and public hosts require Secure; loopback HTTP is allowed for local
development. Only SHA-256 hashes of random 256-bit tokens are stored in the new
`auth_browser_sessions` and `auth_login_grants` tables in the configured database.
No existing tables are reset or replaced.

Every full UI run validates expiration, revocation, account existence and the
credential fingerprint before restoring identity. Role and display name come from
the current server-side account, never browser claims. Password changes invalidate
sessions. A successful exchange rotates an existing browser token. Logout revokes
the record, clears Streamlit state and deletes the cookie. A single reload after
cookie exchange establishes the new authenticated WebSocket, without rendering
login and dashboard together. Failed requests show retry controls and time out.

HTTP mutations require exact same-origin requests, JSON and a double-submit CSRF
nonce. Responses are not cached. Authentication tokens, passwords and authorization
flags are never written to localStorage/sessionStorage or URLs. Theme preference
uses independent non-sensitive browser storage and survives logout.

## Deployment options

- `FYP_AUTH_SESSION_SECONDS`: absolute lifetime, default 28800 (8 hours), bounded
  between 60 seconds and 30 days; validation cannot be disabled.
- `FYP_PUBLIC_ORIGIN`: exact public origin, such as `https://office.example.com`,
  when running behind a TLS reverse proxy. Also ensures Secure cookies.
- `FYP_AUTH_COOKIE_SECURE=true`: explicitly require Secure cookies locally too.
- `FYP_TRUSTED_PROXIES`: Uvicorn trusted proxy addresses; module launcher default
  is `127.0.0.1`. Restrict this to actual proxies. External Uvicorn commands must
  configure their own forwarded-header trust.

Do not expose the private HTTP upstream publicly when terminating TLS at a proxy.
Idle pages are checked again on their next full UI run, navigation or reload.

## Verification

From the repository root:

```powershell
python FYP_FINAL/scripts/test_persistent_auth.py
python FYP_FINAL/scripts/test_auth_session.py
python FYP_FINAL/scripts/test_auth_pages.py
python FYP_FINAL/scripts/test_workspace_theme.py
```

The persistent-auth suite covers opaque hashes, replay/expiry/revocation, current
roles, credential changes, token rotation, concurrent grant exchange, cookie flags,
CSRF/origin rejection, TLS proxy settings, base paths and logout. The UI-boundary
suite checks forged/stale state, fail-closed validation, fresh server identity,
session changes and login/logout transitions. Browser verification used an isolated SQLite
fixture with the real credential verifier: five reloads, second tab, all eight
modules, four roles, logout and both tabs reloading, expired/revoked records,
dark/light login at 1920x1080, 1440x900, 1366x768, 390x844 and 320x568, bounded
icons, desktop overflow checks and WCAG A/AA axe checks. These checks do not claim
production HTTPS deployment or acceptance of external AI/MCP integrations.

## Main changed files

- `auth/persistent_sessions.py`, `auth/http_routes.py`: server-side sessions and HTTP boundary.
- `ui/auth_session.py`, `ui/auth_cookie_bridge.js`, `ui/server.py`, `main.py`: restoration and launch lifecycle.
- `ui/auth_pages.py`, `ui/auth.css`: scoped login layout, bounded icons and compact notice.
- `ui/appearance.py`, `ui/theme_switcher.js`, `ui/theme_switcher.css`, `ui/monochrome.css`: isolated theme control and safe visibility.
- `ui/app.py`: authentication gate and logout integration; existing business handlers retained.
- `scripts/test_persistent_auth.py`, `scripts/test_auth_pages.py`: session and login regressions.
