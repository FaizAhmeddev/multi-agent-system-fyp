"""Finance Portal: REST API (CRUD, auth, duplicates, idempotency, SQL summary) and web screens."""
from __future__ import annotations

import sqlite3

from phelpers import PERSON, H, csrf_of, web_login


def _add(c, **over):
    body = {**PERSON, **over}
    return c.post("/api/v1/people", json=body, headers=H)


def test_api_requires_key(finance):
    assert finance.get("/api/v1/people").status_code == 401
    assert finance.get("/api/v1/people", headers={"X-API-Key": "wrong"}).status_code == 401
    assert finance.get("/api/v1/health").json()["status"] == "ok"  # health is public


def test_crud(finance):
    r = _add(finance)
    assert r.status_code == 201 and r.json()["created"] is True
    p = r.json()["person"]
    assert p["monthly_salary"] == "150000.00" and p["created_via"] == "api"
    pid = p["id"]
    assert finance.get(f"/api/v1/people/{pid}", headers=H).json()["email"] == "ayesha.khan@example.com"
    u = finance.patch(f"/api/v1/people/{pid}", json={"monthly_salary": "155000.50", "status": "inactive"}, headers=H)
    assert u.status_code == 200 and u.json()["monthly_salary"] == "155000.50" and u.json()["status"] == "inactive"
    d = finance.delete(f"/api/v1/people/{pid}", headers=H)
    assert d.status_code == 200 and d.json()["deleted"]["full_name"] == "Ayesha Khan"
    assert finance.get(f"/api/v1/people/{pid}", headers=H).status_code == 404


def test_duplicate_email_rejected(finance):
    assert _add(finance).status_code == 201
    r = _add(finance, email="AYESHA.KHAN@example.com", full_name="Someone Else")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate_email"


def test_idempotent_retry_creates_one_person(finance):
    """Acceptance scenario 5 (person half)."""
    hk = {**H, "Idempotency-Key": "appr-retry-0001"}
    a = finance.post("/api/v1/people", json=PERSON, headers=hk)
    b = finance.post("/api/v1/people", json=PERSON, headers=hk)
    assert a.status_code == 201 and b.status_code == 200 and b.headers["Idempotent-Replay"] == "true"
    assert a.json()["person"]["id"] == b.json()["person"]["id"]
    assert finance.get("/api/v1/people", headers=H).json()["total"] == 1


def test_validation(finance):
    r = _add(finance, department="Payroll", monthly_salary="-5", email="nope")
    assert r.status_code == 422
    fields = {f["field"] for f in r.json()["detail"]["fields"]}
    assert {"department", "monthly_salary", "email"} <= fields


def test_search_filter_sort_paginate(finance):
    people = [("Zara Ahmed", "HR", "200000"), ("Ali Raza", "Finance", "100000"), ("Bina Shah", "Finance", "300000")]
    for i, (n, d, s) in enumerate(people):
        _add(finance, full_name=n, email=f"p{i}@example.com", department=d, monthly_salary=s)
    q = finance.get("/api/v1/people?q=raza", headers=H).json()
    assert [p["full_name"] for p in q["items"]] == ["Ali Raza"]
    f = finance.get("/api/v1/people?department=Finance&sort=monthly_salary&order=desc", headers=H).json()
    assert [p["full_name"] for p in f["items"]] == ["Bina Shah", "Ali Raza"]
    pg = finance.get("/api/v1/people?page_size=2&page=2", headers=H).json()
    assert pg["total"] == 3 and pg["pages"] == 2 and len(pg["items"]) == 1
    assert finance.get("/api/v1/people?sort=password", headers=H).status_code == 422


def test_summary_matches_independent_sql(finance, tmp_path):
    """Acceptance scenario 3 (payroll half): finance_summary's total equals a direct SQL query."""
    for i, s in enumerate(["150000", "120000.75", "99999.25"]):
        _add(finance, email=f"s{i}@example.com", full_name=f"Person {i}", monthly_salary=s)
    _add(finance, email="gone@example.com", full_name="Inactive One", monthly_salary="500000", status="inactive")
    _add(finance, email="usd@example.com", full_name="Usd Person", monthly_salary="2500", currency="USD")
    s = finance.get("/api/v1/summary", headers=H).json()
    pkr = next(r for r in s["payroll_by_currency"] if r["currency"] == "PKR")
    con = sqlite3.connect(str(tmp_path / "finance.db"))
    minor = con.execute("SELECT SUM(salary_minor) FROM people WHERE status='active' AND currency='PKR'").fetchone()[0]
    con.close()
    assert pkr["total_monthly_payroll"] == f"{minor // 100}.{minor % 100:02d}" == "370000.00"
    assert pkr["active_people"] == 3 and s["people_inactive"] == 1


