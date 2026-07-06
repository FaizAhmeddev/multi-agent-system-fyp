"""
Login, sign-up, and forgot-password screens with email OTP verification.
"""

from __future__ import annotations

import re
import streamlit as st

from config import OPENAI_API_KEY, admin_contact_message, is_hosted_deploy


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
    "login": ("🔐", "Welcome back", "Sign in to access your automation workspace."),
    "signup": ("✨", "Create account", "Register with email verification to get started."),
    "forgot": ("🔑", "Reset password", "Verify your identity, then choose a new password."),
}


def _init_auth_session() -> None:
    for k, v in _AUTH_DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v if not isinstance(v, dict) else {}


def _auth_hero_panel() -> None:
    st.markdown(
        """
        <div class="auth-hero-panel">
            <div class="auth-hero-inner">
                <div class="auth-hero-badge">Secure enterprise portal</div>
                <div class="auth-hero-logo">🤖</div>
                <h1>Office Automation Pro</h1>
                <p>Multi-agent AI workspace for HR, Finance, IT, and email — powered by orchestrated automation.</p>
                <ul class="auth-feature-list">
                    <li><span class="auth-feature-icon">⚡</span> Intelligent agent routing</li>
                    <li><span class="auth-feature-icon">🛡️</span> Role-based secure access</li>
                    <li><span class="auth-feature-icon">📊</span> Real-time dashboards & history</li>
                </ul>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _auth_card_header() -> None:
    screen = st.session_state.auth_screen
    icon, title, subtitle = _AUTH_HEADINGS.get(
        screen, ("🔐", "Sign in", "Access your workspace.")
    )
    st.markdown(
        f"""
        <div class="auth-card-header">
            <div class="auth-card-icon">{icon}</div>
            <h2>{title}</h2>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _auth_secondary_links() -> None:
    screen = st.session_state.auth_screen
    st.markdown('<div class="auth-divider"></div>', unsafe_allow_html=True)
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


def _complete_login(user: dict, *, new_session_id_fn, record_login_fn) -> None:
    from database.sqlite_db import (
        create_new_conversation,
        touch_user_session,
    )

    st.session_state.logged_in = True
    st.session_state.username = user["username"]
    st.session_state.user_role = user["role"]
    st.session_state.user_name = user["name"]
    st.session_state.auth_session_id = new_session_id_fn()
    touch_user_session(
        st.session_state.auth_session_id,
        user["username"],
        user["name"],
        user["role"],
    )
    st.session_state.orch_conversation_id = create_new_conversation(
        st.session_state.auth_session_id,
        user["username"],
        "orchestrator",
    )
    st.session_state.orch_chat = []
    st.session_state["_orch_active_cid"] = st.session_state.orch_conversation_id
    st.session_state.pending_hr_gmail_batch_id = None
    st.session_state.hr_ats_batch_id = None
    st.session_state.hr_ats_candidates = []
    st.session_state.hr_ats_filters = {}
    st.session_state.hr_ats_selected = []
    record_login_fn(
        username=user["username"],
        display_name=user["name"],
        role=user["role"],
        event="login",
    )
    st.rerun()


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


def _render_login(*, new_session_id_fn, record_login_fn) -> None:
    username = st.text_input(
        "Username",
        placeholder="Enter your username",
        autocomplete="username",
        key="login_username",
    )
    password = st.text_input(
        "Password",
        type="password",
        placeholder="Enter your password",
        autocomplete="current-password",
        key="login_password",
    )
    if st.button("Sign in", use_container_width=True, type="primary", key="login_submit"):
        from database.sqlite_db import authenticate_user

        user = authenticate_user(username, password)
        if user:
            _complete_login(user, new_session_id_fn=new_session_id_fn, record_login_fn=record_login_fn)
        else:
            st.error("Invalid username or password.")
    st.markdown(
        """
        <div class="auth-demo-pill">
            Demo accounts: <strong>admin</strong> · <strong>hr</strong> · <strong>finance</strong> · <strong>it</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )


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

    st.markdown('<div class="auth-page-wrap">', unsafe_allow_html=True)

    hero_col, form_col = st.columns([1.05, 1], gap="medium")

    with hero_col:
        _auth_hero_panel()

    with form_col:
        st.markdown('<div class="auth-form-shell">', unsafe_allow_html=True)
        st.markdown('<div class="auth-card">', unsafe_allow_html=True)
        _auth_card_header()
        screen = st.session_state.auth_screen
        if screen == "login":
            _render_login(new_session_id_fn=new_session_id_fn, record_login_fn=record_login_fn)
        elif screen == "signup":
            _render_signup()
        elif screen == "forgot":
            _render_forgot()
        _auth_secondary_links()
        st.markdown(
            '<p class="auth-footer-note">Protected by role-based access · KIET Automation Suite</p>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    if is_hosted_deploy() and not (OPENAI_API_KEY or "").strip():
        st.warning(
            "Hosted deploy: add **OPENAI_API_KEY** to Streamlit **Secrets** "
            "(same names as `.env.example`)."
        )

    st.stop()
