"""
CV Parsing Agent — parallel-safe worker: raw text → normalized structured profile.
"""

from __future__ import annotations

from typing import Any

from recruitment.llm_utils import get_chat_llm, invoke_json


def _fallback_structured(name_hint: str, raw_text: str) -> dict[str, Any]:
    return {
        "name": name_hint or "Candidate",
        "email": "",
        "phone": "",
        "skills": [],
        "experience_years": None,
        "education": "",
        "certifications": [],
        "projects": [],
        "technologies": [],
        "linkedin": "",
        "github": "",
        "summary": (raw_text or "")[:500],
        "source_file": "",
    }


def parse_cv_structured(
    raw_text: str,
    filename: str = "",
    name_hint: str = "Candidate",
) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if len(text) < 40:
        out = _fallback_structured(name_hint, text)
        out["source_file"] = filename
        out["parse_status"] = "insufficient_text"
        return out

    cap = 12_000
    excerpt = text[:cap]
    llm = get_chat_llm(0.05)
    prompt = f"""You extract structured recruiting data from a CV/resume.

Filename hint: {filename}
Preferred display name if unclear: {name_hint}

CV text:
\"\"\"
{excerpt}
\"\"\"

Return ONLY valid JSON with these keys (use null where unknown, arrays can be empty):
{{
  "name": "string",
  "email": "string",
  "phone": "string",
  "skills": ["skill1", ...],
  "experience_years": number or null,
  "education": "string",
  "certifications": ["..."],
  "projects": ["short project line", ...],
  "technologies": ["tool or stack", ...],
  "linkedin": "url or empty",
  "github": "url or empty",
  "summary": "2-3 sentence professional summary"
}}"""
    try:
        data = invoke_json(llm, prompt)
        data["source_file"] = filename
        data["parse_status"] = "ok"
        if not data.get("name"):
            data["name"] = name_hint or "Candidate"
        return data
    except Exception as e:
        out = _fallback_structured(name_hint, text)
        out["source_file"] = filename
        out["parse_status"] = f"error:{e}"
        return out
