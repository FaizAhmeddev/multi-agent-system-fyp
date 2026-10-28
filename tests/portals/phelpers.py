"""Shared constants and helpers for portal tests."""
from __future__ import annotations

import re

API_KEY = "portal-test-key-" + "k" * 20
ADMIN_EMAIL = "portal.admin@example.com"
ADMIN_PASSWORD = "Portal-Admin-Pass-77"
H = {"X-API-Key": API_KEY}


def csrf_of(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "no csrf token in page"
    return m.group(1)


def web_login(client, path: str = "/login") -> None:
    page = client.get(path)
    r = client.post(path, data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "csrf": csrf_of(page.text)},
                    follow_redirects=False)
    assert r.status_code == 303, r.text


PERSON = {"full_name": "Ayesha Khan", "email": "ayesha.khan@example.com", "department": "Finance",
          "job_title": "Accounts Officer", "employment_type": "full_time", "monthly_salary": "150000",
          "currency": "PKR", "start_date": "2026-12-01"}
