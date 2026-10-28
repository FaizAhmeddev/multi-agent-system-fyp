"""Native authentication UI regressions, with no database or network activity.

Run: python FYP_FINAL/scripts/test_auth_pages.py
"""
from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
PREVIEW = '''
import sys
import types
import streamlit as st
sys.path.insert(0, ROOT)
config = types.ModuleType("config")
config.OPENAI_API_KEY = ""
config.admin_contact_message = lambda: "Contact your administrator."
config.is_hosted_deploy = lambda: False
sys.modules["config"] = config
db = types.ModuleType("database.sqlite_db")
def authenticate(username, password):
    st.session_state.last_credentials = (username, password)
    if username == "qa-user" and password == "qa-password":
        return {"username": username, "role": "HR Manager", "name": "QA User"}
    return None
db.authenticate_user = authenticate
db.create_new_conversation = lambda *args: "qa-conversation"
db.touch_user_session = lambda *args: None
for name in ("email_exists", "register_app_user", "username_exists", "verify_auth_otp",
             "get_app_user", "is_system_account", "update_app_user_password"):
    setattr(db, name, lambda *args: False)
sys.modules["database.sqlite_db"] = db
auth_ui = types.ModuleType("ui.auth_session")
def begin_login(username, password):
    st.session_state.pending_verified_login = (username, password)
auth_ui.begin_login = begin_login
sys.modules["ui.auth_session"] = auth_ui
from ui.auth_pages import render_auth_gate
def record(**kwargs):
    st.session_state.login_event = kwargs
render_auth_gate(new_session_id_fn=lambda: "qa-session", record_login_fn=record)
st.success("Authenticated workspace")
'''.replace("ROOT", repr(str(ROOT)))


class AuthPagesTests(unittest.TestCase):
    def app(self):
        app = AppTest.from_string(PREVIEW).run()
        self.assertFalse(app.exception)
        return app

    def submit(self, app):
        next(b for b in app.button if b.label.startswith("Sign in to workspace")).click().run()
        self.assertFalse(app.exception)

    def test_required_fields(self):
        app = self.app()
        self.submit(app)
        self.assertIn("Enter your username and password", app.error[0].value)
        self.assertNotIn("last_credentials", app.session_state)

    def test_credentials_are_forwarded_unchanged(self):
        app = self.app()
        app.text_input(key="login_username").set_value("unknown")
        app.text_input(key="login_password").set_value("wrong-password")
        self.submit(app)
        self.assertEqual(app.session_state.last_credentials, ("unknown", "wrong-password"))
        self.assertIn("couldn't sign you in", app.error[0].value)

    def test_success_waits_for_protected_cookie_exchange(self):
        app = self.app()
        app.text_input(key="login_username").set_value("qa-user")
        app.text_input(key="login_password").set_value("qa-password")
        self.submit(app)
        self.assertEqual(app.session_state.pending_verified_login, ("qa-user", "qa-password"))
        self.assertNotIn("logged_in", app.session_state)
        self.assertNotIn("login_event", app.session_state)

    def test_demo_chips_select_role_without_authenticating(self):
        app = self.app()
        for account in ("admin", "hr", "finance", "it"):
            app.button(key=f"demo_{account}").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.text_input(key="login_username").value, account)
            self.assertEqual(app.text_input(key="login_password").value, "")
            self.assertNotIn("last_credentials", app.session_state)

    def test_signup_and_reset_navigation(self):
        app = self.app()
        app.button(key="link_signup").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.auth_screen, "signup")
        self.assertEqual(len(app.text_input), 5)
        app.button(key="link_login").click().run()
        app.button(key="link_forgot").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.auth_screen, "forgot")
        self.assertEqual(app.text_input[0].label, "Username")
        app.button(key="link_login").click().run()
        self.assertEqual(app.session_state.auth_screen, "login")


if __name__ == "__main__":
    unittest.main()
