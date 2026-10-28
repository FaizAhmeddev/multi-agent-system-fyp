"""Persistent authentication boundary for the Streamlit UI.

Never authorizes from a browser flag or from Streamlit session_state alone.
"""
from pathlib import Path
import streamlit as st
import streamlit.components.v2 as components

from auth.persistent_sessions import COOKIE_NAME, get_session_store

_bridge = components.component(
    "office_secure_cookie_exchange",
    js=Path(__file__).with_name("auth_cookie_bridge.js").read_text(encoding="utf-8"),
)


def _cookie_bridge(action: str, grant: str = "") -> None:
    st.markdown('<div class="auth-transition" role="status">'
                + ("Signing in securely…" if action == "handshake" else "Signing out…")
                + '</div>', unsafe_allow_html=True)
    attempt = st.session_state.get("_auth_bridge_attempt", 0)
    result = _bridge(key=f"office_secure_cookie_exchange_{attempt}", height=0,
        data={"action": action, "grant": grant, "base": "/" + st.get_option("server.baseUrlPath").strip("/") if st.get_option("server.baseUrlPath") else ""},
        on_error_change=lambda: None)
    if result.get("error"):
        st.error(result["error"])
        if action == "logout":
            if st.button("Retry sign out", key="auth_cookie_retry"):
                st.session_state["_auth_bridge_attempt"] = attempt + 1
                st.rerun()
        elif st.button("Return to sign in", key="auth_cookie_retry"):
            st.session_state.clear()
            st.rerun()
    st.stop()


def restore_authentication() -> None:
    if st.session_state.get("_auth_logout_pending"):
        _cookie_bridge("logout")
    if st.session_state.get("_auth_login_grant"):
        _cookie_bridge("handshake", st.session_state["_auth_login_grant"])
    token = st.context.cookies.get(COOKIE_NAME)
    try:
        verified = get_session_store().validate(token) if token else None
    except Exception:
        # Fail closed. Never fall back to a previous session_state authorization.
        verified = None
    if verified is None:
        if st.session_state.get("logged_in"):
            st.session_state.clear()
        st.session_state.logged_in = False
        return
    if st.session_state.get("auth_session_id") not in (None, "", verified.id):
        st.session_state.clear()
    account = verified.account
    st.session_state.logged_in = True
    st.session_state.username = account.username
    st.session_state.user_role = account.role
    st.session_state.user_name = account.name
    st.session_state.auth_session_id = verified.id


def begin_login(username: str, verified_password: str) -> None:
    try:
        grant = get_session_store().issue_grant(username, verified_password)
    except Exception:
        st.error("Secure sign-in is temporarily unavailable. Please try again.")
        return
    if not grant:
        st.error("Your credentials changed. Please sign in again.")
        return
    st.session_state["_auth_login_grant"] = grant
    st.rerun()


def begin_logout() -> None:
    # Revoke immediately, even if the browser closes before clearing its cookie.
    from auth.http_routes import revoke_browser_session
    try:
        revoke_browser_session(st.context.cookies.get(COOKIE_NAME))
    except Exception:
        # The HTTP boundary retries revocation before it will delete the cookie.
        pass
    st.session_state.clear()
    st.session_state["_auth_logout_pending"] = True
    st.rerun()
