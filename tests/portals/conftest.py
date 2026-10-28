"""Fixtures for the two external portals (each with its own temporary database)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "external_systems"))

from phelpers import ADMIN_EMAIL, ADMIN_PASSWORD, API_KEY  # noqa: E402


def _cfg(tmp_path, name: str) -> dict:
    return {"db_url": "sqlite:///" + str(tmp_path / f"{name}.db").replace("\\", "/"), "api_key": API_KEY,
            "secret_key": "s" * 40, "admin_email": ADMIN_EMAIL, "admin_password": ADMIN_PASSWORD,
            "public_url": "http://testserver", "upload_dir": str(tmp_path / "uploads")}


@pytest.fixture
def finance(tmp_path):
    from fastapi.testclient import TestClient

    from finance_portal.app import create_app

    with TestClient(create_app(_cfg(tmp_path, "finance"))) as c:
        yield c


@pytest.fixture
def it(tmp_path):
    from fastapi.testclient import TestClient

    from it_portal.app import create_app

    with TestClient(create_app(_cfg(tmp_path, "it"))) as c:
        yield c
