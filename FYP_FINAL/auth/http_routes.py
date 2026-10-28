"""Same-origin HTTP endpoints mounted through Streamlit's supported st.App API."""
from datetime import datetime, timezone
import hmac
import os
import secrets

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from auth.persistent_sessions import COOKIE_NAME, get_session_store

CSRF_COOKIE = "office_auth_csrf"


def secure_cookie(request: Request) -> bool:
    # Insecure cookies are permitted only for loopback development.
    return (request.url.scheme == "https"
            or os.getenv("FYP_PUBLIC_ORIGIN", "").lower().startswith("https://")
            or os.getenv("FYP_AUTH_COOKIE_SECURE", "").lower() in ("true", "1")
            or request.url.hostname not in ("localhost", "127.0.0.1", "::1"))


def _response(payload, status=200):
    return JSONResponse(payload, status_code=status, headers={
        "Cache-Control": "no-store", "Pragma": "no-cache", "Vary": "Origin",
        "X-Content-Type-Options": "nosniff",
    })


def _same_origin(request: Request, *, require_origin: bool) -> bool:
    origin = request.headers.get("origin")
    expected = os.getenv("FYP_PUBLIC_ORIGIN", "").rstrip("/") or f"{request.url.scheme}://{request.url.netloc}"
    if origin and origin.rstrip("/") != expected:
        return False
    if require_origin and not origin:
        return False
    return request.headers.get("sec-fetch-site", "same-origin") != "cross-site"


def _csrf_valid(request: Request) -> bool:
    cookie, header = request.cookies.get(CSRF_COOKIE, ""), request.headers.get("x-office-csrf", "")
    return (bool(cookie) and len(cookie) <= 128 and len(header) <= 128
            and hmac.compare_digest(cookie.encode(), header.encode())
            and _same_origin(request, require_origin=True)
            and request.headers.get("content-type", "").split(";")[0].strip() == "application/json")


async def csrf_nonce(request: Request):
    if not _same_origin(request, require_origin=False):
        return _response({"error": "Request rejected."}, 403)
    token = request.cookies.get(CSRF_COOKIE)
    if not token or len(token) != 43 or not all(c.isalnum() or c in "_-" for c in token):
        token = secrets.token_urlsafe(32)
    response = _response({"csrf": token})
    response.set_cookie(CSRF_COOKIE, token, max_age=600, httponly=True,
                        secure=secure_cookie(request), samesite="strict", path="/")
    return response


def _record_login(verified):
    from database.sqlite_db import touch_user_session, log_login_event
    account = verified.account
    touch_user_session(verified.id, account.username, account.name, account.role)
    log_login_event(username=account.username, display_name=account.name,
                    role=account.role, event="login", session_id=verified.id)


def _record_logout(verified):
    from database.sqlite_db import deactivate_user_session, log_login_event
    deactivate_user_session(verified.id)
    log_login_event(username=verified.account.username, display_name=verified.account.name,
                    role=verified.account.role, event="logout", session_id=verified.id)


def revoke_browser_session(token):
    store = get_session_store()
    verified = store.validate(token)
    changed = store.revoke(token)
    if verified and changed:
        _record_logout(verified)
    return changed


async def handshake(request: Request):
    if not _csrf_valid(request):
        return _response({"error": "Request rejected."}, 403)
    if len(await request.body()) > 2048:
        return _response({"error": "Request rejected."}, 400)
    try:
        body = await request.json()
        grant = body.get("grant") if isinstance(body, dict) else None
        if not isinstance(grant, str):
            return _response({"error": "Sign-in expired. Please sign in again."}, 401)
        result = await run_in_threadpool(get_session_store().exchange, grant, request.cookies.get(COOKIE_NAME))
        if not result:
            return _response({"error": "Sign-in expired. Please sign in again."}, 401)
        token, verified = result
        await run_in_threadpool(_record_login, verified)
        response = _response({"ok": True})
        response.set_cookie(COOKIE_NAME, token,
            max_age=max(1, verified.expires_at - int(datetime.now(timezone.utc).timestamp())),
            expires=datetime.fromtimestamp(verified.expires_at, timezone.utc),
            httponly=True, secure=secure_cookie(request), samesite="lax", path="/")
        return response
    except (ValueError, TypeError):
        return _response({"error": "Request rejected."}, 400)
    except Exception:
        return _response({"error": "Secure sign-in is temporarily unavailable."}, 503)


async def logout(request: Request):
    if not _csrf_valid(request):
        return _response({"error": "Request rejected."}, 403)
    try:
        await run_in_threadpool(revoke_browser_session, request.cookies.get(COOKIE_NAME))
        response = _response({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True,
                               secure=secure_cookie(request), samesite="lax")
        response.delete_cookie(CSRF_COOKIE, path="/", httponly=True,
                               secure=secure_cookie(request), samesite="strict")
        return response
    except Exception:
        return _response({"error": "Sign-out could not be completed. Please retry."}, 503)


def auth_routes(base_path=""):
    prefix = "/" + base_path.strip("/") if base_path else ""
    return [Route(prefix + "/_office/auth/nonce", csrf_nonce, methods=["GET"]),
            Route(prefix + "/_office/auth/handshake", handshake, methods=["POST"]),
            Route(prefix + "/_office/auth/logout", logout, methods=["POST"])]
