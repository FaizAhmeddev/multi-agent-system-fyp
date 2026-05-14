"""Job Description Analysis Agent — JD text → structured ideal-candidate profile."""

from __future__ import annotations

from typing import Any

from recruitment.llm_utils import get_chat_llm, invoke_json


def analyze_job_description(jd_text: str, role_title_hint: str = "") -> dict[str, Any]:
    jd = (jd_text or "").strip()
    if not jd:
        return {
            "role_title": role_title_hint or "Open Role",
            "required_skills": [],
            "preferred_skills": [],
            "experience_required_years": None,
            "role_level": "Unknown",
            "education_requirements": "",
            "soft_skills": [],
            "keywords": [],
            "ideal_candidate_summary": "",
            "jd_status": "empty",
        }

    llm = get_chat_llm(0.1)
    prompt = f"""Analyze this job description for recruiting automation.

Optional role title hint: {role_title_hint or "infer from JD"}

Job description:
\"\"\"
{jd[:14_000]}
\"\"\"

Return ONLY valid JSON:
{{
  "role_title": "concise title",
  "required_skills": ["must-have skills"],
  "preferred_skills": ["nice-to-have"],
  "experience_required_years": number or null,
  "role_level": "Intern|Junior|Mid|Senior|Lead|Principal|Manager|Director",
  "education_requirements": "string",
  "soft_skills": ["communication", ...],
  "keywords": ["domain keywords"],
  "ideal_candidate_summary": "3-5 sentences"
}}"""
    try:
        data = invoke_json(llm, prompt)
        data["jd_status"] = "ok"
        return data
    except Exception as e:
        return {
            "role_title": role_title_hint or "Open Role",
            "required_skills": [],
            "preferred_skills": [],
            "experience_required_years": None,
            "role_level": "Unknown",
            "education_requirements": "",
            "soft_skills": [],
            "keywords": [],
            "ideal_candidate_summary": jd[:800],
            "jd_status": f"error:{e}",
        }
