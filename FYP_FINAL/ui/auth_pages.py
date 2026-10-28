"""
Login, sign-up, and forgot-password screens with email OTP verification.
"""

from __future__ import annotations

import re
from pathlib import Path
import streamlit as st

from config import OPENAI_API_KEY, admin_contact_message, is_hosted_deploy
from ui.branding import logo_html


_AUTH_DEFAULTS = {
    "auth_screen": "login",
    "signup_step": 1,
    "signup_draft": {},
    "forgot_step": 1,
    "forgot_username": "",
    "auth_email_verified": False,
    "auth_dev_otp_email": "",
}

_AUTH_HEADINGS = {
    "login": ("Welcome back", "Sign in to your intelligent workspace."),
    "signup": ("Create account", "Register with email verification to get started."),
    "forgot": ("Reset password", "Verify your identity, then choose a new password."),
}

def _init_auth_session() -> None:
    for k, v in _AUTH_DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v if not isinstance(v, dict) else {}


def _inject_auth_styles() -> None:
    css = Path(__file__).with_name("auth.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _icon(name: str) -> str:
    """Small decorative icons share one accessible, dependency-free SVG system."""
    paths = {
        "route": '<rect x="3" y="3" width="6" height="6" rx="1.5"/><rect x="15" y="15" width="6" height="6" rx="1.5"/><path d="M6 9v9h9M9 6h9v9"/>',
        "shield": '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
        "chart": '<path d="M4 3v17h17M9 15v-4m5 4V7m5 8v-6"/>',
        "spark": '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
        "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
        "lock": '<rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 4v3"/>',
        "mail": '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m3 7 9 6 9-6"/>',
    }
    return f'<svg width="18" height="18" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{paths[name]}</svg>'


def _auth_hero_panel() -> None:
    st.markdown(
        f"""
<div class="auth-hero-panel">
<div class="auth-orb"></div><div class="auth-orb teal"></div>
<div class="auth-brand">{logo_html()}</div>
<div class="auth-eyebrow"><span class="auth-status-dot"></span> Your workspace, reimagined</div>
<h1>Work Smarter.<br> <span class="auth-gradient">Automate Everything.</span></h1>
<p class="auth-description">Less busywork. More possibility. Bring HR, Finance, IT, and Email together with intelligent AI-powered automation.</p>
<ul class="auth-feature-list">
<li>{_icon("route")} Intelligent AI Agent Routing</li>
<li>{_icon("shield")} Enterprise-Grade Security</li>
<li>{_icon("chart")} Real-Time Analytics &amp; Automation</li>
</ul>
<div class="auth-workflow" role="img" aria-label="Illustrative workflow: incoming request is routed by an AI agent to a completed task. This is a product preview, not live data.">
<div class="auth-workflow-head"><span>Intelligence in motion</span><span><span class="auth-status-dot"></span> Workflow preview</span></div>
<div class="auth-flow"><div class="auth-flow-node">{_icon("mail")} Request</div><div class="auth-connector"></div><div class="auth-flow-node core">{_icon("spark")} AI orchestrator</div><div class="auth-connector"></div><div class="auth-flow-node">{_icon("check")} Complete</div></div>
<div class="auth-flow-foot">{_icon("check")} The right agent. The right action.<span>HR · Finance · IT · Email</span></div>
</div>
<div class="auth-hero-footer">{_icon("shield")} Purpose-built for a more productive workday.</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def _auth_card_header() -> None:
    screen = st.session_state.auth_screen
    title, subtitle = _AUTH_HEADINGS.get(
        screen, ("Sign in", "Access your workspace.")
    )
    st.markdown(
        f"""
        <div class="auth-card-header">
            <div class="auth-form-mark">{_icon("spark")}</div>
            <div class="auth-kicker">Your intelligent workspace</div>
            <h2>{title}</h2>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _auth_secondary_links() -> None:
    screen = st.session_state.auth_screen
    if screen == "login":
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Create account", use_container_width=True, key="link_signup"):
                st.session_state.auth_screen = "signup"
                st.session_state.signup_step = 1
                st.session_state.signup_draft = {}
                st.rerun()
        with c2:
            if st.button("Forgot password?", use_container_width=True, key="link_forgot"):
                st.session_state.auth_screen = "forgot"
                st.session_state.forgot_step = 1
                st.rerun()
    else:
        if st.button("← Back to sign in", use_container_width=True, key="link_login"):
            st.session_state.auth_screen = "login"
            st.session_state.signup_step = 1
            st.session_state.forgot_step = 1
            st.rerun()


def _show_dev_otp(channel: str) -> None:
    code = st.session_state.auth_dev_otp_email
    if code:
        st.info(f"**Demo / dev mode** — {channel.title()} verification code: `{code}`")


def _send_otp(username: str, channel: str, destination: str, purpose: str) -> bool:
    from auth.otp_service import generate_otp, send_email_otp
    from database.sqlite_db import create_auth_otp

    code = generate_otp()
    ok, msg, dev = send_email_otp(destination, code, purpose)
    st.session_state.auth_dev_otp_email = code if dev else ""

    if not ok:
        st.error(msg)
        return False

    create_auth_otp(username, channel, destination, purpose, code)
    st.success(msg)
    if dev:
        _show_dev_otp(channel)
    return True


def _complete_login(user: dict, *, new_session_id_fn, record_login_fn, verified_password: str) -> None:
    from ui.auth_session import begin_login
    begin_login(user["username"], verified_password)


def _validate_username(username: str) -> str | None:
    u = (username or "").strip()
    if len(u) < 3:
        return "Username must be at least 3 characters."
    if not re.match(r"^[a-zA-Z0-9._-]+$", u):
        return "Username may only contain letters, numbers, dots, hyphens, and underscores."
    return None


def _validate_password(password: str) -> str | None:
    if len(password or "") < 6:
        return "Password must be at least 6 characters."
    return None


def _select_demo_account(username: str) -> None:
    # Choose a role without exposing environment-configured credentials or bypassing auth.
    st.session_state.login_username = username
    st.session_state.login_password = ""


def _render_login(*, new_session_id_fn, record_login_fn) -> None:
    with st.form("login_form", border=False):
        username = st.text_input(
            "Username", placeholder="Enter your username", autocomplete="username",
            key="login_username",
        )
        password = st.text_input(
            "Password", type="password", placeholder="Enter your password",
            autocomplete="current-password", key="login_password",
        )
        submitted = st.form_submit_button("Sign in to workspace  →", use_container_width=True, type="primary")
    if submitted:
        if not username.strip() or not password:
            st.error("Enter your username and password to continue.")
        else:
            from database.sqlite_db import authenticate_user

            with st.spinner("Signing in securely…"):
                user = authenticate_user(username, password)
                if user:
                    _complete_login(user, new_session_id_fn=new_session_id_fn, record_login_fn=record_login_fn, verified_password=password)
                else:
                    st.error("We couldn't sign you in. Check your username and password and try again.")
    st.markdown('<div class="auth-demo-label">Explore a demo workspace</div>', unsafe_allow_html=True)
    for col, label, account in zip(st.columns(4), ("Admin", "HR", "Finance", "IT"), ("admin", "hr", "finance", "it")):
        with col:
            st.button(label, key=f"demo_{account}", use_container_width=True,
                      type="primary" if st.session_state.get("login_username") == account else "secondary",
                      on_click=_select_demo_account, args=(account,),
                      help=f"Select the {label} account, then enter its password")
    st.markdown('<p class="auth-demo-note">Select a role, then use its demo account password.</p>', unsafe_allow_html=True)


def _render_signup() -> None:
    from database.sqlite_db import email_exists, register_app_user, username_exists, verify_auth_otp

    step = st.session_state.signup_step
    draft = st.session_state.signup_draft

    if step == 1:
        st.caption("Step 1 of 2 — Account details")
        draft["display_name"] = st.text_input("Full name", value=draft.get("display_name", ""))
        draft["username"] = st.text_input("Username", value=draft.get("username", ""))
        draft["email"] = st.text_input("Work email", value=draft.get("email", ""))
        draft["password"] = st.text_input("Password", type="password", value="")
        draft["password2"] = st.text_input("Confirm password", type="password", value="")
        if st.button("Continue to email verification", use_container_width=True, type="primary"):
            err = _validate_username(draft.get("username", ""))
            if err:
                st.error(err)
            elif _validate_password(draft.get("password", "")):
                st.error(_validate_password(draft.get("password", "")))
            elif draft.get("password") != draft.get("password2"):
                st.error("Passwords do not match.")
            elif username_exists(draft.get("username", "")):
                st.error("Username is already taken.")
            elif email_exists(draft.get("email", "")):
                st.error("Email is already registered.")
            elif not (draft.get("email") or "").strip():
                st.error("Email is required.")
            else:
                st.session_state.signup_draft = draft
                st.session_state.auth_email_verified = False
                st.session_state.signup_step = 2
                st.rerun()

    elif step == 2:
        st.caption("Step 2 of 2 — Verify email")
        email = (draft.get("email") or "").strip()
        st.markdown(f"Code will be sent to **{email}**")
        if st.button("Send email code", use_container_width=True):
            if _send_otp(draft["username"], "email", email, "signup"):
                pass
        code = st.text_input("Email verification code", max_chars=8, key="signup_email_otp")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Complete registration", use_container_width=True, type="primary"):
                if verify_auth_otp(draft["username"], "email", "signup", code):
                    st.session_state.auth_email_verified = True
                    ok, msg = register_app_user(
                        draft["username"],
                        draft["password"],
                        draft["email"],
                        "",
                        draft.get("display_name") or draft["username"],
                    )
                    if ok:
                        st.session_state.signup_step = 1
                        st.session_state.signup_draft = {}
                        st.session_state.auth_screen = "login"
                        st.success("Account created. You can sign in now.")
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.error("Invalid or expired code.")
        with c2:
            if st.button("← Back", use_container_width=True):
                st.session_state.signup_step = 1
                st.rerun()
        _show_dev_otp("email")


def _render_forgot() -> None:
    from database.sqlite_db import (
        get_app_user,
        is_system_account,
        update_app_user_password,
        username_exists,
        verify_auth_otp,
    )

    step = st.session_state.forgot_step

    if step == 1:
        st.caption("Enter your username to begin.")
        username = st.text_input("Username", key="forgot_username_input")
        if st.button("Continue", use_container_width=True, type="primary"):
            u = (username or "").strip()
            if not u:
                st.error("Username is required.")
            elif not username_exists(u):
                st.error("No account found with that username.")
            elif is_system_account(u):
                st.session_state.forgot_username = u
                st.session_state.forgot_step = 99
                st.rerun()
            else:
                profile = get_app_user(u)
                if not profile or not profile.get("email"):
                    st.session_state.forgot_username = u
                    st.session_state.forgot_step = 99
                    st.rerun()
                st.session_state.forgot_username = u
                st.session_state.forgot_profile = profile
                st.session_state.forgot_step = 2
                st.session_state.auth_email_verified = False
                st.rerun()

    elif step == 99:
        st.warning("**Password reset not available for this account.**")
        st.markdown(admin_contact_message())
        if st.button("Return to sign in", use_container_width=True):
            st.session_state.forgot_step = 1
            st.session_state.auth_screen = "login"
            st.rerun()

    elif step == 2:
        u = st.session_state.forgot_username
        profile = st.session_state.get("forgot_profile") or get_app_user(u) or {}
        email = (profile.get("email") or "").strip()
        st.caption("Step 1 of 2 — Verify email")
        if email:
            st.markdown(f"Code will be sent to **{email}**")
            if st.button("Send email code", use_container_width=True):
                _send_otp(u, "email", email, "reset")
            code = st.text_input("Email verification code", max_chars=8)
            if st.button("Verify email", use_container_width=True, type="primary"):
                if verify_auth_otp(u, "email", "reset", code):
                    st.session_state.auth_email_verified = True
                    st.session_state.forgot_step = 3
                    st.success("Email verified.")
                    st.rerun()
                else:
                    st.error("Invalid or expired code.")
        else:
            st.warning("No email on file — contact your administrator.")
        _show_dev_otp("email")

    elif step == 3:
        u = st.session_state.forgot_username
        st.caption("Step 2 of 2 — Set new password")
        new_pw = st.text_input("New password", type="password")
        new_pw2 = st.text_input("Confirm new password", type="password")
        if st.button("Update password", use_container_width=True, type="primary"):
            if not st.session_state.auth_email_verified:
                st.warning("Verify your email first.")
            elif err := _validate_password(new_pw):
                st.error(err)
            elif new_pw != new_pw2:
                st.error("Passwords do not match.")
            else:
                ok, msg = update_app_user_password(u, new_pw)
                if ok:
                    st.session_state.forgot_step = 1
                    st.session_state.auth_screen = "login"
                    st.success("Password updated. Sign in with your new password.")
                    st.rerun()
                else:
                    st.error(msg)


def render_auth_gate(*, new_session_id_fn, record_login_fn) -> None:
    """
    Block the main app until the user signs in.
    Calls st.stop() when not authenticated.
    """
    if st.session_state.get("logged_in"):
        return

    _init_auth_session()
    _inject_auth_styles()

    with st.container(key="auth_root"):
        hero_col, form_col = st.columns([1.08, 1], gap="large")

        with hero_col:
            _auth_hero_panel()

        with form_col:
            with st.container(key="auth_form_panel"):
                _auth_card_header()
                screen = st.session_state.auth_screen
                if screen == "login":
                    _render_login(new_session_id_fn=new_session_id_fn, record_login_fn=record_login_fn)
                elif screen == "signup":
                    _render_signup()
                elif screen == "forgot":
                    _render_forgot()
                _auth_secondary_links()
                setup_note = ""
                if is_hosted_deploy() and not (OPENAI_API_KEY or "").strip():
                    setup_note = (
                        '<details class="auth-configuration"><summary>AI configuration pending</summary>'
                        '<p>An administrator must add OPENAI_API_KEY to Streamlit Secrets to enable AI tools. '
                        'Sign-in remains available.</p></details>'
                    )
                st.markdown(
                    f'<p class="auth-footer-note">{_icon("lock")} Protected by role-based access</p>' + setup_note,
                    unsafe_allow_html=True,
                )


    st.stop()
