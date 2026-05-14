"""Candidate Matching Agent — compare one parsed CV to JD profile with weighted rationale."""

from __future__ import annotations

import json
from typing import Any

from recruitment.llm_utils import get_chat_llm, invoke_json


def match_candidate_to_jd(parsed_cv: dict[str, Any], jd_profile: dict[str, Any]) -> dict[str, Any]:
    llm = get_chat_llm(0.1)
    prompt = f"""You are an expert technical recruiter.

Job profile (JSON):
{json.dumps(jd_profile, ensure_ascii=False)[:18_000]}

Candidate profile (JSON):
{json.dumps(parsed_cv, ensure_ascii=False)[:18_000]}

Score how well the candidate fits this role. Consider: required skill overlap, preferred skills,
experience vs requirement, project relevance, education fit, seniority alignment, soft skills signals.

Return ONLY valid JSON:
{{
  "candidate": "name as in candidate profile",
  "match_score": <integer 0-100>,
  "strengths": ["...", "..."],
  "weaknesses": ["...", "..."],
  "dimensions": {{
    "skills_overlap": <0-100>,
    "experience_relevance": <0-100>,
    "projects_relevance": <0-100>,
    "education_fit": <0-100>,
    "seniority_fit": <0-100>
  }},
  "rationale": "2-4 sentences, factual"
}}"""
    try:
        return invoke_json(llm, prompt)
    except Exception as e:
        return {
            "candidate": parsed_cv.get("name", "Unknown"),
            "match_score": 0,
            "strengths": [],
            "weaknesses": [f"Matching error: {e}"],
            "dimensions": {},
            "rationale": "",
        }
