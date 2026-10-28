"""Agent registry: who may run each agent, its tools, and its actions.

Actions available in 1b are the ported legacy prompt actions. They are read-only:
they produce text and never call a tool. Tool-using actions (tickets, people records,
calendar, email) arrive with the MCP servers in Phases 2 and 3.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from ..rbac import STAFF_ROLES
from . import ported as P
from .catalog import AGENT_TOOLS, DOC_ROLES
from .llm import LLM


@dataclass(frozen=True)
class AgentOutput:
    text: str
    simulated: bool
    model: str
    meta: dict[str, Any] = field(default_factory=dict)


# ── input schemas ────────────────────────────────────────────────────────────

class InterviewQuestionsIn(BaseModel):
    job_description: str = Field(min_length=10, max_length=8000)
    candidate_name: str = Field(min_length=1, max_length=200)
    cv_content: str = Field(default="", max_length=20000)


class OnboardingIn(BaseModel):
    job_title: str = Field(default="", max_length=200)
    department: str = Field(default="", max_length=200)


class PolicyQuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    policy_context: str = Field(default="", max_length=20000)


class JobDescriptionIn(BaseModel):
    role: str = Field(min_length=2, max_length=200)
    department: str = Field(min_length=2, max_length=200)
    requirements: str = Field(default="", max_length=4000)


class TroubleshootIn(BaseModel):
    problem: str = Field(min_length=5, max_length=4000)


class SummarizeIn(BaseModel):
    document_content: str = Field(min_length=1, max_length=200000)
    file_name: str = Field(default="Document", max_length=255)


class ExtractIn(BaseModel):
    document_content: str = Field(min_length=1, max_length=200000)
    extraction_type: str = Field(default="all", pattern="^(dates|amounts|parties|clauses|contacts|all)$")
    file_name: str = Field(default="Document", max_length=255)


class CompareIn(BaseModel):
    doc1_content: str = Field(min_length=1, max_length=200000)
    doc2_content: str = Field(min_length=1, max_length=200000)
    doc1_name: str = Field(default="Doc 1", max_length=255)
    doc2_name: str = Field(default="Doc 2", max_length=255)


# ── actions ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Action:
    name: str
    title: str
    schema: type[BaseModel]
    run: Callable[[BaseModel, str, LLM], AgentOutput]  # (inputs, user_display_name, llm)


def _llm_out(llm: LLM, prompt: str, temperature: float, **meta) -> AgentOutput:
    r = llm.complete(prompt, temperature=temperature)
    return AgentOutput(text=r.text, simulated=r.simulated, model=r.model, meta=meta)


def _plain(text: str) -> AgentOutput:
    return AgentOutput(text=text, simulated=False, model="none", meta={"answered_without_llm": True})


def _interview(i: InterviewQuestionsIn, _user: str, llm: LLM) -> AgentOutput:
    return _llm_out(llm, P.hr_interview_questions_prompt(i.job_description, i.candidate_name, i.cv_content),
                    P.Temperature.HR)


def _onboarding(i: OnboardingIn, _user: str, llm: LLM) -> AgentOutput:
    missing = P.hr_onboarding_missing(i.job_title, i.department)
    if missing:
        return _plain(missing)
    return _llm_out(llm, P.hr_onboarding_checklist_prompt(i.job_title, i.department), P.Temperature.HR)


def _policy(i: PolicyQuestionIn, user: str, llm: LLM) -> AgentOutput:
    return _llm_out(llm, P.hr_policy_answer_prompt(i.question, user, i.policy_context), P.Temperature.HR,
                    policy_source="provided" if i.policy_context else "none")


def _jd(i: JobDescriptionIn, _user: str, llm: LLM) -> AgentOutput:
    return _llm_out(llm, P.hr_job_description_prompt(i.role, i.department, i.requirements), P.Temperature.HR_JD)


def _troubleshoot(i: TroubleshootIn, user: str, llm: LLM) -> AgentOutput:
    return _llm_out(llm, P.it_troubleshoot_prompt(i.problem, user), P.Temperature.IT)


def _summarize(i: SummarizeIn, user: str, llm: LLM) -> AgentOutput:
    if len(i.document_content.strip()) < 30:
        return _plain(f"'{i.file_name}' is empty or too short to summarize.")
    return _llm_out(llm, P.doc_summarize_prompt(i.document_content, i.file_name, user), P.Temperature.DOCS)


def _extract(i: ExtractIn, _user: str, llm: LLM) -> AgentOutput:
    return _llm_out(llm, P.doc_extract_prompt(i.document_content, i.extraction_type, i.file_name),
                    P.Temperature.DOCS)


def _compare(i: CompareIn, _user: str, llm: LLM) -> AgentOutput:
    return _llm_out(llm, P.doc_compare_prompt(i.doc1_content, i.doc2_content, i.doc1_name, i.doc2_name),
                    P.Temperature.DOCS)


@dataclass(frozen=True)
class AgentSpec:
    name: str
    title: str
    department: str
    roles: frozenset[str]  # who may run it (admin always may)
    tools: frozenset[str]
    actions: dict[str, Action]


def _actions(*acts: Action) -> dict[str, Action]:
    return {a.name: a for a in acts}


AGENTS: dict[str, AgentSpec] = {a.name: a for a in (
    AgentSpec("hr", "HR agent", "hr", frozenset({"hr"}), AGENT_TOOLS["hr"], _actions(
        Action("interview_questions", "Draft interview questions", InterviewQuestionsIn, _interview),
        Action("onboarding_checklist", "Draft onboarding checklist", OnboardingIn, _onboarding),
        Action("policy_answer", "Answer an HR policy question", PolicyQuestionIn, _policy),
        Action("job_description", "Draft a job description", JobDescriptionIn, _jd),
    )),
    AgentSpec("it", "IT agent", "it", STAFF_ROLES, AGENT_TOOLS["it"], _actions(
        Action("troubleshoot", "Suggest troubleshooting steps", TroubleshootIn, _troubleshoot),
    )),
    AgentSpec("documents", "Documents agent", "documents", DOC_ROLES, AGENT_TOOLS["documents"], _actions(
        Action("summarize", "Summarize a document", SummarizeIn, _summarize),
        Action("extract", "Extract data from a document", ExtractIn, _extract),
        Action("compare", "Compare two documents", CompareIn, _compare),
    )),
    AgentSpec("finance", "Finance agent", "finance", frozenset({"finance"}), AGENT_TOOLS["finance"], {}),
    AgentSpec("email", "Email agent", "communications", STAFF_ROLES, AGENT_TOOLS["email"], {}),
    AgentSpec("calendar", "Calendar agent", "communications", STAFF_ROLES, AGENT_TOOLS["calendar"], {}),
)}
