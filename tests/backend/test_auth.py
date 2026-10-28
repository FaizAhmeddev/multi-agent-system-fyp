"""Auth: login, lockout (acceptance scenario 1), tokens, password flows."""
from __future__ import annotations

from bhelpers import ADMIN_EMAIL, ADMIN_PASSWORD, auth_header, login
from sqlalchemy import select


def _audit_actions(db, email=None):
    from agentsmind.db.models import AuditLog

    q = select(AuditLog).order_by(AuditLog.id)
    if email:
        q = q.where(AuditLog.actor_email == email)
    db.expire_all()
    return [(a.action, a.outcome) for a in db.scalars(q)]


def test_first_admin_created_from_env_and_can_login(client):
    r = login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == ADMIN_EMAIL and body["user"]["roles"] == ["admin"]
    assert body["token_type"] == "bearer" and body["expires_in"] == 15 * 60
    assert client.get("/api/auth/me", headers=auth_header(body["access_token"])).json()["email"] == ADMIN_EMAIL


def test_email_is_case_insensitive(client):
    assert login(client, email=ADMIN_EMAIL.upper()).status_code == 200


def test_wrong_password_generic_message(client):
    r = login(client, password="not-the-password")
    assert r.status_code == 401
    assert r.json()["detail"] == {"code": "invalid_credentials", "message": "Email or password is incorrect."}
    r2 = login(client, email="nobody@example.com", password="whatever")
    assert r2.json()["detail"] == r.json()["detail"]  # no account enumeration


def test_five_wrong_passwords_lock_the_account(client, db):
    """Acceptance scenario 1."""
    for i in range(4):
        assert login(client, password=f"wrong-{i}").status_code == 401
    fifth = login(client, password="wrong-4")
    assert fifth.status_code == 423
    assert fifth.json()["detail"]["code"] == "account_locked"
    # Even the correct password is refused while locked.
    locked = login(client)
    assert locked.status_code == 423
    actions = _audit_actions(db, ADMIN_EMAIL)
    assert ("auth.lockout", "success") in actions
    assert actions.count(("auth.login", "failure")) == 5
    assert ("auth.login", "denied") in actions


def test_admin_can_unlock_a_locked_user(client, make_user, admin_token):
    u = make_user("finance.lead@example.com", ["finance"])
    for i in range(5):
        login(client, email=u["email"], password=f"bad-{i}")
    assert login(client, email=u["email"], password="Plenty-Long-Passw0rd").status_code == 423
    r = client.post(f"/api/admin/users/{u['id']}/unlock", headers=auth_header(admin_token))
    assert r.status_code == 200
    assert login(client, email=u["email"], password="Plenty-Long-Passw0rd").status_code == 200


def test_successful_login_resets_failure_counter(client):
    for i in range(4):
        login(client, password=f"wrong-{i}")
    assert login(client).status_code == 200
    for i in range(4):
        assert login(client, password=f"again-{i}").status_code == 401  # counter restarted


def test_protected_endpoint_requires_valid_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=auth_header("garbage")).status_code == 401


def test_refresh_rotates_and_detects_reuse(client):
    first = login(client).json()
    r1 = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r1.status_code == 200
    second = r1.json()
    assert second["refresh_token"] != first["refresh_token"]
    # Re-using the old token revokes the whole family, including the new one.
    assert client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh_token(client):
    t = login(client).json()
    assert client.post("/api/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_password_change_invalidates_old_sessions(client):
    import time

    t = login(client).json()
    time.sleep(1.1)  # iat has 1-second resolution
    r = client.post("/api/auth/password/change", headers=auth_header(t["access_token"]),
                    json={"current_password": ADMIN_PASSWORD, "new_password": "Another-Strong-Pass-77"})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me", headers=auth_header(t["access_token"])).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert login(client, password="Another-Strong-Pass-77").status_code == 200


def test_weak_passwords_rejected(client, admin_token):
    for pw in ("short", "password123", "aaaaaaaaaaaaaaaa", "newhire-1234567"):
        r = client.post("/api/admin/users", headers=auth_header(admin_token),
                        json={"email": "newhire@example.com", "full_name": "New Hire", "password": pw,
                              "roles": ["employee"]})
        assert r.status_code == 422, (pw, r.text)


def test_forgot_password_no_enumeration_and_sandbox_outbox(client, admin_token, db):
    a = client.post("/api/auth/password/forgot", json={"email": ADMIN_EMAIL})
    b = client.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    box = client.get("/api/admin/outbox", headers=auth_header(admin_token)).json()["items"]
    assert len(box) == 1 and box[0]["simulated"] is True and box[0]["to"] == ADMIN_EMAIL
    code = box[0]["body"].split("Reset code: ", 1)[1].split()[0]
    r = client.post("/api/auth/password/reset", json={"token": code, "new_password": "Brand-New-Secret-91"})
    assert r.status_code == 200
    assert client.post("/api/auth/password/reset",
                       json={"token": code, "new_password": "Brand-New-Secret-92"}).status_code == 400  # single use
    assert login(client, password="Brand-New-Secret-91").status_code == 200


def test_passwords_are_hashed_with_argon2id(db, client):
    from agentsmind.db.models import User

    u = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
    assert u.password_hash.startswith("$argon2id$")
    assert ADMIN_PASSWORD not in u.password_hash


def test_no_users_and_no_admin_env_fails_clearly(db_url, monkeypatch):
    import pytest
    from agentsmind.auth.service import bootstrap_first_admin
    from agentsmind.db.session import SessionLocal
    from agentsmind.settings import reset_settings_cache

    monkeypatch.delenv("AGENTSMIND_ADMIN_EMAIL")
    monkeypatch.delenv("AGENTSMIND_ADMIN_PASSWORD")
    reset_settings_cache()
    with SessionLocal() as s, pytest.raises(RuntimeError, match="AGENTSMIND_ADMIN_EMAIL"):
        bootstrap_first_admin(s)


def test_weak_first_admin_password_refused(db_url, monkeypatch):
    import pytest
    from agentsmind.auth.service import AuthError, bootstrap_first_admin
    from agentsmind.db.session import SessionLocal
    from agentsmind.settings import reset_settings_cache

    monkeypatch.setenv("AGENTSMIND_ADMIN_PASSWORD", "admin123")
    reset_settings_cache()
    with SessionLocal() as s, pytest.raises(AuthError):
        bootstrap_first_admin(s)
