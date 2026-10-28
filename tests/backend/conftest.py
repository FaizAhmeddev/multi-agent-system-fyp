"""Backend test harness: a fresh, Alembic-migrated SQLite database per test."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

# Must be set before agentsmind.main is imported (it builds the app at import).
os.environ["AGENTSMIND_ENV_FILE"] = ""  # never read a developer .env in tests
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["LOG_JSON"] = "true"
os.environ["AGENTSMIND_ADMIN_EMAIL"] = "admin@example.com"
os.environ["AGENTSMIND_ADMIN_PASSWORD"] = "Correct-Horse-Battery-42"
os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(ROOT / "data" / "pytest-import.db").replace("\\", "/"))

from bhelpers import auth_header, login  # noqa: E402


def migrate(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "db" / "migrations"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "test.db").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", url)
    from agentsmind.db.session import reset_engine
    from agentsmind.settings import reset_settings_cache

    reset_settings_cache()
    reset_engine()
    migrate(url)
    yield url
    reset_engine()
    reset_settings_cache()


@pytest.fixture
def db(db_url):
    from agentsmind.db.session import SessionLocal

    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client(db_url):
    from agentsmind.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def admin_token(client):
    r = login(client)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def make_user(client, admin_token):
    def _make(email: str, roles: list[str], password: str = "Plenty-Long-Passw0rd"):  # noqa: S107
        r = client.post("/api/admin/users", headers=auth_header(admin_token),
                        json={"email": email, "full_name": "Test Person", "password": password, "roles": roles})
        assert r.status_code == 201, r.text
        return r.json()
    return _make
