"""HR agent: CV screening against a job description, plus drafting HR texts.

Screening reads the job description and CVs from Drive (read tools only), scores each
CV with screening.screen(), and records the results on the candidates board. It never
shortlists or rejects anyone: a person moves candidates between stages.
"""
from __future__ import annotations

import re
from typing import Any

from ...agents import ported as P
from ..base import Agent, AgentError, Ctx, State
from ..cards import Card
from ..screening import screen
from .common import has_any

HR_WORDS = ("cv", "cvs", "resume", "resumes", "candidate", "candidates", "screen", "shortlist", "hiring", "recruit",
            "recruitment", "job description", "interview questions", "onboarding", "hr policy", "applicant",
            "applicants", "vacancy", "job posting")


def _role(text: str) -> str:
    m = re.search(r"\bfor (?:the |a |an )?([A-Za-z][A-Za-z +#/\-]{2,60}?)(?: role| position| job| vacancy|[.?,]|$)",
                  text, re.I)
    return m.group(1).strip() if m else ""


class HRAgent(Agent):
    name = "hr"
    title = "HR agent"
    roles = frozenset({"hr"})
    examples = ("Screen the CVs for the Python Developer role", "Draft a job description for a Data Analyst in Finance",
                "Write interview questions for the Python Developer role", "Onboarding checklist for a new Accountant "
                "in Finance")

    def score(self, text: str) -> float:
        t = text.lower()
        return sum(1.5 for w in HR_WORDS if re.search(rf"\b{re.escape(w)}\b", t))

    def understand(self, ctx: Ctx, state: State) -> State:
        t = state["text"].lower()
        slots: dict[str, Any] = dict(state.get("slots") or {})
        if has_any(t, "screen", "rank", "shortlist", "score", "evaluate", "assess") and has_any(
                t, "cv", "cvs", "resume", "resumes", "candidates", "applicants"):
            intent = "screen"
        elif has_any(t, "job description", "job posting", "jd"):
            intent = "job_description"
        elif has_any(t, "interview questions", "interview question"):
            intent = "interview_questions"
        elif has_any(t, "onboarding"):
            intent = "onboarding"
        else:
            intent = "policy"
        slots.update(intent=intent, role=_role(state["text"]))
        if intent in ("screen", "job_description", "interview_questions") and not slots["role"]:
            return {"intent": intent, "slots": slots, "question": "For which role?"}
        return {"intent": intent, "slots": slots}

    def _find_jd(self, ctx: Ctx, role: str) -> dict[str, Any]:
        for q in (f"{role} job description", role, "job description"):
            d = self.read_or_raise(ctx, "drive_search", {"query": q, "page_size": 10})
            jds = [f for f in d["items"] if re.search(r"job[_ ]?desc|\bjd\b", f["name"], re.I)]
            rw = set(role.lower().split())
            jds.sort(key=lambda f: -len(rw & set(re.split(r"[_ .]", f["name"].lower()))))
            if jds:
                return jds[0]
        raise AgentError(f"I could not find a job description for '{role}' in Drive. Add one (for example "
                         f"'Job_Description_{role.replace(' ', '_')}') and try again.")

    def _cvs(self, ctx: Ctx) -> list[dict[str, Any]]:
        d = self.read_or_raise(ctx, "drive_list_files", {"folder": "HR/CVs", "page_size": 50})
        items = d["items"]
        if not items:  # Google mode: folders are ids, so search by name instead
            items = [f for f in self.read_or_raise(ctx, "drive_search", {"query": "CV", "page_size": 50})["items"]
                     if re.search(r"\b(cv|resume)\b", f["name"].replace("_", " "), re.I)]
        return items[:25]

    def gather(self, ctx: Ctx, state: State) -> State:
        s = state["slots"]
        intent = s["intent"]
        if intent != "screen":
            if intent == "job_description":
                prompt = P.hr_job_description_prompt(s["role"], "", "")
            elif intent == "interview_questions":
                prompt = P.hr_interview_questions_prompt(f"Role: {s['role']}", "the candidate", "")
            elif intent == "onboarding":
                m = re.search(r"\bnew ([A-Za-z ]+?) in (?:the )?([A-Za-z ]+?)(?: department|[.?]|$)", state["text"], re.I)
                jt, dept = (m.group(1), m.group(2)) if m else ("", "")
                missing = P.hr_onboarding_missing(jt, dept)
                if missing:
                    return {"question": missing}
                prompt = P.hr_onboarding_checklist_prompt(jt, dept)
            else:
                prompt = P.hr_policy_answer_prompt(state["text"], ctx.user.name, "")
            r = ctx.llm.complete(prompt, temperature=P.Temperature.HR)
            return {"cards": [Card(kind="text", agent=self.name, title=intent.replace("_", " ").capitalize(),
                                   body=r.text, simulated=r.simulated)]}

        jd_file = self._find_jd(ctx, s["role"])
        jd = self.read_or_raise(ctx, "drive_read_file", {"file_id": jd_file["id"]})
        rows, sim = [], jd["simulated"]
        cvs = [f for f in self._cvs(ctx) if f["id"] != jd_file["id"]]
        if not cvs:
            raise AgentError("No CVs found in Drive (looked in HR/CVs and for files named CV or resume).")
        for i, f in enumerate(cvs, 1):
            ctx.emit({"type": "step", "agent": self.name, "node": "gather", "detail": f"CV {i} of {len(cvs)}"})
            doc = self.read_or_raise(ctx, "drive_read_file", {"file_id": f["id"]})
            r = screen(doc["text"], jd["text"], ctx.llm, source=f"file:{f['id']}")
            sim = sim or r.simulated
            rows.append({"candidate": r.candidate_label, "file": f["name"], "file_id": f["id"],
                         "rubric_score": r.rubric_score, "keyword_score": r.keyword_score,
                         "recommendation": r.recommendation, "needs_human_review": r.needs_human_review,
                         "review_reasons": r.review_reasons, "matched": r.matched, "missing": r.missing,
                         "rubric": r.rubric, "flags": r.flags, "simulated": r.simulated})
        rows.sort(key=lambda x: (x["needs_human_review"], -(x["rubric_score"] or 0)))
        record = getattr(ctx, "record_screening", None)
        if record is not None:
            record(role=s["role"], jd_text=jd["text"], jd_file=jd_file, rows=rows)
        review = sum(1 for x in rows if x["needs_human_review"])
        body = (f"Screened {len(rows)} CV(s) against '{jd_file['name']}'. {review} need human review. Scores rank "
                "skills and experience only; protected details were removed before scoring. Shortlisting is your "
                "decision on the Candidates board.")
        warnings = [f"{x['candidate']}: {'; '.join(x['flags'])}" for x in rows if x["flags"]]
        if sim:
            warnings.append("Simulated rubric: no language model is configured, so a deterministic stand-in rated "
                            "the criteria.")
        return {"cards": [Card(kind="result", agent=self.name, title=f"CV screening: {s['role']}", body=body,
                               simulated=sim, untrusted=True, warnings=warnings,
                               data={"columns": ["candidate", "rubric_score", "keyword_score", "recommendation"],
                                     "rows": rows})]}
