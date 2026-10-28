"""Equivalence: prompts ported into backend/agentsmind/agents/ported.py must match
the legacy FYP_FINAL agents exactly, for the same inputs (Phase 1b, wrap legacy agents)."""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from agentsmind.agents import ported as P  # noqa: E402


class Capture:
    def __init__(self):
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)

        class R:
            content = "ok"
        return R()


@pytest.fixture
def cap(monkeypatch):
    c = Capture()
    import agents.documents_agent as da
    import agents.hr_agent as ha
    import agents.it_support_agent as ia
    monkeypatch.setattr(ha, "_get_llm", lambda *a, **k: c)
    monkeypatch.setattr(ia, "_get_llm", lambda *a, **k: c)
    monkeypatch.setattr(da, "_get_llm", lambda *a, **k: c)
    return c


JD = "Python developer with FastAPI and SQL experience, 3+ years."
CV = "Zara Hussain. 4 years Python, FastAPI, PostgreSQL. " * 40  # longer than the 1000-char cut


def test_interview_questions(cap):
    import agents.hr_agent as ha
    ha.generate_interview_questions(JD, "Zara Hussain", CV)
    assert cap.prompts[0] == P.hr_interview_questions_prompt(JD, "Zara Hussain", CV)


@pytest.mark.parametrize("title,dept", [("Accounts Officer", "Finance"), ("", "Finance"), ("", "")])
def test_onboarding(cap, title, dept):
    import agents.hr_agent as ha
    legacy = ha.generate_onboarding_checklist(title, dept)
    missing = P.hr_onboarding_missing(title, dept)
    if missing:
        assert legacy == missing and cap.prompts == []
    else:
        assert cap.prompts[0] == P.hr_onboarding_checklist_prompt(title, dept)


@pytest.mark.parametrize("ctx", ["", "Annual leave: 20 days per year. " * 100])
def test_policy_answer(cap, ctx):
    import agents.hr_agent as ha
    ha.answer_hr_query("How many leave days do I get?", "Omar Farooq", ctx)
    assert cap.prompts[0] == P.hr_policy_answer_prompt("How many leave days do I get?", "Omar Farooq", ctx)


@pytest.mark.parametrize("req", ["", "SQL, Excel"])
def test_job_description(cap, req):
    import agents.hr_agent as ha
    ha.draft_job_description("Accounts Officer", "Finance", req)
    assert cap.prompts[0] == P.hr_job_description_prompt("Accounts Officer", "Finance", req)


@pytest.mark.parametrize("problem", ["My laptop cannot connect to office wifi", "Need a new chair for my desk"])
def test_it_troubleshoot(cap, problem, monkeypatch):
    import agents.it_support_agent as ia
    # No knowledge base in tests: make the legacy Chroma lookup and ticket logging no-ops.
    vec = type(sys)("database.vector_db")
    vec.semantic_search = lambda *a, **k: []
    monkeypatch.setitem(sys.modules, "database.vector_db", vec)
    ia.solve_it_problem({"it_problem": problem, "user_name": "Bilal Qureshi"})
    assert cap.prompts[0] == P.it_troubleshoot_prompt(problem, "Bilal Qureshi")
    assert P.detect_it_issue(problem) == ia.detect_it_issue(problem)


def test_doc_summarize_extract_compare(cap):
    import agents.documents_agent as da
    body = "Leave policy. Employees get 20 days annual leave. Effective 1 January 2026. " * 80
    da.summarize_document(body, "leave-policy.pdf", "Hira Siddiqui")
    assert cap.prompts[-1] == P.doc_summarize_prompt(body, "leave-policy.pdf", "Hira Siddiqui")
    for kind in ("dates", "amounts", "all", "unknown-kind"):
        da.extract_data_from_document(body, kind, "leave-policy.pdf")
        assert cap.prompts[-1] == P.doc_extract_prompt(body, kind, "leave-policy.pdf")
    da.compare_documents(body, body[::-1], "a.pdf", "b.pdf")
    assert cap.prompts[-1] == P.doc_compare_prompt(body, body[::-1], "a.pdf", "b.pdf")


def test_ported_module_has_no_emoji():
    import re
    src = open(P.__file__, encoding="utf-8").read()
    assert not re.search("[\U0001F300-\U0001FAFF☀-➿]", src)