def test_payments(finance):
    pid = _add(finance).json()["person"]["id"]
    r = finance.post(f"/api/v1/people/{pid}/payments", json={"month": "2026-12", "amount": "150000", "status": "paid",
                                                             "paid_on": "2026-12-28"}, headers=H)
    assert r.status_code == 201 and r.json()["currency"] == "PKR"
    dup = finance.post(f"/api/v1/people/{pid}/payments", json={"month": "2026-12", "amount": "1"}, headers=H)
    assert dup.status_code == 409
    lst = finance.get("/api/v1/payments?month=2026-12", headers=H).json()
    assert lst["total"] == 1 and lst["items"][0]["person_name"] == "Ayesha Khan"


def test_web_requires_login_and_csrf(finance):
    r = finance.get("/people", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    page = finance.get("/login")
    bad = finance.post("/login", data={"email": "portal.admin@example.com", "password": "x", "csrf": "forged"})
    assert bad.status_code == 403
    wrong = finance.post("/login", data={"email": "portal.admin@example.com", "password": "nope",
                                         "csrf": csrf_of(page.text)})
    assert wrong.status_code == 401 and "incorrect" in wrong.text


def test_web_crud_csv_and_delete_confirmation(finance):
    web_login(finance)
    page = finance.get("/people/new")
    csrf = csrf_of(page.text)
    form = {**PERSON, "csrf": csrf, "status": "active", "notes": "", "form_key": "abc123"}
    r = finance.post("/people/new", data=form, follow_redirects=False)
    assert r.status_code == 303
    again = finance.post("/people/new", data=form, follow_redirects=False)  # double submit
    assert again.status_code == 303 and again.headers["location"] == r.headers["location"]
    lst = finance.get("/people?q=ayesha")
    assert "Ayesha Khan" in lst.text and "Monthly payroll" in lst.text
    csv = finance.get("/people/export.csv")
    assert csv.headers["content-type"].startswith("text/csv") and "ayesha.khan@example.com" in csv.text
    pid = r.headers["location"].rsplit("/", 1)[1]
    confirm = finance.get(f"/people/{pid}/delete")
    assert "permanently deletes" in confirm.text and "Ayesha Khan" in confirm.text
    wrong = finance.post(f"/people/{pid}/delete", data={"csrf": csrf, "confirm_name": "Ayesha"})
    assert wrong.status_code == 422
    ok = finance.post(f"/people/{pid}/delete", data={"csrf": csrf, "confirm_name": "ayesha  khan"},
                      follow_redirects=False)
    assert ok.status_code == 303
    assert finance.get(f"/people/{pid}").status_code == 404


def test_web_form_validation_is_inline(finance):
    web_login(finance)
    csrf = csrf_of(finance.get("/people/new").text)
    r = finance.post("/people/new", data={"csrf": csrf, "full_name": "A", "email": "bad", "form_key": "k1"})
    assert r.status_code == 422 and 'aria-invalid="true"' in r.text and "Fix the highlighted fields" in r.text


def test_csv_neutralises_formulas(finance):
    _add(finance, full_name="=HYPERLINK(evil)", email="f@example.com")
    web_login(finance)
    assert "'=HYPERLINK(evil)" in finance.get("/people/export.csv").text


def test_staff_lockout(finance):
    csrf = csrf_of(finance.get("/login").text)
    for _ in range(5):
        finance.post("/login", data={"email": "portal.admin@example.com", "password": "bad", "csrf": csrf})
    r = finance.post("/login", data={"email": "portal.admin@example.com", "password": "Portal-Admin-Pass-77",
                                     "csrf": csrf})
    assert r.status_code == 401 and "locked" in r.text.lower()


def test_audit_trail(finance, tmp_path):
    pid = _add(finance).json()["person"]["id"]
    finance.patch(f"/api/v1/people/{pid}", json={"job_title": "Senior Accounts Officer"},
                  headers={**H, "X-Actor": "sana.malik@example.com"})
    con = sqlite3.connect(str(tmp_path / "finance.db"))
    rows = con.execute("SELECT actor, action FROM audit_events ORDER BY id").fetchall()
    con.close()
    assert rows == [("api:client", "person.create"), ("api:sana.malik@example.com", "person.update")]
