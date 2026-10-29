"""HR ecosystem end to end: assistant -> HR agent -> one workflow approval -> records, letters, email,
IT ticket, payroll, induction invites, WhatsApp and the HR's own Excel sheet (external tools faked in-process)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from bhelpers import ROOT, auth_header, login
from sandbox_executors import register

PW = "Plenty-Long-Passw0rd"


@pytest.fixture(autouse=True)
def _executors(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(ROOT))
    from agentsmind.agents import gateway
    from agentsmind.hr import letters, reports

    saved = dict(gateway.EXECUTORS)
    register(tmp_path, monkeypatch)
    monkeypatch.setattr(letters, "DOCS_DIR", tmp_path / "hr_documents")
    monkeypatch.setattr(reports, "REPORTS_DIR", tmp_path / "hr_reports")
    calls: dict[str, list] = {}

    def fake(name, out):
        def fn(a, key):
            assert key, f"{name} must get an idempotency key"
            calls.setdefault(name, []).append(a)
            return out(a)
        gateway.register_executor(name, fn)

    fake("it_create_ticket", lambda a: {"created": True, "ticket": {"number": f"ITK-00000{len(calls['it_create_ticket'])}",
                                                                    "expected_response": "IT responds in 8 hours."}})
    fake("payroll_enroll_employee", lambda a: {"created": True, "person": {"id": 42, "full_name": a["full_name"]}})
    fake("payroll_end_employment", lambda a: {"id": a["person_id"], "full_name": "x", "status": "inactive"})
    fake("payroll_record_payment", lambda a: {"recorded": True, "payment": {"id": 1, "person_id": a["person_id"],
                                                                            "person_name": "x", "month": a["month"],
                                                                            "amount": a["amount"], "currency": "PKR",
                                                                            "status": "pending", "paid_on": None,
                                                                            "note": ""}})
    fake("whatsapp_send", lambda a: {"sid": "SM1", "to": a["to"], "status": "queued", "already_sent": False, "at": "now"})
    from mcp_servers.workspace_mcp import sheets as sh

    monkeypatch.setenv("WORKSPACE_DATA_DIR", str(tmp_path))
    ex = sh.ExcelSheets()
    gateway.register_executor("sheets_read", lambda a, k: ex.read(a["location"], a.get("tab"), a.get("max_rows", 1000))
                              | {"untrusted": True})
    gateway.register_executor("sheets_append", lambda a, k: ex.append(a["location"], a.get("tab"), a["rows"]))
    yield calls
    gateway.EXECUTORS.clear()
    gateway.EXECUTORS.update(saved)


@pytest.fixture
def hr(make_user, client):
    u = make_user("hira.hr@company.pk", ["hr"])
    return {"id": u["id"], "h": auth_header(login(client, email=u["email"], password=PW).json()["access_token"])}


def say(client, h, text):
    r = client.post("/api/assistant/messages", headers=h, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def approve(client, h, card):
    assert card["kind"] == "approval", card
    r = client.post(f"/api/approvals/{card['approval']['id']}/approve", headers=h, json={})
    assert r.status_code == 200, r.text
    return r.json()


def new_joiners_sheet(tmp_path):
    from openpyxl import Workbook

    p = tmp_path / "hr_sheets"
    p.mkdir(exist_ok=True)
    wb = Workbook()
    wb.active.append(["Employee ID", "Name", "Designation", "Department", "Date of Joining", "Email", "Status"])
    wb.save(p / "joiners.xlsx")
    return "joiners.xlsx"


def test_onboarding_runs_every_step_from_one_approval(client, hr, tmp_path, _executors):
    loc = new_joiners_sheet(tmp_path)
    r = client.post("/api/hr/sheets", headers=hr["h"], json={"name": "New joiners", "purpose": "new_joiners",
                                                             "source": "excel", "location": loc})
    assert r.status_code == 201, r.text
    assert r.json()["headers"][1] == "Name"
    out = say(client, hr["h"], "Onboard Sara Khan as Python Developer in Engineering joining 1 December 2026, salary "
                               "150,000, email sara.khan@company.pk, phone 03001234567")
    card = next(c for c in out["cards"] if c["kind"] == "approval")
    assert card["approval"]["tool"] == "hr_run_workflow"
    labels = [d["label"] for d in card["approval"]["details"]]
    assert any("Add to payroll" in x for x in labels) and any("IT" in x for x in labels)
    assert any("WhatsApp" in x for x in labels) and any("HR sheet" in x for x in labels)
    res = approve(client, hr["h"], card)
    assert res["outcome"]["status"] == "ok", res
    from agentsmind.db.hr_models import Employee
    from agentsmind.db.session import SessionLocal

    with SessionLocal() as db:
        e = db.query(Employee).one()
        assert (e.code, e.status, e.finance_person_id) == ("EMP-0001", "onboarding", "42")
        assert e.joining_date == date(2026, 12, 1) and e.probation_end == date(2027, 3, 1)
    detail = client.get(f"/api/hr/employees/{e.id}", headers=hr["h"]).json()
    done = {t["key"] for t in detail["tasks"] if t["status"] == "done"}
    assert {"it_setup", "payroll", "welcome", "whatsapp", "record", "contract", "orientation"} <= done
    kinds = {x["kind"] for x in detail["letters"]}
    assert {"contract", "welcome"} <= kinds
    assert all(Path(x["pdf_path"]).is_file() for x in detail["letters"])
    assert _executors["it_create_ticket"][0]["requester_email"] == "hira.hr@company.pk"
    assert _executors["whatsapp_send"][0]["to"] == "03001234567"
    rows = client.post("/api/hr/sheets/1/refresh", headers=hr["h"])
    assert rows.status_code == 200
    from openpyxl import load_workbook

    ws = load_workbook(tmp_path / "hr_sheets" / loc).active
    assert [c.value for c in ws[2]][:4] == ["EMP-0001", "Sara Khan", "Python Developer", "Engineering"]
    # the letter downloads
    lid = detail["letters"][0]["id"]
    pdf = client.get(f"/api/hr/letters/{lid}/pdf", headers=hr["h"])
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    # replaying the approval runs nothing twice
    again = client.post(f"/api/approvals/{card['approval']['id']}/approve", headers=hr["h"], json={})
    assert again.status_code == 409
    assert len(_executors["it_create_ticket"]) == 1


def test_offer_letter_for_new_candidate_is_emailed_with_pdf(client, hr, tmp_path):
    out = say(client, hr["h"], "Issue an offer letter to Bilal Ahmed for Data Analyst, salary 120000, joining 5 "
                               "January 2027, email bilal@company.pk")
    preview = next(c for c in out["cards"] if c["kind"] == "text")
    assert preview["links"][0]["url"].startswith("/api/hr/previews/")
    assert client.get(preview["links"][0]["url"], headers=hr["h"]).content[:4] == b"%PDF"
    res = approve(client, hr["h"], next(c for c in out["cards"] if c["kind"] == "approval"))
    steps = res["approval"]["result"]["steps"]
    assert [s["status"] for s in steps] == ["ok", "ok", "ok"], steps
    letters_ = client.get("/api/hr/letters", headers=hr["h"]).json()["items"]
    assert letters_[0]["kind"] == "offer" and letters_[0]["status"] == "sent"


def test_missing_details_are_asked_for(client, hr):
    out = say(client, hr["h"], "Issue an offer letter to Bilal Ahmed")
    assert out["cards"][-1]["kind"] == "clarify" and "monthly salary" in out["cards"][-1]["body"]


def test_employee_self_service_leave_and_check_in(client, hr, make_user):
    u = make_user("omar@company.pk", ["employee"])
    eh = auth_header(login(client, email=u["email"], password=PW).json()["access_token"])
    r = client.post("/api/hr/employees", headers=hr["h"], json={"full_name": "Omar Farooq", "email": "omar@company.pk",
                                                                "joining_date": "2025-01-01", "monthly_salary": 90000})
    assert r.status_code == 201, r.text
    out = say(client, eh, "I want casual leave from 2 November 2026 to 3 November 2026 for a family event")
    assert out["cards"][0]["title"] == "Leave request" and "2 working day" in out["cards"][0]["body"]
    pend = client.get("/api/hr/leave?status=pending", headers=hr["h"]).json()["items"]
    assert len(pend) == 1 and pend[0]["days"] == 2
    assert client.post(f"/api/hr/leave/{pend[0]['id']}/decide", headers=hr["h"], json={"approve": True}).status_code == 200
    me = client.get("/api/me/hr", headers=eh).json()
    assert me["balances"]["casual"]["taken"] == 2
    assert "monthly_salary" not in me["employee"]  # self-service never shows pay
    assert client.post("/api/me/attendance/check", headers=eh, json={}).json()["action"] == "check_in"
    # HR-only things stay closed to employees
    assert say(client, eh, "Run payroll for October 2026")["cards"][0]["kind"] == "denied"
    assert client.get("/api/hr/employees", headers=eh).status_code == 403


def test_payroll_separation_and_settlement(client, hr):
    for name, email, joining in (("Sara Khan", "sara@company.pk", "2025-01-01"),):
        r = client.post("/api/hr/employees", headers=hr["h"], json={"full_name": name, "email": email,
                                                                    "joining_date": joining, "monthly_salary": 150000})
        eid = r.json()["id"]
    run = client.get("/api/hr/payroll/2026-11", headers=hr["h"]).json()
    assert run["status"] == "draft" and run["lines"][0]["net"] == 150000
    out = say(client, hr["h"], "Sara Khan resigned, last working day 20 November 2026")
    res = approve(client, hr["h"], next(c for c in out["cards"] if c["kind"] == "approval"))
    assert res["outcome"]["status"] == "ok"
    emp = client.get(f"/api/hr/employees/{eid}", headers=hr["h"]).json()
    assert emp["employee"]["status"] == "notice" and emp["separation"]["last_working_day"] == "2026-11-20"
    assert any(t["process"] == "separation" for t in emp["tasks"])
    out = say(client, hr["h"], "Final settlement for Sara Khan")
    table = next(c for c in out["cards"] if c["kind"] == "result")
    assert table["data"]["rows"][-1]["item"] == "Net payable"
    res = approve(client, hr["h"], next(c for c in out["cards"] if c["kind"] == "approval"))
    assert res["outcome"]["status"] == "ok"
    emp = client.get(f"/api/hr/employees/{eid}", headers=hr["h"]).json()
    assert emp["employee"]["status"] == "separated"
    assert {"final_settlement", "experience", "resignation_acceptance"} <= {x["kind"] for x in emp["letters"]}


def test_reports_and_excel_export(client, hr):
    client.post("/api/hr/employees", headers=hr["h"], json={"full_name": "Zara Ali", "email": "zara@company.pk",
                                                            "joining_date": "2026-12-03", "status": "onboarding"})
    rep = client.get("/api/hr/reports?kind=new_joiners&period=December 2026", headers=hr["h"]).json()
    assert [r["name"] for r in rep["rows"]] == ["Zara Ali"] and rep["file"].endswith(".xlsx")
    f = client.get(f"/api/hr/reports/file/{rep['file']}", headers=hr["h"])
    assert f.status_code == 200 and f.content[:2] == b"PK"
    out = say(client, hr["h"], "New joiners report for December 2026")
    assert out["cards"][0]["data"]["rows"][0]["name"] == "Zara Ali"
