"""CV screening: a rubric score and an independent keyword check.

1. The job description is turned into criteria (must-have and nice-to-have) by code.
2. Keyword check (code only): does the CV mention each criterion's terms?
3. Rubric (model, or a labeled deterministic stand-in in sandbox mode): for each
   criterion, met / partial / not met, with a short quote from the CV as evidence.
   A quote that is not in the CV is discarded and the criterion counts as not met.
4. Scores are weighted sums computed in code (models never do arithmetic).
5. "Needs human review" when the two scores disagree by REVIEW_GAP points or more,
   when the CV contains instructions aimed at the AI, or when evidence was invented.

Protected attributes never reach the model and are never scored: names, contact
details, age and dates of birth, gender, marital status, nationality, religion, photos
and addresses are removed before the rubric step. Screening only ranks; a person
decides who is shortlisted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from ..agents.untrusted import injection_signals, wrap

REVIEW_GAP = 25
MUST_WEIGHT, NICE_WEIGHT = 0.7, 0.3
RATING_VALUE = {"met": 1.0, "partial": 0.5, "not_met": 0.0}

SYNONYMS: dict[str, tuple[str, ...]] = {
    "python": ("python",),
    "fastapi": ("fastapi",),
    "django": ("django",),
    "flask": ("flask",),
    "sql": ("sql", "postgresql", "postgres", "mysql", "sqlite", "sql server"),
    "postgresql": ("postgresql", "postgres"),
    "git": ("git", "github", "gitlab"),
    "code review": ("code review", "code reviews", "reviewed code", "pull request"),
    "docker": ("docker", "container", "containers"),
    "cloud": ("aws", "azure", "gcp", "google cloud", "cloud"),
    "testing": ("pytest", "unit test", "unit tests", "automated test", "automated tests", "test suite", "tdd"),
    "pytest": ("pytest",),
    "react": ("react",),
    "typescript": ("typescript",),
    "javascript": ("javascript",),
    "excel": ("excel",),
    "accounting": ("accounting", "bookkeeping", "ledger"),
    "communication": ("communication", "presenting", "presentation"),
    "linux": ("linux", "ubuntu"),
    "networking": ("networking", "tcp/ip", "dns", "vpn"),
}
WEAK_MARKERS = ("basic", "beginner", "familiar with", "some exposure", "learning", "intern", "small scripts",
                "coursework")


class Criterion(BaseModel):
    name: str
    kind: Literal["must", "nice"]
    terms: list[str]
    min_years: int | None = None


class RubricItem(BaseModel):
    criterion: str = Field(max_length=200)
    rating: Literal["met", "partial", "not_met"]
    evidence: str = Field(default="", max_length=300, description="A short exact quote from the CV, or empty")


class RubricOut(BaseModel):
    items: list[RubricItem] = Field(max_length=30)


@dataclass
class Screening:
    candidate_label: str
    keyword_score: int
    rubric_score: int | None
    matched: list[str]
    missing: list[str]
    rubric: list[dict]
    needs_human_review: bool
    review_reasons: list[str]
    recommendation: str
    simulated: bool
    flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------- job description

def _terms_for(line: str) -> list[str]:
    low = line.lower()
    keys = [k for k, syns in SYNONYMS.items() if any(re.search(rf"\b{re.escape(s)}\b", low) for s in (k, *syns))]
    # prefer the most specific keys (postgresql over sql when both appear in the line)
    if "postgresql" in keys and "sql" in keys and "sql" not in re.sub(r"postgre\w*", "", low):
        keys.remove("sql")
    if keys:
        return keys
    words = [w for w in re.findall(r"[a-z][a-z+#]{2,}", low) if w not in {"and", "with", "the", "years", "year",
                                                                         "professional", "experience", "any",
                                                                         "preferred", "provider", "plus"}]
    return words[:3]


def parse_job_description(text: str) -> list[Criterion]:
    out: list[Criterion] = []
    section: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower().rstrip(":")
        if re.match(r"^(must[- ]have|requirements?|required|essential)\b", low):
            section = "must"
            continue
        if re.match(r"^(nice[- ]to[- ]have|preferred|desirable|bonus)\b", low):
            section = "nice"
            continue
        if not line.startswith(("-", "*", "•")):
            section = None  # any prose line ends the list
            continue
        if section is None:
            continue
        item = line.lstrip("-*• ").strip()
        terms = _terms_for(item)
        if not terms:
            continue
        m = re.search(r"(\d+)\s*\+?\s*years?", item.lower())
        out.append(Criterion(name=item[:120], kind=section, terms=terms, min_years=int(m.group(1)) if m else None))
    if not out:  # unstructured job description: every known skill mentioned is a must-have
        for k in _terms_for(text):
            out.append(Criterion(name=k, kind="must", terms=[k]))
    return out


# ---------------------------------------------------------------------------- redaction

_PHONE = re.compile(r"\+?\d[\d\s\-().]{7,}\d")
_REDACT = [
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[email removed]"),
    (re.compile(r"(?im)^\s*(date of birth|dob|born|age|gender|sex|marital status|married|nationality|citizenship|"
                r"religion|caste|address|photo|picture|father'?s name|cnic|passport)\b.*$"), "[personal detail removed]"),
    (re.compile(r"(?i)\b(he|she|him|her|his|hers|mr|mrs|ms|miss)\b\.?"), "[they]"),
    (re.compile(r"(?i)\b\d{1,2}\s*(?:years?|yrs?)\s*old\b"), "[age removed]"),
]


def redact(cv_text: str, candidate_name: str = "") -> str:
    text = cv_text
    if candidate_name:
        for part in {candidate_name, *candidate_name.split()}:
            if len(part) > 2:
                text = re.sub(rf"\b{re.escape(part)}\b", "Candidate", text)
    lines = text.splitlines()
    if lines and not re.search(r"\b(summary|experience|skills|education)\b", lines[0], re.I):
        lines[0] = "Candidate"  # first line of a CV is usually the name and headline
    text = "\n".join(lines)
    text = _PHONE.sub(lambda m: "[phone removed]" if sum(ch.isdigit() for ch in m.group(0)) >= 10 else m.group(0), text)
    for rx, rep in _REDACT:
        text = rx.sub(rep, text)
    return text


def candidate_name_from(cv_text: str) -> str:
    first = next((ln.strip() for ln in cv_text.splitlines() if ln.strip()), "Candidate")
    return re.sub(r"\s*\(.*?\)\s*", " ", first).strip()[:120] or "Candidate"


# ---------------------------------------------------------------------------- scoring

def _mentions(text: str, terms: list[str]) -> list[str]:
    low = text.lower()
    hits = []
    for t in terms:
        for s in (t, *SYNONYMS.get(t, ())):
            if re.search(rf"\b{re.escape(s)}\b", low):
                hits.append(s)
                break
    return hits


def _years(text: str) -> int | None:
    ys = [int(x) for x in re.findall(r"(\d{1,2})\s*\+?\s*years?", text.lower())]
    return max(ys) if ys else None


def _weighted(values: dict[str, float], crits: list[Criterion]) -> int:
    must = [c for c in crits if c.kind == "must"]
    nice = [c for c in crits if c.kind == "nice"]
    total = 0.0
    if must:
        total += (MUST_WEIGHT if nice else 1.0) * sum(values[c.name] for c in must) / len(must)
    if nice:
        total += (NICE_WEIGHT if must else 1.0) * sum(values[c.name] for c in nice) / len(nice)
    return round(total * 100)


def keyword_check(cv: str, crits: list[Criterion]) -> tuple[int, list[str], list[str]]:
    vals, matched, missing = {}, [], []
    for c in crits:
        hit = bool(_mentions(cv, c.terms))
        if c.min_years is not None:
            y = _years(cv)
            hit = hit and y is not None and y >= c.min_years
        vals[c.name] = 1.0 if hit else 0.0
        (matched if hit else missing).append(c.name)
    return _weighted(vals, crits), matched, missing


def _sandbox_rubric(cv: str, crits: list[Criterion]) -> list[RubricItem]:
    """Deterministic stand-in for the model. Reads context, not just keywords."""
    lines = [ln.strip() for ln in cv.splitlines() if ln.strip()]
    out = []
    for c in crits:
        hit_lines = [ln for ln in lines if _mentions(ln, c.terms)]
        if not hit_lines:
            out.append(RubricItem(criterion=c.name, rating="not_met"))
            continue
        ev = hit_lines[0]
        weak = all(any(w in ln.lower() for w in WEAK_MARKERS) for ln in hit_lines)
        only_skills = all(ln.lower().startswith("skills") for ln in hit_lines)
        rating = "partial" if (weak or only_skills) else "met"
        if c.min_years is not None:
            y = _years(cv)
            if y is None or y < c.min_years:
                rating = "partial" if y else "not_met"
        out.append(RubricItem(criterion=c.name, rating=rating, evidence=ev[:300]))
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def screen(cv_text: str, jd_text: str, llm, *, source: str = "cv") -> Screening:
    crits = parse_job_description(jd_text)
    name = candidate_name_from(cv_text)
    clean = redact(cv_text, name)
    signals = injection_signals(cv_text)
    kw_score, matched, missing = keyword_check(clean, crits)
    reasons: list[str] = []
    flags: list[str] = []
    if signals:
        flags.append("The CV contains text addressed to the AI. It was ignored and did not affect the score.")
        reasons.append("contains instructions aimed at the AI")

    items: list[RubricItem] | None = None
    simulated = bool(getattr(llm, "simulated", True))
    if not simulated:
        crit_lines = "\n".join(f"- {c.name} ({'must have' if c.kind == 'must' else 'nice to have'})" for c in crits)
        w = wrap(clean, source=source)
        try:
            out = llm.complete_json(
                system="You assess a CV against job criteria. Rate each criterion met, partial or not_met and quote "
                       "a short exact phrase from the CV as evidence (empty if none). Judge only skills and "
                       "experience. Never consider or mention age, gender, ethnicity, religion, nationality, "
                       "disability, marital status or names.",
                user=f"Criteria:\n{crit_lines}\n\nCV:\n{w.text}", schema=RubricOut)
            items = out.items if out else None
        except Exception as exc:  # noqa: BLE001 - LLMError or provider failure: fall back, flag for review
            reasons.append(f"rubric step failed ({type(exc).__name__})")
    if items is None:
        items = _sandbox_rubric(clean, crits)
        simulated = True

    by_name = {i.criterion.strip().lower(): i for i in items}
    cv_norm = _norm(clean)
    vals, rubric = {}, []
    invented = False
    for c in crits:
        it = by_name.get(c.name.lower()) or RubricItem(criterion=c.name, rating="not_met")
        rating = it.rating
        if rating != "not_met" and (not it.evidence or _norm(it.evidence) not in cv_norm):
            invented = invented or bool(it.evidence)
            rating = "not_met"
        vals[c.name] = RATING_VALUE[rating]
        rubric.append({"criterion": c.name, "kind": c.kind, "rating": rating, "evidence": it.evidence[:300]})
    if invented:
        reasons.append("the model quoted evidence that is not in the CV")
    rb_score = _weighted(vals, crits) if crits else None
    if rb_score is not None and abs(rb_score - kw_score) >= REVIEW_GAP:
        reasons.append(f"rubric ({rb_score}) and keyword ({kw_score}) scores disagree")
    review = bool(reasons)
    score = rb_score if rb_score is not None else kw_score
    rec = ("needs human review" if review else "strong match" if score >= 70 else "possible match" if score >= 50
           else "weak match")
    return Screening(candidate_label=name, keyword_score=kw_score, rubric_score=rb_score, matched=matched,
                     missing=missing, rubric=rubric, needs_human_review=review, review_reasons=reasons,
                     recommendation=rec, simulated=simulated, flags=flags)
