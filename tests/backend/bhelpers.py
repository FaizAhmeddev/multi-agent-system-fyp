"""Shared helpers for backend tests (env is set by conftest.py first)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADMIN_EMAIL = os.environ["AGENTSMIND_ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["AGENTSMIND_ADMIN_PASSWORD"]


def login(client, email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
