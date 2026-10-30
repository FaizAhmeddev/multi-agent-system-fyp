"""What the HR agent does for each intent.

Read-only answers (reports, balances, sheet lookups, records) come back as cards straight away.
Anything that changes records or reaches people is proposed as ONE workflow approval card
listing every step (hr.workflows). Self-service for every employee: check in and out, apply
for leave, see own leave balance and attendance. Everything else needs the HR role, checked
here in code.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from ....hr import calc
from ...base import AgentError, Ctx, Proposal
from ...cards import Card, Detail
from . import parse as P


class _Lazy:
    """Import a module on first use, so routing and tests do not need the database libraries."""

    def __init__(self, name: str):
        self._name, self._mod = name, None

    def __getattr__(self, attr: str):
        if self._mod is None:
            import importlib

            self._mod = importlib.import_module(self._name)
        return getattr(self._mod, attr)


S = _Lazy("agentsmind.hr.service")
letters = _Lazy("agentsmind.hr.letters")
reports = _Lazy("agentsmind.hr.reports")
workflows = _Lazy("agentsmind.hr.workflows")


# ---------------------------------------------------------------------------- context helpers

def db_of(ctx: Ctx):
    db = getattr(ctx, "db", None)
    if db is None:
        raise AgentError("HR records need the AgentsMind database (not available here).")
    return db


def actor(ctx: Ctx):
    u = getattr(ctx, "model_user", None)
    if u is None:
        raise AgentError("Sign in again to use HR actions.")
    return u


def today(ctx: Ctx) -> date:
    return ctx.now.date()


def known_names(db) -> tuple[list[str], dict[str, Any]]:
    from sqlalchemy import select

    from ....db.hr_models import Employee
    from ....db.models import Candidate

    idx: dict[str, Any] = {}
    for e in db.scalars(select(Employee)):
        idx.setdefault(e.full_name.lower(), ("employee", e))
    for c in db.scalars(select(Candidate)):
        idx.setdefault(c.full_name.lower(), ("candidate", c))
    return [k for k in idx], idx


def find_person(ctx: Ctx, text: str, slots: dict[str, str]) -> tuple[str | None, Any, str]:
    """('employee'|'candidate'|None, record, name). The slot name is matched first, then the whole text."""
    db = db_of(ctx)
    names, idx = known_names(db)
    for probe in (slots.get("person", ""), text):
        if not probe:
            continue
        code = re.search(r"\bEMP-\d{4,}\b", probe, re.I)
        if code:
            es = S.find_employees(db, code.group(0))
            if es:
                return "employee", es[0], es[0].full_name
        if slots.get("email"):
            es = S.find_employees(db, slots["email"])
            if es:
                return "employee", es[0], es[0].full_name
        hit = P.name_in_text(probe, names)
        if hit:
            kind, rec = idx[hit]
            return kind, rec, rec.full_name
    name = slots.get("person") or P.new_name(text)
    return None, None, name


def need_employee(ctx: Ctx, text: str, slots: dict[str, str], what: str):
    kind, rec, name = find_person(ctx, text, slots)
    if kind != "employee":
        q = (f"I could not find an employee called '{name}'." if name else "Which employee?") + \
            " Give the full name or employee code (EMP-0001)."
        return None, {"question": q + (f" ({what})" if what else "")}
    return rec, None


def table(title: str, rows: list[dict[str, Any]], columns: list[str], body: str = "", **kw: Any) -> Card:
    return Card(kind="result", agent="hr", title=title, body=body, data={"columns": columns, "rows": rows}, **kw)


def text(title: str, body: str, **kw: Any) -> Card:
    return Card(kind="text", agent="hr", title=title, body=body, **kw)


def jsonsafe(v: Any) -> Any:
    """Approval arguments are stored as JSON: dates become ISO strings."""
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: jsonsafe(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [jsonsafe(x) for x in v]
    return v


def workflow_proposal(ctx: Ctx, *, workflow: str, title: str, steps: list[dict[str, Any]],
                      employee_id: int | None = None, candidate_id: int | None = None,
                      warnings: list[str] | None = None) -> Proposal:
    if not steps:
        raise AgentError("There is nothing to do for this request.")
    args = {"workflow": workflow, "title": title, "steps": jsonsafe(steps), "employee_id": employee_id,
            "candidate_id": candidate_id, "_actor": ctx.user.id}
    details = [Detail(f"{i}. {st['title']}", st.get("summary", "")) for i, st in enumerate(steps, 1)]
    return Proposal(tool="hr_run_workflow", args=args, summary=title, details=details, warnings=warnings or [])


def preview_letter(ctx: Ctx, kind: str, fields: dict[str, Any]) -> dict[str, str]:
    """Render the letter to a preview file (not recorded, nothing sent) so HR can read it before approving."""
    db = db_of(ctx)
    pol = S.get_policy(db)
    preview_dir = letters.DOCS_DIR / "_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    let = letters.build(kind, dict(fields), pol)
    pid = uuid.uuid4().hex[:16]
    pdf = preview_dir / f"{pid}.pdf"
    letters.render_pdf(let, pol["company"], pdf, "PREVIEW")
    return {"label": f"Preview the {letters.KINDS[kind].lower()} (PDF)", "url": f"/api/hr/previews/{pid}.pdf"}


def policy_of(ctx: Ctx) -> dict[str, Any]:
    db = getattr(ctx, "db", None)
    if db is None:
        from ....hr.policy import merged

        return merged(None)
    return S.get_policy(db)


def company_warnings(db) -> list[str]:
    from ....hr.policy import company_ready

    missing = company_ready(S.get_policy(db))
    return [f"Letters will be sent without the {', '.join(missing)}. Add them in HR > Settings."] if missing else []


# ---------------------------------------------------------------------------- employee details from slots

def employee_fields(ctx: Ctx, slots: dict[str, str], name: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    t = today(ctx)
    out = dict(base or {})
    out["full_name"] = out.get("full_name") or name
    for k in ("email", "phone", "job_title", "department", "manager", "location"):
        if slots.get(k):
            out[k] = slots[k]
    if slots.get("salary"):
        amt = P.to_amount(slots["salary"])
        if amt:
            out["monthly_salary"] = amt
    jd = P.to_date(slots.get("joining_date", ""), t)
    if jd:
        out["joining_date"] = jd.isoformat()
    out.setdefault("location", S.get_policy(db_of(ctx))["company"].get("city") or "Karachi")
    return out


def missing_of(emp: dict[str, Any], need: tuple[str, ...]) -> list[str]:
    labels = {"full_name": "full name", "job_title": "job title", "joining_date": "joining date",
              "monthly_salary": "monthly salary", "email": "email address", "department": "department"}
    return [labels[k] for k in need if not emp.get(k)]


# ---------------------------------------------------------------------------- recruitment

def h_create_job(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    title = slots.get("job_title") or P._after(txt, r"job for|vacancy for|position of|opening for|job of|for an?|for")
    title = re.sub(r"\s+in\s+.*$", "", title or "").strip(" .,")
    if not title:
        return {"question": "What is the job title?"}
    req = ""
    m = re.search(r"(?:requirements?|must have|skills?)\s*[:\-]\s*(.+)$", txt, re.I | re.S)
    if m:
        req = m.group(1).strip()
    from ....db.hr_models import HRJob

    j = HRJob(title=title[:200], department=slots.get("department", ""),
              location=slots.get("location") or S.get_policy(db)["recruitment"]["candidate_city"],
              employment_type="permanent", description=_jd_text(title, req), status="open",
              created_by_user_id=ctx.user.id)
    db.add(j)
    db.commit()
    body = (f"Job opening '{j.title}' ({j.location}) is open. Screening will use its requirements. Edit the "
            "requirements in HR > Recruitment, or say for example: 'Screen CVs from Gmail for the "
            f"{j.title} role'.")
    return {"cards": [text("Job opening created", body)]}


def _jd_text(title: str, req: str) -> str:
    items = [x.strip(" -•*") for x in re.split(r"[;\n,]+", req) if x.strip(" -•*")]
    if not items:
        return f"{title}\n\nRequirements:\n- {title} experience"
    return f"{title}\n\nRequirements:\n" + "\n".join(f"- {x}" for x in items)


def _jd_for(ctx: Ctx, role: str) -> tuple[str, str]:
    db = getattr(ctx, "db", None)
    j = S.find_job(db, role) if db is not None else None
    if j is not None and j.description.strip():
        return j.description, f"job opening '{j.title}'"
    for q in (f"{role} job description", role, "job description"):
        r = ctx.read("hr", "drive_search", {"query": q, "page_size": 10})
        if not r.ok:
            break
        jds = [f for f in r.data["items"] if re.search(r"job[_ ]?desc|\bjd\b", f["name"], re.I)]
        if jds:
            d = ctx.read("hr", "drive_read_file", {"file_id": jds[0]["id"]})
            if d.ok:
                return d.data["text"], f"Drive file '{jds[0]['name']}'"
    return _auto_job(ctx, role)


JD_SYSTEM = ("You write short job requirements for a company in Karachi, Pakistan. Reply with 5 to 8 lines, one "
             "requirement per line, each starting with '- '. Use concrete skills, tools and years of experience. "
             "No other text.")


def _auto_job(ctx: Ctx, role: str) -> tuple[str, str]:
    """No opening and no JD file: write the requirements (with the model when one is configured, otherwise from
    the role's own words), save them as a job opening the HR can edit, and screen against them."""
    title = " ".join(w if w.isupper() else w.capitalize() for w in role.split())[:200]
    req = ""
    llm = getattr(ctx, "llm", None)
    if llm is not None and not getattr(llm, "simulated", True):
        try:
            r = llm.complete(f"Job title: {title}\nWrite the requirements.", system=JD_SYSTEM, temperature=0.2)
            lines = [x.strip(" -•*\t") for x in r.text.splitlines() if x.strip(" -•*\t")]
            req = "\n".join(lines[:8])
        except Exception:  # noqa: BLE001 - fall back to the role's words
            req = ""
    words = [w for w in re.findall(r"[A-Za-z+#.]+", title) if w.lower() not in {"senior", "junior", "the", "and", "of"}]
    if not req:
        req = "\n".join([f"{title} experience", *words[:3]])
    description = _jd_text(title, req)
    db = getattr(ctx, "db", None)
    if db is not None:
        from ....db.hr_models import HRJob

        j = HRJob(title=title, department="", location=S.get_policy(db)["recruitment"]["candidate_city"],
                  employment_type="permanent", description=description, status="open",
                  created_by_user_id=ctx.user.id)
        db.add(j)
        db.commit()
    return description, (f"new job opening '{title}' (no opening existed, so its requirements were written "
                         "automatically; edit them in HR > Recruitment and screen again if needed)")


def _recent_count(txt: str) -> int | None:
    """'from my last 20 emails': only the newest N emails, whatever their subject."""
    m = re.search(r"\b(?:last|latest|recent|newest)\s+(\d{1,3})\s+(?:e-?mails?|messages|mails)\b", txt, re.I)
    return min(int(m.group(1)), 100) if m else None


def _top_count(txt: str) -> int | None:
    """'1 best Python developer', 'top 3 candidates', 'give me 2 Java developers'."""
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    m = re.search(r"\b(?:top|best)\s+(\d{1,2}|one|two|three|four|five)\b|\b(\d{1,2}|one|two|three|four|five)\s+"
                  r"(?:best|top|strongest|suitable|good)?\s*[a-z+#. ]{0,30}?" + P.ROLE_NOUNS, txt, re.I)
    if not m:
        return None
    v = (m.group(1) or m.group(2)).lower()
    return words.get(v) or int(v)


def gather_cvs(ctx: Ctx, role: str, sources: set[str], notes: list[str],
               recent: int | None = None) -> list[dict[str, Any]]:
    """CV texts from Gmail attachments, the CV folders and Drive. Each source is optional."""
    pol = policy_of(ctx)
    out: list[dict[str, Any]] = []
    for src in ("gmail", "folder", "drive"):
        if src in sources:
            try:
                out += _from_source(ctx, src, role, pol, notes, recent)
            except AgentError as exc:
                notes.append(f"{src}: {exc}")
            except Exception as exc:  # noqa: BLE001 - one source failing must not stop the others
                notes.append(f"{src}: {type(exc).__name__}")
    seen, uniq = set(), []
    for c in out:
        k = re.sub(r"\s+", " ", c["text"][:400]).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def _from_source(ctx: Ctx, src: str, role: str, pol: dict[str, Any], notes: list[str],
                 recent: int | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    sources = {src}
    if "gmail" in sources:
        query = "newer_than:365d" if recent else _gmail_cv_query(pol, role)
        r = ctx.read("hr", "gmail_find_attachments", {"query": query, "max_messages": recent or 40})
        if r.ok:
            items = r.data["items"][:60]
            if not items:
                notes.append(f"Gmail: no email with a PDF or Word attachment matched the search '{query}' "
                             f"({'the newest ' + str(recent) + ' emails with attachments' if recent else 'all mail'}"
                             f"; {r.data.get('searched', 'unknown')} email(s) with attachments looked at).")
            for a in items:
                hint = re.search(r"\b(cv|resume|curriculum|profile|application|candidate)\b|"
                                 + re.escape(role.split()[0].lower()), f"{a['filename']} {a['subject']}".lower())
                if not hint and not re.search(r"\.(pdf|docx)$", a["filename"].lower()):
                    continue  # plain-text attachments only when the email says it is a CV
                d = ctx.read("hr", "gmail_read_attachment", {"message_id": a["message_id"],
                                                             "attachment": a["attachment"]})
                if d.ok:
                    out.append({"source": "gmail", "ref": f"gmail:{a['message_id']}:{a['attachment']}",
                                "name": a["filename"], "text": d.data["text"], "from": a["sender"]})
        else:
            notes.append(f"Gmail: {r.error}")
    if "folder" in sources:
        r = ctx.read("hr", "cv_folder_list", {"max_files": 200})
        if r.ok:
            for f in r.data["items"][:60]:
                d = ctx.read("hr", "cv_folder_read", {"file_id": f["id"]})
                if d.ok:
                    out.append({"source": "folder", "ref": f["id"], "name": f["name"], "text": d.data["text"],
                                "from": f["folder"]})
        else:
            notes.append(f"CV folder: {r.error}")
    if "drive" in sources:
        r = ctx.read("hr", "drive_search", {"query": "CV", "page_size": 50})
        if r.ok:
            items = [f for f in r.data["items"] if re.search(r"\b(cv|resume)\b", f["name"].replace("_", " "), re.I)]
            for f in items[:30]:
                d = ctx.read("hr", "drive_read_file", {"file_id": f["id"]})
                if d.ok:
                    out.append({"source": "drive", "ref": f["id"], "name": f["name"], "text": d.data["text"],
                                "from": "Google Drive"})
        else:
            notes.append(f"Drive: {r.error}")
    return out


def _gmail_cv_query(pol: dict[str, Any], role: str) -> str:
    """The HR's Gmail search, widened with the role ("Python Developer" CVs often say only that)."""
    q = pol["recruitment"]["gmail_query"]
    role = re.sub(r"[\"()]", " ", role).strip()
    if role and role.lower() not in q.lower() and q.startswith("("):
        q = q.replace(")", f' OR "{role}")', 1)
    return q


def h_screen(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    from ...screening import screen

    pol = policy_of(ctx)
    role = slots.get("job_title") or _role(txt)
    if not role:
        return {"question": "For which role? (for example: Screen CVs for the Python Developer role)"}
    t = txt.lower()
    sources = {s for s, w in (("gmail", ("gmail", "email", "inbox", "mail")), ("drive", ("drive",)),
                              ("folder", ("folder", "computer", "local", "disk"))) if any(x in t for x in w)}
    sources = sources or {"gmail", "folder", "drive"}
    jd_text, jd_src = _jd_for(ctx, role)
    notes: list[str] = []
    recent, top = _recent_count(txt), _top_count(txt)
    if recent:
        sources = {"gmail"}
    cvs = gather_cvs(ctx, role, sources, notes, recent)
    if not cvs:
        raise AgentError("No CVs found (looked in " + ", ".join(sorted(sources)) + "). " + " ".join(notes) +
                         " CVs are read from PDF or Word attachments in Gmail, from the CV folders (data\\cvs or "
                         "HR_CV_DIRS) and from Drive files named CV or resume.")
    rec = pol["recruitment"]
    city = rec["candidate_city"]
    rows, out_city, no_city = [], [], []
    for i, cv in enumerate(cvs, 1):
        ctx.emit({"type": "step", "agent": "hr", "node": "gather", "detail": f"CV {i} of {len(cvs)}"})
        inside, where = calc.location_match(cv["text"], rec)
        if inside is False:
            out_city.append(f"{cv['name']} ({where})")
            continue
        if inside is None and not rec.get("include_unknown_location"):
            no_city.append(cv["name"])
            continue
        r = screen(cv["text"], jd_text, ctx.llm, source=cv["ref"])
        em = P.EMAIL_RE.search(cv["text"])
        ph = P.PHONE_RE.search(cv["text"])
        rows.append({"candidate": r.candidate_label, "file": cv["name"], "file_id": cv["ref"], "source": cv["source"],
                     "location": city if inside else "not stated", "email": em.group(0).lower() if em else "",
                     "phone": ph.group(0) if ph else "", "rubric_score": r.rubric_score,
                     "keyword_score": r.keyword_score, "recommendation": r.recommendation,
                     "needs_human_review": r.needs_human_review, "review_reasons": r.review_reasons,
                     "matched": r.matched, "missing": r.missing, "rubric": r.rubric, "flags": r.flags,
                     "simulated": r.simulated})
    rows.sort(key=lambda x: (x["needs_human_review"], -(x["rubric_score"] or 0)))
    record = getattr(ctx, "record_screening", None)
    if record is not None and rows:
        record(role=role, jd_text=jd_text, jd_file={"name": jd_src}, rows=rows)
    warnings = [f"{x['candidate']}: {'; '.join(x['flags'])}" for x in rows if x["flags"]]
    if out_city:
        warnings.append(f"Not screened, outside {city}: " + ", ".join(out_city[:15]))
    if no_city:
        warnings.append(f"Not screened, no city in the CV: {', '.join(no_city[:15])}. Turn on 'include CVs without "
                        "a location' in HR > Settings to screen them too.")
    warnings += notes
    sim = any(x["simulated"] for x in rows)
    best = ""
    if top and rows:
        pick = [x for x in rows if not x["needs_human_review"]][:top] or rows[:top]
        best = "Best match" + ("es" if len(pick) > 1 else "") + ": " + "; ".join(
            f"{x['candidate']} ({x['file']}, score {x['rubric_score']})" for x in pick) + ". "
        rows = pick + [x for x in rows if x not in pick]
    if sim:
        warnings.append("Simulated rubric: no language model is configured, so a deterministic stand-in rated the "
                        "criteria.")
    body = (f"{best}Found {len(cvs)} CV(s) in {', '.join(sorted(sources))}; screened {len(rows)} {city} candidate(s) against "
            f"the {jd_src}. {sum(1 for x in rows if x['needs_human_review'])} need human review. Scores rank skills "
            "and experience only; protected details were removed first. Next: 'Issue an offer letter to <name>'.")
    return {"cards": [Card(kind="result", agent="hr", title=f"CV screening: {role}", body=body, simulated=sim,
                           untrusted=True, warnings=warnings,
                           data={"columns": ["candidate", "source", "location", "rubric_score", "keyword_score",
                                             "recommendation"], "rows": rows})]}


def _role(txt: str) -> str:
    m = re.search(r"\bfor (?:the |a |an )?([A-Za-z][A-Za-z +#/\-]{2,60}?)(?: role| position| job| vacancy| opening|"
                  r"[.?,]|$)", txt, re.I)
    if not m:
        r = P.ROLE_RE.search(re.sub(r"\b(best|top|suitable|strongest|good|one|two|three|five|\d+|my|last|from|"
                                    r"give|me|fetch|find|get|show|list|the|a|an|e-?mails?|inbox|gmail|cvs?|resumes?|in|of|om|for|"
                                    r"out)\b", " ", txt,
                                    flags=re.I))
        return re.sub(r"\s+", " ", r.group(1)).strip().title() if r else ""
    r = m.group(1).strip()
    return re.sub(r"^(?:cvs?|resumes?)\s+", "", r, flags=re.I)


# ---------------------------------------------------------------------------- letters

LETTER_INTENT = {"offer_letter": "offer", "contract": "contract", "welcome_letter": "welcome",
                 "conduct_letter": "conduct", "experience_letter": "experience",
                 "resignation_acceptance": "resignation_acceptance"}


def h_letter(ctx: Ctx, txt: str, slots: dict[str, str], intent: str) -> dict[str, Any]:
    db = db_of(ctx)
    kind = LETTER_INTENT[intent]
    pkind, rec, name = find_person(ctx, txt, slots)
    email_it = not re.search(r"\b(don'?t|do not|without) (?:email|send)|\bdraft only\b|\bjust (?:generate|create)\b",
                             txt, re.I)
    if kind == "offer":
        if not slots.get("job_title"):
            slots = {**slots, "job_title": _role(txt)} if _role(txt) else slots
        base = S.employee_dict(rec) if pkind == "employee" else {}
        if pkind == "candidate":
            base = {"full_name": rec.full_name, "email": rec.email, "phone": rec.phone, "job_title": rec.job_title}
        emp = employee_fields(ctx, slots, name, base)
        miss = missing_of(emp, ("full_name", "job_title", "monthly_salary", "joining_date") + (
            ("email",) if email_it else ()))
        if miss:
            return {"question": f"For the offer letter I still need: {', '.join(miss)}. For example: 'Offer letter "
                                "for Sara Khan, Python Developer, salary 150,000, joining 1 December, email "
                                "sara@example.com'."}
        valid = P.to_date(slots.get("end_date", ""), today(ctx)) or (today(ctx) + timedelta(days=7))
        fields = {"offer_valid_until": valid, "probation_months": None}
        steps = workflows.letter_steps(db, "offer", emp, fields=fields, email=email_it,
                                       existing_id=rec.id if pkind == "employee" else None)
        prev = preview_letter(ctx, "offer", S.letter_fields(None, {**_letter_base(emp), **fields}))
        p = workflow_proposal(ctx, workflow="offer", title=f"Issue an offer letter to {emp['full_name']}", steps=steps,
                              employee_id=rec.id if pkind == "employee" else None,
                              candidate_id=rec.id if pkind == "candidate" else None, warnings=company_warnings(db))
        return {"proposals": [p], "cards": [Card(kind="text", agent="hr", title="Offer letter preview",
                                                 body="Read the preview, then approve the card to issue and email it.",
                                                 links=[prev])]}
    e, q = need_employee(ctx, txt, slots, f"for the {letters.KINDS[kind].lower()}")
    if q:
        return q
    fields: dict[str, Any] = {}
    if kind == "conduct":
        issue = slots.get("issue") or slots.get("reason") or ""
        issue = re.sub(rf"^{re.escape(e.full_name)}\s*(?:for|about|regarding)?\s*", "", issue, flags=re.I).strip()
        if not issue:
            return {"question": f"What is the conduct issue for {e.full_name}? For example: 'repeated late arrival in "
                                "October'."}
        fields.update(issue=issue, incident_date=P.to_date(slots.get("start_date", ""), today(ctx)))
    if kind == "resignation_acceptance":
        sep = next((s for s in S.separations(db) if s["employee_id"] == e.id and s["status"] != "closed"), None)
        if sep is None and not e.last_working_day:
            return {"question": f"What is {e.full_name}'s last working day? Or say: '{e.full_name} resigned, last "
                                "working day 30 November' to start the separation."}
        fields.update(notice_date=(sep or {}).get("notice_date") or today(ctx),
                      last_working_day=(sep or {}).get("last_working_day") or e.last_working_day)
    if kind == "experience" and not e.last_working_day:
        fields["last_working_day"] = "present"
    emp = S.employee_dict(e)
    steps = workflows.letter_steps(db, kind, emp, fields=fields, email=email_it and bool(e.email), existing_id=e.id)
    prev = preview_letter(ctx, kind, S.letter_fields(e, fields))
    p = workflow_proposal(ctx, workflow=kind, title=f"{letters.KINDS[kind]} for {e.full_name}", steps=steps,
                          employee_id=e.id, warnings=company_warnings(db))
    return {"proposals": [p], "cards": [Card(kind="text", agent="hr", title="Letter preview",
                                             body="Read the preview, then approve the card.", links=[prev])]}


def _letter_base(emp: dict[str, Any]) -> dict[str, Any]:
    return {"name": emp.get("full_name", ""), "email": emp.get("email", ""), "job_title": emp.get("job_title", ""),
            "department": emp.get("department", ""), "joining_date": emp.get("joining_date"),
            "salary": emp.get("monthly_salary"), "manager": emp.get("manager", ""), "location": emp.get("location", "")}


# ---------------------------------------------------------------------------- onboarding, induction

def h_onboard(ctx: Ctx, txt: str, slots: dict[str, str], induction_only: bool = False) -> dict[str, Any]:
    db = db_of(ctx)
    pkind, rec, name = find_person(ctx, txt, slots)
    base: dict[str, Any] = {}
    if pkind == "employee":
        base = S.employee_dict(rec)
    elif pkind == "candidate":
        base = {"full_name": rec.full_name, "email": rec.email, "phone": rec.phone, "job_title": rec.job_title}
    emp = employee_fields(ctx, slots, name, base)
    miss = missing_of(emp, ("full_name", "joining_date", "job_title"))
    if miss:
        return {"question": f"To onboard I need the {', '.join(miss)}. For example: 'Onboard Sara Khan as Python "
                            "Developer in Engineering joining 1 December, salary 150,000, email sara@example.com, "
                            "phone 03001234567'."}
    t = txt.lower()
    options = {"whatsapp": "no whatsapp" not in t, "it_ticket": "no it ticket" not in t,
               "payroll": "no payroll" not in t, "welcome_email": "no email" not in t}
    warnings = company_warnings(db)
    if not emp.get("email"):
        warnings.append("No email address: the welcome email and payroll steps are skipped. Add 'email ...' to "
                        "include them.")
    if not emp.get("monthly_salary"):
        warnings.append("No salary given: the payroll step is skipped.")
    requester = (ctx.user.name, ctx.user.email)
    if induction_only:
        if pkind != "employee":
            return {"question": f"I could not find an employee called '{name}'. Onboard them first."}
        steps = [workflows.step("core", "Create the induction checklist", "Induction items with dates",
                                op="checklists", params={"processes": ["induction"]})]
        steps += [s for s in workflows.onboarding_steps(db, emp, tz=ctx.tz, options=options, existing_id=rec.id,
                                                       requester=requester)
                  if (s.get("task") or [""])[0] == "induction"]
        title = f"Schedule the induction for {emp['full_name']}"
    else:
        steps = workflows.onboarding_steps(db, emp, tz=ctx.tz, options=options,
                                           existing_id=rec.id if pkind == "employee" else None, requester=requester)
        title = f"Onboard {emp['full_name']} ({emp.get('job_title', '')}, joining {emp.get('joining_date')})"
    p = workflow_proposal(ctx, workflow="induction" if induction_only else "onboarding", title=title, steps=steps,
                          employee_id=rec.id if pkind == "employee" else None,
                          candidate_id=rec.id if pkind == "candidate" else None, warnings=warnings)
    return {"proposals": [p]}


# ---------------------------------------------------------------------------- separation, settlement

def h_separation(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    e, q = need_employee(ctx, txt, slots, "who is leaving")
    if q:
        return q
    pol = S.get_policy(db)
    notice = P.to_date(slots.get("start_date", "") or slots.get("notice_date", ""), today(ctx)) or today(ctx)
    last = P.to_date(slots.get("last_working_day", ""), today(ctx))
    if last is None:
        last = notice + timedelta(days=int(pol["payroll"]["notice_days"] or 30))
        guessed = True
    else:
        guessed = False
    kind = slots.get("separation_kind") or ("termination" if re.search(r"terminat", txt, re.I) else "resignation")
    steps = workflows.separation_steps(db, e, kind=kind, last_day=last, notice_date=notice,
                                       reason=slots.get("reason", ""), tz=ctx.tz, email=bool(e.email),
                                       requester=(ctx.user.name, ctx.user.email))
    warnings = company_warnings(db)
    if guessed:
        warnings.append(f"No last working day given: using the {pol['payroll']['notice_days']}-day notice period "
                        f"({last.isoformat()}). Say 'last working day ...' to change it.")
    p = workflow_proposal(ctx, workflow="separation", title=f"Start the {kind} of {e.full_name} (last day "
                          f"{last.isoformat()})", steps=steps, employee_id=e.id, warnings=warnings)
    return {"proposals": [p]}


def h_settlement(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    e, q = need_employee(ctx, txt, slots, "for the final settlement")
    if q:
        return q
    from sqlalchemy import select

    from ....db.hr_models import Separation

    sep = db.scalar(select(Separation).where(Separation.employee_id == e.id, Separation.status != "closed"))
    if sep is None:
        return {"question": f"{e.full_name} has no separation in progress. Start it first: '{e.full_name} resigned, "
                            "last working day ...'."}
    ded = P.to_amount(P._after(txt, r"deduct(?:ion)?s?|minus|less|advance(?: of)?", r"(?=[,;.]|$)")) or 0.0
    add = P.to_amount(P._after(txt, r"plus|bonus(?: of)?|add(?:ition)?s?", r"(?=[,;.]|$)")) or 0.0
    st = S.compute_settlement(db, sep, other_deductions=ded, other_additions=add)
    rows = [{"item": x["item"], "amount": f"{st['currency']} {x['amount']:,.2f}"} for x in st["lines"]]
    rows.append({"item": "Net payable", "amount": f"{st['currency']} {st['net_payable']:,.2f}"})
    steps = workflows.settlement_steps(db, e, sep, settlement=st, email=bool(e.email))
    p = workflow_proposal(ctx, workflow="settlement", title=f"Final settlement for {e.full_name}: {st['currency']} "
                          f"{st['net_payable']:,.2f}", steps=steps, employee_id=e.id,
                          warnings=company_warnings(db) + [st["note"]])
    return {"cards": [table(f"Final settlement: {e.full_name}", rows, ["item", "amount"],
                            "Computed in code from salary, the last working day, leave balance and notice served.")],
            "proposals": [p]}


# ---------------------------------------------------------------------------- attendance

def h_check_in(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    e = S.employee_for_user(db, actor(ctx))
    if e is None:
        raise AgentError("Your sign-in email is not linked to an employee record. Ask HR to add you.")
    row, what = S.check_in_out(db, e, ctx.now)
    body = (f"Checked in at {row.check_in}" + (" (late)." if row.status == "late" else ".")) if what == "check_in" \
        else f"Checked out at {row.check_out}. Checked in at {row.check_in}."
    return {"cards": [text("Attendance", body)]}


def h_attendance_mark(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    e, q = need_employee(ctx, txt, slots, "whose attendance")
    if q:
        return q
    day = P.to_date(slots.get("start_date", ""), today(ctx)) or today(ctx)
    status = slots.get("status") or ""
    if status not in ("present", "absent", "late", "half_day", "leave", "wfh"):
        return {"question": "Mark as present, absent, late, half day or work from home?",
                "options": ["present", "absent", "late", "half day", "work from home"]}
    times = re.findall(r"\b(\d{1,2}[:.]\d{2})\b", txt)
    row = S.mark_attendance(db, e, day, status, check_in=times[0].replace(".", ":") if times else "",
                            check_out=times[1].replace(".", ":") if len(times) > 1 else "", source="manual",
                            note=f"marked by {ctx.user.email}")
    return {"cards": [text("Attendance saved", f"{e.full_name} ({e.code}) marked {row.status.replace('_', ' ')} on "
                                              f"{day.strftime('%a %d %b %Y')}.")]}


def h_attendance_import(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    sheets = S.sheets_for(db, "attendance")
    if not sheets:
        raise AgentError("No attendance sheet is registered. Add it in HR > Sheets (purpose: attendance).")
    sh = sheets[0]
    r = ctx.read("hr", "sheets_read", {"source": sh.source, "location": sh.location, "tab": sh.tab or None,
                                       "max_rows": 5000})
    if not r.ok:
        raise AgentError(r.error)
    headers = r.data["headers"]
    hmap = {_norm(h): h for h in headers}

    def col(*names: str) -> str | None:
        return next((hmap[n] for n in names if n in hmap), None)

    c_name = col("name", "employee", "employee name", "full name")
    c_code = col("code", "employee id", "emp id", "employee code", "id")
    c_day = col("date", "day", "attendance date")
    c_status = col("status", "attendance", "present absent")
    c_in, c_out = col("check in", "in", "time in", "in time"), col("check out", "out", "time out", "out time")
    if not c_day or not (c_name or c_code):
        raise AgentError(f"'{sh.name}' needs a date column and a name or employee code column. Columns found: "
                         f"{', '.join(headers)}.")
    period = calc.parse_period(txt, today(ctx))
    emps = S.list_employees(db)
    by_code = {e.code: e for e in emps}
    by_name = {e.full_name.lower(): e for e in emps}
    rows, skipped = [], 0
    for row in r.data["rows"]:
        e = by_code.get(str(row.get(c_code, "")).strip().upper()) if c_code else None
        e = e or (by_name.get(str(row.get(c_name, "")).strip().lower()) if c_name else None)
        d = P.to_date(str(row.get(c_day, ""))[:10], today(ctx))
        if e is None or d is None or (period and not (period.start <= d <= period.end)):
            skipped += 1
            continue
        st = _status_of(str(row.get(c_status, "")) if c_status else "", str(row.get(c_in, "")) if c_in else "",
                        S.get_policy(db))
        rows.append({"employee_id": e.id, "day": d.isoformat(), "status": st,
                     "check_in": str(row.get(c_in, ""))[:5] if c_in else "",
                     "check_out": str(row.get(c_out, ""))[:5] if c_out else "", "source": sh.source})
    if not rows:
        raise AgentError(f"No rows in '{sh.name}' matched an employee and a date ({skipped} skipped).")
    steps = [workflows.step("core", f"Save {len(rows)} attendance record(s) from '{sh.name}'",
                            f"{skipped} row(s) skipped (unknown employee or date)", op="attendance_import",
                            params={"rows": rows})]
    return {"proposals": [workflow_proposal(ctx, workflow="attendance_import", title=f"Import attendance from "
                                                                                        f"'{sh.name}'", steps=steps)]}


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", h.lower()).strip()


def _status_of(s: str, check_in: str, pol: dict[str, Any]) -> str:
    t = s.strip().lower()
    for k, v in (("absent", "absent"), ("a", "absent"), ("late", "late"), ("half", "half_day"), ("leave", "leave"),
                 ("l", "leave"), ("wfh", "wfh"), ("work from home", "wfh"), ("holiday", "holiday"), ("p", "present"),
                 ("present", "present")):
        if t == k or (len(k) > 1 and k in t):
            return v
    if check_in and check_in[:5] > pol["work"]["late_after"]:
        return "late"
    return "present" if check_in else "absent"


# ---------------------------------------------------------------------------- leave

def h_leave_apply(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    is_hr = ctx.user.has("hr")
    kind, rec, _ = find_person(ctx, txt, slots) if is_hr else (None, None, "")
    e = rec if kind == "employee" else S.employee_for_user(db, actor(ctx))
    if e is None:
        raise AgentError("Your sign-in email is not linked to an employee record. Ask HR to add you.")
    start = P.to_date(slots.get("start_date", ""), today(ctx))
    end = P.to_date(slots.get("end_date", ""), today(ctx)) or start
    if start is None:
        return {"question": "For which dates? For example: 'casual leave on 5 November' or 'annual leave from 10 to 14 "
                            "November'."}
    lt = slots.get("leave_type") or ""
    if lt not in ("annual", "casual", "sick", "unpaid", "maternity", "paternity"):
        return {"question": "Which type of leave?", "options": ["casual", "annual", "sick", "unpaid"]}
    half = bool(re.search(r"\bhalf[ -]?day\b", txt, re.I))
    try:
        r = S.request_leave(db, e, lt, start, end, slots.get("reason", ""), half, user=actor(ctx))
    except S.HRError as exc:
        raise AgentError(str(exc)) from exc
    bal = S.leave_balances(db, e, start.year)[lt]
    body = (f"{lt.capitalize()} leave requested for {e.full_name}: {start.strftime('%d %b')}"
            + (f" to {end.strftime('%d %b %Y')}" if end != start else f" {start.year}")
            + f" ({r.days:g} working day(s)). Status: waiting for HR approval. Remaining after approval: "
              f"{max(bal['remaining'] - r.days, 0):g} day(s).")
    return {"cards": [text("Leave request", body)]}


def h_leave_decide(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    kind, rec, name = find_person(ctx, txt, slots)
    pending = S.leave_requests(db, status="pending", employee_id=rec.id if kind == "employee" else None)
    if not pending:
        return {"cards": [text("Leave", "There are no pending leave requests" + (f" for {name}." if name else "."))]}
    if len(pending) > 1 and kind != "employee":
        return {"cards": [table("Pending leave requests", pending, ["code", "name", "leave_type", "start_date",
                                                                    "end_date", "days", "reason"],
                                "Say for example 'Approve Sara Khan's leave'.")]}
    approve = slots.get("status") != "reject"
    reqs = pending if kind == "employee" else pending[:1]
    steps = []
    for r in reqs:
        steps.append(workflows.step("core", f"{'Approve' if approve else 'Reject'} {r['name']}'s {r['leave_type']} leave",
                                    f"{r['start_date']} to {r['end_date']}, {r['days']:g} day(s)",
                                    op="leave_decision", params={"leave_id": r["id"], "approve": approve}))
    e = S.find_employees(db, reqs[0]["code"])[0]
    if e.email:
        steps.append(workflows.step("tool", "Tell the employee by email", e.email, tool="gmail_send_email",
                                    args={"to": [e.email], "subject": f"Your leave request was "
                                                                      f"{'approved' if approve else 'not approved'}",
                                          "body": f"Dear {e.full_name.split()[0]},\n\nYour {reqs[0]['leave_type']} "
                                                  f"leave from {reqs[0]['start_date']} to {reqs[0]['end_date']} has "
                                                  f"been {'approved' if approve else 'declined'}.\n\nHR"}))
    p = workflow_proposal(ctx, workflow="leave_decision", title=f"{'Approve' if approve else 'Reject'} leave for "
                          f"{e.full_name}", steps=steps, employee_id=e.id)
    return {"proposals": [p]}


def h_leave_balance(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    e = None
    if ctx.user.has("hr"):
        kind, rec, _ = find_person(ctx, txt, slots)
        e = rec if kind == "employee" else None
    e = e or S.employee_for_user(db, actor(ctx))
    if e is None:
        raise AgentError("Your sign-in email is not linked to an employee record. Ask HR to add you.")
    bal = S.leave_balances(db, e, today(ctx).year)
    rows = [{"type": k, "entitled": v["entitled"], "taken": v["taken"], "remaining": v["remaining"]}
            for k, v in bal.items() if k != "unpaid" and (v["entitled"] or v["taken"])]
    return {"cards": [table(f"Leave balance {today(ctx).year}: {e.full_name}", rows,
                            ["type", "entitled", "taken", "remaining"],
                            "Entitlements are pro-rated from the joining date; counted in working days.")]}


# ---------------------------------------------------------------------------- payroll

def h_payroll(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    month = calc.month_key(txt, today(ctx))
    run = S.build_payroll(db, month, actor(ctx))
    rows = [{**ln, "net_text": f"{ln['currency']} {ln['net']:,.2f}"} for ln in run.lines]
    if not rows:
        raise AgentError(f"No employees with a salary for {month}. Salaries come from the employee records "
                         "(set during onboarding or in HR > Employees).")
    tot = "; ".join(f"{c}: {t['employees']} employee(s), gross {t['gross']:,.2f}, deductions {t['deductions']:,.2f}, "
                    f"net {t['net']:,.2f}" for c, t in run.totals.items())
    card = table(f"Payroll {month} ({run.status})", rows, ["code", "name", "department", "gross", "unpaid_leave_days",
                                                           "absent_days", "leave_deduction", "eobi", "tax", "net"],
                 tot + ". Unpaid leave and absences without leave are deducted at the daily rate; joiners and leavers "
                       "are paid for the days employed.", warnings=list({ln["tax_note"] for ln in run.lines
                                                                         if ln["tax_note"]}))
    out: dict[str, Any] = {"cards": [card]}
    if run.status == "draft":
        out["proposals"] = [workflow_proposal(ctx, workflow="payroll", title=f"Post payroll {month} to the Finance "
                                                                             "Portal", steps=workflows.payroll_steps(db, run))]
    return out


# ---------------------------------------------------------------------------- compliance and checklists

def h_compliance(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    kind, rec, _ = find_person(ctx, txt, slots)
    if kind == "employee":
        ts = S.tasks_for(db, rec.id, "compliance") or S.create_checklist(db, rec, "compliance", rec.joining_date)
        rows = [S.task_dict(t) for t in ts]
        done = sum(1 for t in ts if t.status in ("done", "skipped"))
        return {"cards": [table(f"Compliance checklist: {rec.full_name}", rows, ["title", "due_date", "status"],
                                f"{done} of {len(ts)} done. Say for example '{rec.full_name.split()[0]} EOBI "
                                "registration done' to tick an item.")]}
    rep = reports.build(db, "compliance", calc.Period(today(ctx), today(ctx), "today"))
    path = reports.compliance_formats(db)
    return {"cards": [table(rep["title"], rep["rows"], rep["columns"], rep["summary"],
                            links=[{"label": "Download the compliance matrix (Excel)",
                                    "url": f"/api/hr/reports/file/{path.name}"}])]}


TASK_WORDS = {"documents": ("cnic", "documents", "degree", "certificates", "photographs", "experience letters"),
              "bank_details": ("bank",), "buddy": ("buddy",), "offer_accepted": ("signed offer", "accepted the offer",
                                                                                 "offer accepted"),
              "contract": ("contract signed", "signed the contract", "contract"), "eobi": ("eobi",),
              "sessi": ("sessi", "social security"), "tax": ("ntn", "tax"), "nda": ("nda", "confidential"),
              "policy_ack": ("policy", "handbook", "code of conduct"), "emergency_contact": ("emergency",),
              "medical": ("medical", "insurance"), "handover": ("handover",), "assets": ("laptop", "assets", "id card"),
              "access": ("access",), "exit_interview": ("exit interview",), "cnic_copy": ("cnic",),
              "education_verified": ("degree verified", "education"), "experience_verified": ("experience verified",)}


def h_task_update(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    e, q = need_employee(ctx, txt, slots, "whose checklist")
    if q:
        return q
    t = txt.lower()
    keys = [k for k, ws in TASK_WORDS.items() if any(w in t for w in ws)]
    tasks = [x for x in S.tasks_for(db, e.id) if x.key in keys and x.status not in ("done", "skipped")]
    if not tasks:
        open_ = [x for x in S.tasks_for(db, e.id) if x.status not in ("done", "skipped")]
        return {"cards": [table(f"Open checklist items: {e.full_name}", [S.task_dict(x) for x in open_],
                                ["process", "title", "due_date", "status"],
                                "I could not tell which item you mean. Tick it in HR > Employees, or name it, e.g. "
                                "'bank details received'.")]}
    status = "skipped" if re.search(r"\b(not needed|n/?a|skip)\b", t) else "done"
    for x in tasks:
        S.set_task(db, x, status, notes=f"{status} by {ctx.user.email}")
    if any(x.key == "bank_details" for x in tasks):
        S.update_employee(db, e, {"bank_account_on_file": True}, actor(ctx))
    return {"cards": [text("Checklist updated", f"{e.full_name}: " + "; ".join(x.title for x in tasks) +
                           f" marked {status}.")]}


# ---------------------------------------------------------------------------- reports and records

def h_report(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    kind = slots.get("report") or ""
    if kind not in reports.KINDS:
        return {"question": "Which report?", "options": ["new joiners", "induction", "separations", "attendance",
                                                         "leave", "compliance", "payroll", "headcount"]}
    period = calc.parse_period(txt, today(ctx))
    if period is None:
        if kind in ("induction", "onboarding"):
            period = calc.Period(today(ctx) - timedelta(days=90), today(ctx) + timedelta(days=60), "last 90 days and "
                                                                                                  "upcoming")
        else:
            a, b = calc.month_bounds(today(ctx).year, today(ctx).month)
            period = calc.Period(a, b, today(ctx).strftime("%B %Y"))
    pkind, rec, _ = find_person(ctx, txt, slots)
    emp_id = rec.id if pkind == "employee" and kind in ("attendance", "leave", "compliance") else None
    rep = reports.build(db, kind, period, employee_id=emp_id)
    path = reports.export_xlsx(rep)
    return {"cards": [table(rep["title"], rep["rows"], rep["columns"], rep["summary"],
                            links=[{"label": "Download as Excel", "url": f"/api/hr/reports/file/{path.name}"}])]}


def h_lookup(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    kind, rec, name = find_person(ctx, txt, slots)
    if kind == "employee":
        d = S.employee_dict(rec)
        rows = [{"field": k.replace("_", " "), "value": v} for k, v in d.items()
                if k not in ("id", "allowances", "candidate_id") and v not in (None, "", {})]
        progress = {p: S.progress(db, rec.id, p) for p in ("onboarding", "induction", "compliance", "separation")}
        extra = "; ".join(f"{p} {v['done']}/{v['total']}" for p, v in progress.items() if v["total"])
        return {"cards": [table(f"{rec.full_name} ({rec.code})", rows, ["field", "value"], extra,
                                links=[{"label": "Open in HR", "url": f"/hr/employees/{rec.id}"}])]}
    es = S.list_employees(db, department=slots.get("department", ""), status="" if "all" in txt.lower() else
                          "offered,onboarding,active,notice")
    rows = [{"code": e.code, "name": e.full_name, "job_title": e.job_title, "department": e.department,
             "status": e.status, "joining_date": S._iso(e.joining_date)} for e in es]
    note = f"No employee called '{name}'. " if name else ""
    return {"cards": [table("Employees", rows, ["code", "name", "job_title", "department", "status", "joining_date"],
                            note + f"{len(rows)} employee(s).")]}


# ---------------------------------------------------------------------------- sheets

PURPOSE_WORDS = {"leave": ("leave", "leaves", "vacation"), "attendance": ("attendance", "present", "absent", "late"),
                 "new_joiners": ("joiner", "joiners", "joined", "new hire", "onboarding"),
                 "employees": ("employee", "employees", "staff", "headcount", "master"),
                 "payroll": ("payroll", "salary", "salaries", "pay"), "separations": ("separation", "resign", "exit",
                                                                                   "leaver"),
                 "compliance": ("compliance", "eobi", "sessi"), "candidates": ("candidate", "cv", "applicant")}


def purpose_of(txt: str) -> str | None:
    t = txt.lower()
    best = max(PURPOSE_WORDS, key=lambda k: sum(1 for w in PURPOSE_WORDS[k] if re.search(rf"\b{w}", t)))
    return best if any(re.search(rf"\b{w}", t) for w in PURPOSE_WORDS[best]) else None


def h_sheet_where(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    purpose = purpose_of(txt)
    sheets = S.sheets_for(db, purpose) if purpose else S.sheets_for(db)
    if not sheets:
        return {"cards": [text("Your HR sheets", ("No sheet is registered for " + purpose.replace("_", " ") + ". "
                                                   if purpose else "No sheets are registered yet. ")
                               + "Add them in HR > Sheets: paste the Google Sheets link or upload the Excel file and say "
                                 "what it holds.")]}
    rows = [{"name": s.name, "purpose": s.purpose.replace("_", " "), "source": s.source, "tab": s.tab or "first tab",
             "description": s.description} for s in sheets]
    links = [{"label": f"Open '{s.name}'", "url": S.sheet_dict(s)["link"]} for s in sheets if s.source == "google"]
    return {"cards": [table("Where your HR records are kept", rows, ["name", "purpose", "source", "tab", "description"],
                            links=links)]}


class SheetFilter(BaseModel):
    column: str = Field(max_length=100)
    op: Literal["equals", "contains", "after", "before", "greater", "less"] = "contains"
    value: str = Field(max_length=200)


class SheetQuery(BaseModel):
    sheet_id: int
    filters: list[SheetFilter] = Field(default_factory=list, max_length=6)
    count_only: bool = False
    sum_column: str = Field(default="", max_length=100)


def h_sheet_query(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    sheets = S.sheets_for(db)
    if not sheets:
        return h_sheet_where(ctx, txt, slots)
    q: SheetQuery | None = None
    if not getattr(ctx.llm, "simulated", True):
        menu = "\n".join(f"- id {s.id}: '{s.name}' ({s.purpose}); columns: {', '.join(s.headers[:40])}" for s in sheets)
        try:
            q = ctx.llm.complete_json(system="Pick the HR sheet that answers the question and the filters to apply. "
                                             "Use only the listed sheet ids and exact column names. Do not answer the "
                                             "question yourself.",
                                      user=f"Sheets:\n{menu}\n\nQuestion:\n{txt[:1500]}", schema=SheetQuery)
        except Exception:  # noqa: BLE001 - fall back to rules
            q = None
    chosen = next((s for s in sheets if q and s.id == q.sheet_id), None)
    if chosen is None:
        purpose = purpose_of(txt)
        chosen = next((s for s in sheets if s.purpose == purpose), None) or sheets[0]
        q = None
    r = ctx.read("hr", "sheets_read", {"source": chosen.source, "location": chosen.location,
                                       "tab": chosen.tab or None, "max_rows": 5000})
    if not r.ok:
        raise AgentError(r.error)
    _cache_headers(db, chosen, r.data["headers"])
    rows = r.data["rows"]
    headers = r.data["headers"]
    applied = []
    if q is not None:
        for f in q.filters:
            if f.column in headers:
                rows = [x for x in rows if _match(x.get(f.column, ""), f.op, f.value)]
                applied.append(f"{f.column} {f.op} {f.value}")
    else:
        kind, rec, name = find_person(ctx, txt, slots)
        who = rec.full_name if rec is not None else name
        if who:
            ncol = next((h for h in headers if workflows.map_headers([h]).get(h) == "full_name"), None)
            if ncol:
                rows = [x for x in rows if who.lower() in str(x.get(ncol, "")).lower()]
                applied.append(f"{ncol} contains {who}")
    body = f"{len(rows)} row(s) in '{chosen.name}'" + (f" where {'; '.join(applied)}" if applied else "") + "."
    if q is not None and q.sum_column and q.sum_column in headers:
        total = sum(P.to_amount(str(x.get(q.sum_column, ""))) or 0 for x in rows)
        body += f" Total {q.sum_column}: {total:,.2f} (summed in code)."
    cols = [h for h in headers][:12]
    if q is not None and q.count_only:
        return {"cards": [text(f"From '{chosen.name}'", body, untrusted=True)]}
    return {"cards": [table(f"From '{chosen.name}'", rows[:200], cols, body, untrusted=True,
                            links=[{"label": "Open the sheet", "url": r.data.get("link", "")}]
                            if chosen.source == "google" else [])]}


def _match(v: Any, op: str, want: str) -> bool:
    s, w = str(v).strip().lower(), want.strip().lower()
    if op == "equals":
        return s == w
    if op == "contains":
        return w in s
    if op in ("greater", "less"):
        a, b = P.to_amount(s), P.to_amount(w)
        return a is not None and b is not None and (a > b if op == "greater" else a < b)
    da, db_ = P.to_date(s[:10], date.today()), P.to_date(w, date.today())
    if da is None or db_ is None:
        return False
    return da > db_ if op == "after" else da < db_


def _cache_headers(db, sheet, headers: list[str]) -> None:
    from ....db.base import utcnow

    if headers and headers != sheet.headers:
        sheet.headers = headers
    sheet.last_read_at = utcnow()
    db.commit()


def h_sheet_register(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    db = db_of(ctx)
    m = re.search(r"https://docs\.google\.com/spreadsheets/d/[A-Za-z0-9_\-]+[^\s]*", txt)
    x = re.search(r"([\w\- ./\\:]+\.xlsx|[\w\- ./\\:]+\.xlsm)", txt, re.I)
    if not m and not x:
        return {"question": "Paste the Google Sheets link, or the Excel file name in data/hr_sheets (you can upload it "
                            "in HR > Sheets)."}
    source, location = ("google", m.group(0)) if m else ("excel", x.group(1).strip())
    purpose = purpose_of(txt.replace(location, "")) or "other"
    tab = P._after(txt, r"tab|worksheet|sheet named", r"(?=[,;.]|\s+for\b|$)")
    r = ctx.read("hr", "sheets_read", {"source": source, "location": location, "tab": tab or None, "max_rows": 5})
    if not r.ok:
        raise AgentError(r.error)
    from ....db.hr_models import HRSheet

    sh = HRSheet(name=r.data.get("tab") or purpose, purpose=purpose, source=source, location=location,
                 tab=tab or "", description=f"{purpose.replace('_', ' ').capitalize()} records",
                 headers=r.data["headers"], auto_record=True)
    db.add(sh)
    db.commit()
    return {"cards": [text("Sheet registered", f"'{sh.name}' ({source}) is now your {purpose.replace('_', ' ')} sheet. "
                           f"Columns: {', '.join(sh.headers[:20])}. AgentsMind will read it when you ask about "
                           f"{purpose.replace('_', ' ')} and add rows to it after approved actions. Rename it or change "
                           "the purpose in HR > Sheets.")]}


# ---------------------------------------------------------------------------- policy and texts

def h_policy(ctx: Ctx, txt: str, slots: dict[str, str]) -> dict[str, Any]:
    from ....agents import ported as PT

    db = getattr(ctx, "db", None)
    pol = S.get_policy(db) if db is not None else None
    t = txt.lower()
    if pol is not None and re.search(r"\bleaves?\b", t) and re.search(r"(how many|entitle|per year|policy|allowed|get)",
                                                                       t):
        lv = pol["leave"]
        body = (f"Leave entitlement per calendar year: annual {lv['annual']}, casual {lv['casual']}, sick {lv['sick']} "
                f"working days; maternity {lv['maternity']} days; paternity {lv['paternity']} days. Joiners during the "
                "year get a pro-rated share. Unused annual leave is "
                + ("encashed on exit." if lv.get("encash_annual_on_exit") else "not encashed on exit.")
                + " HR can change these in HR > Settings.")
        return {"cards": [text("Leave policy", body)]}
    if pol is not None and re.search(r"\b(notice period|probation|office hours|working hours|timing)\b", t):
        body = (f"Notice period {pol['payroll']['notice_days']} days; probation {pol['payroll']['probation_months']} "
                f"months; office hours {pol['work']['office_start']} to {pol['work']['office_end']} (late after "
                f"{pol['work']['late_after']}).")
        return {"cards": [text("HR policy", body)]}
    r = ctx.llm.complete(PT.hr_policy_answer_prompt(txt, ctx.user.name, ""), temperature=PT.Temperature.HR)
    return {"cards": [Card(kind="text", agent="hr", title="HR", body=r.text, simulated=r.simulated)]}


def h_llm_text(ctx: Ctx, txt: str, slots: dict[str, str], intent: str) -> dict[str, Any]:
    from ....agents import ported as PT

    role = slots.get("job_title") or _role(txt)
    if not role:
        return {"question": "For which role?"}
    if intent == "job_description":
        prompt = PT.hr_job_description_prompt(role, slots.get("department", ""), "")
    else:
        prompt = PT.hr_interview_questions_prompt(f"Role: {role}", "the candidate", "")
    r = ctx.llm.complete(prompt, temperature=PT.Temperature.HR)
    return {"cards": [Card(kind="text", agent="hr", title=intent.replace("_", " ").capitalize(), body=r.text,
                           simulated=r.simulated)]}
