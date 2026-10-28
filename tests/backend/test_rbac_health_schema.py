"""RBAC on endpoints, /health, settings validation, and migration drift."""
from __future__ import annotations

from datetime import UTC

import pytest
from bhelpers import ROOT, auth_header, login
from sqlalchemy import select


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["checks"]["database"] == "ok"
    assert r.headers["X-Request-ID"]


def test_request_id_is_echoed(client):
    r = client.get("/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"


def test_hr_user_gets_403_on_admin_endpoint_and_it_is_audited(client, make_user, db):
    """Backend half of acceptance scenario 2 (department routes arrive in 1b)."""
    from agentsmind.db.models import AuditLog

    make_user("hr.officer@example.com", ["hr"])
    tok = login(client, email="hr.officer@example.com", password="Plenty-Long-Passw0rd").json()["access_token"]
    r = client.get("/api/admin/users", headers=auth_header(tok))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "forbidden"
    db.expire_all()
    denied = db.scalars(select(AuditLog).where(AuditLog.action == "access.denied")).all()
    assert len(denied) == 1 and denied[0].actor_email == "hr.officer@example.com"
    assert denied[0].target_id == "/api/admin/users"


def test_unknown_role_rejected(client, admin_token):
    r = client.post("/api/admin/users", headers=auth_header(admin_token),
                    json={"email": "x@example.com", "full_name": "X Y", "password": "Plenty-Long-Passw0rd",
                          "roles": ["superuser"]})
    assert r.status_code == 422


def test_duplicate_email_409(client, make_user, admin_token):
    make_user("dup@example.com", ["employee"])
    r = client.post("/api/admin/users", headers=auth_header(admin_token),
                    json={"email": "DUP@example.com", "full_name": "Dup", "password": "Plenty-Long-Passw0rd",
                          "roles": ["employee"]})
    assert r.status_code == 409


def test_validation_errors_are_structured(client):
    r = client.post("/api/auth/login", json={"email": "not-an-email", "password": ""})
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["code"] == "validation_error" and {f["field"] for f in d["fields"]} == {"email", "password"}


def test_settings_require_jwt_secret(monkeypatch):
    from pydantic import ValidationError

    from agentsmind.settings import Settings

    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(_env_file=None)


def test_settings_reject_bad_timezone(monkeypatch):
    from pydantic import ValidationError

    from agentsmind.settings import Settings

    with pytest.raises(ValidationError, match="valid IANA"):
        Settings(_env_file=None, timezone="Mars/Olympus")


def test_migrations_match_models(db_url):
    """Alembic head must equal the SQLAlchemy models (no drift)."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from agentsmind.db import Base
    from agentsmind.db.session import get_engine

    with get_engine().connect() as conn:
        # compare_type is off: SQLite reflects DATETIME without the timezone flag that
        # UTCDateTime declares, which would be a false positive. Tables, columns,
        # nullability, indexes, unique constraints and FKs are still compared.
        mc = MigrationContext.configure(conn, opts={"compare_type": False})
        diff = compare_metadata(mc, Base.metadata)
    assert diff == []


def test_downgrade_to_base_and_back(db_url):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from agentsmind.db.session import get_engine, reset_engine

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "db" / "migrations"))
    cfg.attributes["database_url"] = db_url
    command.downgrade(cfg, "base")
    reset_engine()
    assert set(inspect(get_engine()).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
    reset_engine()
    assert "users" in inspect(get_engine()).get_table_names()


def test_utc_datetimes_round_trip_aware(db):
    from datetime import datetime

    from agentsmind.db.models import AuditLog

    db.add(AuditLog(action="t", detail={}, at=datetime(2026, 1, 1, 12, tzinfo=UTC)))
    db.commit()
    db.expire_all()
    row = db.scalar(select(AuditLog).where(AuditLog.action == "t"))
    assert row.at.tzinfo is not None and row.at.hour == 12
