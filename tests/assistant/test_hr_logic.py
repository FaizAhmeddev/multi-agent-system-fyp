"""HR request understanding and HR arithmetic (pure code, no database)."""
from __future__ import annotations

from datetime import date

import pytest

from agentsmind.assistant.agents.hr.parse import parse, to_amount, to_date
from agentsmind.assistant.orchestrator import plan
from agentsmind.hr import calc
from agentsmind.hr.policy import merged

T = date(2026, 10, 30)


@pytest.mark.parametrize("text,intent", [
    ("Onboard Sara Khan as Python Developer in Engineering joining 1 December, salary 150,000", "onboard"),
    ("Issue an offer letter to Sara Khan for Python Developer, salary 1.5 lakh, joining 1 Dec", "offer_letter"),
    ("Ahmed Raza resigned, last working day 30 November", "separation"),
    ("Final settlement for Ahmed Raza", "final_settlement"),
    ("Gather CVs from Gmail for the Python Developer role", "screen"),
    ("I want casual leave from 3 November to 5 November", "leave_apply"),
    ("Approve Sara's leave", "leave_decide"),
    ("How many leaves do I have left?", "leave_balance"),
    ("Check in", "check_in"),
    ("Mark Bilal absent today", "attendance_mark"),
    ("New joiners report for this month", "report"),
    ("Induction report for October", "report"),
    ("Who resigned this month?", "report"),
    ("Run payroll for October", "payroll_run"),
    ("Generate a warning letter for Bilal for repeated late arrival", "conduct_letter"),
    ("Where do I keep the leave records?", "sheet_where"),
    ("Show Ahmed's leaves from my leave sheet", "sheet_query"),
    ("Sara submitted her CNIC copy", "task_update"),
    ("Compliance checklist for Sara Khan", "compliance"),
    ("Open a job for Data Analyst in Karachi", "create_job"),
    ("Experience letter for Ahmed Raza", "experience_letter"),
    ("What is our maternity leave policy?", "policy"),
    ("How many casual leaves do we get per year?", "policy"),
    ("Import attendance from my attendance sheet", "attendance_import"),
    ("Can you onboard Sara Khan joining next Monday?", "onboard"),
])
def test_rule_intents(text, intent):
    assert parse(None, text, T)[0] == intent


def test_slots_are_converted_by_code():
    _, s, how = parse(None, "Onboard Sara Khan as Python Developer in Engineering joining 1 December with salary "
                            "150,000, email sara.khan@gmail.com, phone 0300-1234567", T)
    assert how == "rules"
    assert s["job_title"] == "Python Developer" and s["department"] == "Engineering"
    assert s["email"] == "sara.khan@gmail.com" and s["phone"] == "0300-1234567"
    assert to_date(s["joining_date"], T) == date(2026, 12, 1)
    assert to_amount(s["salary"]) == 150000
    assert to_amount("1.5 lakh") == 150000 and to_amount("Rs. 120k") == 120000
    assert to_date("01/12/2026", T) == date(2026, 12, 1)  # dd/mm/yyyy as written in Pakistan


@pytest.mark.parametrize("text,agent", [
    ("What is the total monthly payroll?", "finance"),
    ("Run payroll for October", "hr"),
    ("Onboard Sara Khan joining 1 December", "hr"),
    ("I want casual leave tomorrow", "hr"),
    ("Final settlement for Ahmed Raza", "hr"),
    ("Show my unread emails", "email"),
    ("Summarize the leave policy", "documents"),
])
def test_routing_with_hr(text, agent):
    assert [s.agent for s in plan(text)] == [agent]


def test_periods():
    assert calc.parse_period("this month", T) == calc.Period(date(2026, 10, 1), date(2026, 10, 31), "October 2026")
    assert calc.parse_period("last month", T).start == date(2026, 9, 1)
    assert calc.parse_period("Sept 2026", T).end == date(2026, 9, 30)
    assert calc.parse_period("last 7 days", T).start == date(2026, 10, 24)
    assert calc.parse_period("on 1 December", T) is None  # a date, not a period
    assert calc.month_key("October", T) == "2026-10"


def test_leave_entitlement_and_days():
    pol = merged(None)
    assert calc.prorated_entitlement(14, date(2025, 3, 1), 2026) == 14
    assert calc.prorated_entitlement(14, date(2026, 7, 10), 2026) == 7  # 6 of 12 months
    assert calc.leave_days(date(2026, 10, 30), date(2026, 11, 2), pol) == 2  # Fri + Mon, weekend skipped
    b = calc.leave_balances(pol, date(2025, 1, 1), 2026, {"casual": 3})
    assert b["casual"] == {"entitled": 10, "taken": 3, "remaining": 7}


