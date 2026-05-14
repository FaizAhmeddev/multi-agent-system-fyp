"""
AGENTS/HR_AGENT.PY
===================
HR Agent — CV screening, interview questions, onboarding, HR Q&A.
"""

import os
import json


def _get_llm(temp=0.3):
    from langchain_openai import ChatOpenAI
    from config import OPENAI_API_KEY
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
    return ChatOpenAI(model="gpt-4o-mini", temperature=temp)


def screen_candidates(job_description: str, cvs: list) -> list:
    """Rank and evaluate candidates based on job description."""
    results = []
    llm = _get_llm()

    for cv in cvs:
        prompt = f"""You are a professional HR recruiter.

Job Description:
{job_description}

Candidate CV:
Name: {cv['name']}
{cv['content'][:3000]}

Evaluate this candidate strictly. Return ONLY valid JSON (no extra text):
{{
  "name": "{cv['name']}",
  "score": <integer 0-100>,
  "summary": "<2-3 sentence overall assessment>",
  "strengths": ["strength1", "strength2", "strength3"],
  "weaknesses": ["weakness1", "weakness2"],
  "recommendation": "<Highly Recommended / Recommended / Maybe / Not Recommended>"
}}"""
        try:
            resp = llm.invoke(prompt)
            raw  = resp.content.strip().replace("```json", "").replace("```", "").strip()
            result = json.loads(raw)
            results.append(result)
        except Exception as e:
            results.append({
                "name":           cv["name"],
                "score":          0,
                "summary":        f"Evaluation error: {e}",
                "strengths":      [],
                "weaknesses":     [],
                "recommendation": "Not Recommended"
            })

    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results


def select_top_candidates_and_email_drafts(
    job_description: str,
    cvs: list,
    top_n: int = 5,
    sender_name: str = "HR Team",
    company: str = "Our Company",
) -> str:
    """
    Rank candidates against the JD, take the top N, and generate outreach email drafts.
    """
    if not job_description.strip():
        return "Job description is required."
    if not cvs:
        return "No candidates: upload CVs or load profiles from the database."
    top_n = max(1, min(int(top_n or 5), 20))
    ranked = screen_candidates(job_description, cvs)
    top = ranked[:top_n]
    llm = _get_llm(0.25)
    blocks = []
    for i, c in enumerate(top, 1):
        name = c.get("name", "Candidate")
        score = c.get("score", 0)
        summary = c.get("summary", "")
        prompt = f"""You are {sender_name} at {company}.

Write one professional recruitment email to **{name}** about the role described below.
First line must be exactly: Subject: <concise subject>

Then a blank line, then the email body (max 200 words).
Use "Dear {name}" if no surname split is obvious.
Mention 1–2 JD fit points based on this screening summary: {summary[:600]}
Job description (excerpt):
{job_description[:2000]}

Tone: warm, professional. No emojis. End with a clear call to reply or schedule a short call."""
        try:
            body = llm.invoke(prompt).content.strip()
        except Exception as e:
            body = f"(Draft failed: {e})"
        blocks.append(f"### {i}. {name} (match score {score}/100)\n\n{body}")
    header = (
        f"**Shortlist:** top **{len(top)}** of **{len(cvs)}** applicants for this JD.\n\n"
        "---\n\n"
    )
    return header + "\n\n---\n\n".join(blocks)


def generate_interview_questions(job_description: str, candidate_name: str, cv_content: str) -> str:
    """Generate tailored interview questions for a candidate."""
    llm = _get_llm()
    prompt = f"""You are a senior HR interviewer.

Job Description:
{job_description}

Candidate: {candidate_name}
CV Summary: {cv_content[:1000]}

Generate 8 tailored interview questions. Mix of: technical, behavioral, situational, role-specific.
For each question, include a brief note on what it assesses.
Format as numbered list."""
    return llm.invoke(prompt).content


def generate_onboarding_checklist(job_title: str, department: str) -> str:
    """Generate a detailed onboarding checklist."""
    llm = _get_llm()
    prompt = f"""You are an HR specialist.
Create a detailed onboarding checklist for a new {job_title} in the {department} department.

Include:
- Day 1 tasks
- Week 1 tasks
- Month 1 milestones
- Required documents
- System access to setup
- Key people to meet

Format as a clear checklist using [ ] for each item."""
    return llm.invoke(prompt).content


def answer_hr_query(question: str, user_name: str = "Employee", policy_context: str = "") -> str:
    """Answer HR-related questions, optionally with policy context."""
    llm = _get_llm()

    context_section = ""
    if policy_context:
        context_section = f"\nRelevant HR Policy:\n{policy_context[:2000]}\n"

    prompt = f"""You are a professional HR assistant.

Employee "{user_name}" asks: "{question}"
{context_section}
Provide a clear, professional, and helpful answer.
If policy context is available, answer based on it.
Keep answer concise and practical."""

    return llm.invoke(prompt).content


def analyze_cv_batch(cvs: list) -> str:
    """Analyze a batch of CVs and provide an overview."""
    llm = _get_llm()

    cv_summaries = []
    for cv in cvs[:10]:
        cv_summaries.append(f"**{cv['name']}**: {cv['content'][:400]}...")
    all_cvs = "\n\n".join(cv_summaries)

    prompt = f"""You are an HR analyst reviewing {len(cvs)} CVs.

CVs:
{all_cvs}

Provide:
1. **Talent Pool Quality** (1-2 sentences)
2. **Common Strengths** across candidates (3-4 points)
3. **Common Gaps** (3-4 points)
4. **Diversity Analysis** (experience levels, backgrounds)
5. **Top 3 Candidates** (names and why)

Be concise and actionable."""

    return llm.invoke(prompt).content


def draft_job_description(role: str, department: str, requirements: str = "") -> str:
    """Draft a professional job description."""
    llm = _get_llm(temp=0.4)
    prompt = f"""You are an HR specialist. Write a professional job description for:

Role: {role}
Department: {department}
Key Requirements: {requirements or 'standard for this role'}

Include:
- Role overview (2-3 sentences)
- Key responsibilities (6-8 bullet points)
- Required qualifications
- Preferred qualifications
- What we offer

Professional tone, clear and attractive."""
    return llm.invoke(prompt).content