def test_payroll_line_prorates_joiner_and_deducts_unpaid_leave():
    pol = merged(None)
    e = {"id": 1, "full_name": "Sara Khan", "monthly_salary": 150000, "allowances": {"transport": 10000},
         "joining_date": "2026-10-15"}
    ln = calc.payroll_line(employee=e, year=2026, month=10, policy=pol, unpaid_leave_days=1, absent_days=0)
    assert ln["gross"] == 160000 and ln["employed_days"] == 17
    assert ln["proration"] == round(14 * 160000 / 31, 2)
    assert ln["leave_deduction"] == round(160000 / 31, 2)
    assert ln["net"] == round(160000 - ln["proration"] - ln["leave_deduction"], 2)
    assert ln["tax"] == 0 and ln["tax_note"]  # tax is never invented


def test_final_settlement_lines():
    pol = merged(None)
    s = calc.final_settlement(employee={"full_name": "A", "monthly_salary": 150000, "joining_date": "2024-01-01"},
                              last_day=date(2026, 11, 20), policy=pol, annual_remaining=5, notice_date=date(2026, 11, 1))
    items = {x["item"].split(" (")[0]: x["amount"] for x in s["lines"]}
    assert items["Salary for 20 day(s) of November 2026"] == 100000.0
    assert items["Annual leave encashment"] == 25000.0
    assert items["Notice period shortfall"] == -50000.0
    assert s["net_payable"] == 75000.0


def test_karachi_filter():
    rec = merged(None)["recruitment"]
    assert calc.location_match("Sara\nGulshan-e-Iqbal, Karachi\nPython", rec)[0] is True
    assert calc.location_match("Ali\nDHA Phase 6\nPython", rec)[0] is True  # area only
    assert calc.location_match("Usman\nLahore, Pakistan\nPython", rec) == (False, "Lahore")
    assert calc.location_match("Bilal\nskills: python", rec) == (None, "")


def test_general_questions_get_direct_answers(tmp_path):
    from fakectx import FakeCtx

    from agentsmind.assistant.orchestrator import run_turn

    r = run_turn(FakeCtx(tmp_path), "Today date and time")
    assert r.planner == "general" and "Wednesday, 28 October 2026, 11:00 AM" in r.cards[0].body
    assert run_turn(FakeCtx(tmp_path), "hello").cards[0].title.startswith("Hello")
    assert run_turn(FakeCtx(tmp_path), "Hi").cards[0].kind == "text"
    assert run_turn(FakeCtx(tmp_path), "what can you do?").cards[0].title == "What I can do"
    assert run_turn(FakeCtx(tmp_path), "What is the weather like on Mars?").planner == "fallback"  # no model here


def test_screening_without_an_opening_writes_requirements():
    from types import SimpleNamespace

    from agentsmind.assistant.agents.hr.handlers import _auto_job

    class LLM:
        simulated = False

        def complete(self, prompt, system, temperature):
            assert "Python Developer" in prompt
            return SimpleNamespace(text="- Python 3 years\n- Django or FastAPI\n- SQL\n", simulated=False)

    jd, src = _auto_job(SimpleNamespace(llm=LLM(), db=None), "python developer")
    assert jd.startswith("Python Developer") and "- Django or FastAPI" in jd and "new job opening" in src
    jd, _ = _auto_job(SimpleNamespace(llm=SimpleNamespace(simulated=True), db=None), "Data Analyst")
    assert "- Data Analyst experience" in jd


@pytest.mark.parametrize("text,agent", [
    ("From my last 20 emails fetch 1 best python developer", "hr"),
    ("from last 20 emails give me 1 Java Developer", "hr"),
    ("Show me the top 3 data analyst CVs", "hr"),
    ("Email the developer team about the release", "email"),
    ("Show my last 5 emails", "email"),
])
def test_recruiting_from_email_goes_to_hr(text, agent):
    assert [s.agent for s in plan(text)] == [agent]


def test_screening_counts():
    from agentsmind.assistant.agents.hr.handlers import _recent_count, _role, _top_count

    t = "From my last 20 emails fetch 1 best python developer"
    assert (_recent_count(t), _top_count(t), _role(t)) == (20, 1, "Python Developer")
