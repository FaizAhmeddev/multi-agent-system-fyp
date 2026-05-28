"""
ORCHESTRATOR/ORCHESTRATOR_BRAIN.PY
====================================
Central Orchestrator — Multi-Agent System Brain

Single entry for the user: call `orchestrator.route(...)` or `dispatch_user_prompt(...)`.
The orchestrator detects intent, dispatches tasks to specialist agents in parallel,
collects their outputs, and merges a final answer. Sub-agents: IT, Email, HR,
Recruitment (multi-step pipeline), Finance, Documents.

Architecture:
┌──────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                           │
│                                                               │
│   User Request → [Intent Detection] → [Agent Router]         │
│                                          │                    │
│          ┌───────────────────────────────┤                    │
│          ▼       ▼        ▼       ▼      ▼                    │
│       IT Agent  Email  HR Agent  Finance  Documents           │
│          │       │        │       │         │                 │
│          └───────┴────────┴───────┴─────────┘                 │
│                       Message Queue (A2A)                     │
│                       MCP Server                              │
└──────────────────────────────────────────────────────────────┘

A2A Protocol:
  - Orchestrator publishes tasks to Message Queue
  - Sub-agents subscribe and process their tasks
  - Sub-agents can collaborate by publishing to each other
  - All messages are tracked in history
"""

import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI

from config import OPENAI_API_KEY, AGENT_IDS
from message_queue.queue import message_queue


os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# ── LLM for intent detection ──────────────────────────────────────────────────

def _get_llm():
    return ChatOpenAI(model="gpt-4o-mini", temperature=0)


def _history_context_block(
    conversation_history: Optional[List[Dict[str, str]]],
    max_turns: int = 6,
) -> str:
    """Prefix prior turns so specialist agents and intent LLM see thread context."""
    lines: list[str] = []
    for h in (conversation_history or [])[-(max_turns * 2) :]:
        content = (h.get("content") or "").strip()[:2000]
        if not content:
            continue
        role = (h.get("role") or "").strip()
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")
    if not lines:
        return ""
    return "Previous conversation:\n" + "\n".join(lines) + "\n\nCurrent request:\n"


def run_general_assistant(
    user_message: str,
    user_name: str = "User",
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Conversational layer: greetings, date/time (server clock), follow-ups, light Q&A.
    Uses thread history so the next turn can refer to the previous reply (real multi-turn).
    """
    from datetime import datetime

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    now = datetime.now().strftime("%A, %B %d, %Y — %I:%M %p (local time on this machine)")
    system = (
        f"You are a helpful office assistant speaking with **{user_name}** inside an enterprise "
        "multi-agent automation platform (IT, Email, HR, Finance, Documents).\n"
        f"When the user asks what day it is, the date, or the time, answer using this exact real-world clock: **{now}**.\n"
        "Continue the conversation naturally: refer back to earlier turns when they say \"that\", \"it\", "
        "\"continue\", or ask a follow-up.\n"
        "If they need operational work (send Gmail from the system, screen CVs, IT tickets, Drive search), "
        "say clearly that those are handled by specialist agents in this same chat — keep your reply short "
        "and do not pretend you already executed those integrations yourself.\n"
        "Be concise unless they ask for detail."
    )
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.35)
    msgs = [SystemMessage(content=system)]
    for h in (conversation_history or [])[-10:]:
        role = (h.get("role") or "").strip()
        text = (h.get("content") or "").strip()[:4000]
        if not text:
            continue
        if role == "user":
            msgs.append(HumanMessage(content=text))
        elif role == "assistant":
            msgs.append(AIMessage(content=text))
    msgs.append(HumanMessage(content=(user_message or "").strip()[:8000]))
    try:
        out = llm.invoke(msgs)
        return (out.content or "").strip() or "I'm here if you need anything else."
    except Exception as e:
        return f"I couldn't reach the language model ({e}). Current local time: {now}."


# ── Intent detection ──────────────────────────────────────────────────────────

EMAIL_KEYWORDS = [
    "email", "mail", "send", "reply", "inbox", "message", "gmail",
    "smtp", "imap", "subject", "recipient", "forward", "compose",
    "write to", "contact", "notify"
]

IT_KEYWORDS = [
    "computer", "laptop", "wifi", "internet", "password", "login",
    "software", "install", "error", "crash", "slow", "printer",
    "network", "screen", "keyboard", "virus", "update", "windows",
    "restart", "freeze", "not working", "broken", "connection",
    "vpn", "access", "reset", "boot", "driver", "it support", "technical",
    "device", "hardware", "monitor", "cable", "usb", "mouse",
    "blue screen", "bsod", "cannot connect", "won't turn on",
]

HR_KEYWORDS = [
    "hr", "hire", "recruit", "cv", "resume", "candidate", "interview",
    "onboard", "onboarding", "employee", "salary", "leave", "policy",
    "payroll", "job description", "staff", "screening", "shortlist",
    "performance", "appraisal", "human resources", "vacancy", "position"
]

RECRUITMENT_KEYWORDS = [
    "orchestration", "multi-agent recruitment", "shortlist and email",
    "interview invitation", "uploaded 10", "uploaded ten", "parallel agents",
    "candidate matching", "jd match", "rank candidates", "workflow",
]

FINANCE_KEYWORDS = [
    "finance", "financial", "expense", "budget", "invoice", "payment",
    "revenue", "cost", "profit", "loss", "tax", "account", "balance",
    "ledger", "cash flow", "report", "spending", "pkr", "usd", "money",
    "salary", "payable", "receivable", "quarterly", "fiscal", "audit",
    "generate pdf", "generate excel", "generate xlsx", "export pdf", "export excel",
]

DOCS_KEYWORDS = [
    "document", "file", "pdf", "drive", "google drive", "folder",
    "search document", "find file", "summarize", "contract", "policy",
    "manual", "report", "doc", "read file", "extract", "compare doc"
]


def _keyword_score(msg: str, keywords: list, weight: int = 1) -> int:
    """Score how strongly a message matches a keyword set (phrase-aware)."""
    score = 0
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        if " " in k:
            if k in msg:
                score += weight * 2
        elif re.search(rf"\b{re.escape(k)}\b", msg):
            score += weight
    return score


def _pre_route_intent(user_message: str) -> list | None:
    """Fast, deterministic routing for common phrasing before LLM/keywords."""
    from tools.hr_gmail_shortlist import parse_gmail_shortlist_prompt

    if parse_gmail_shortlist_prompt(user_message):
        return ["hr_gmail"]

    msg = (user_message or "").lower().strip()
    if not msg:
        return ["general"]

    approve_send = re.search(
        r"\b(approve\s+(and\s+)?send|send\s+(the\s+)?(interview\s+)?emails?|confirm\s+send)\b",
        msg,
    )
    if approve_send and ("gmail" in msg or "shortlist" in msg or "batch" in msg or "interview" in msg):
        return ["hr_gmail"]

    if re.search(r"\b(what\s+day|what\s+date|what\s+time|today'?s\s+date|current\s+time)\b", msg):
        return ["general"]
    if re.search(r"^(hi|hello|hey|thanks|thank you|good\s+(morning|afternoon|evening))\b", msg):
        return ["general"]

    fin_doc = re.search(
        r"\b(generate|export|create|download)\b.*\b(pdf|xlsx|excel|csv|word|docx|report)\b",
        msg,
    ) or re.search(r"\b(pdf|xlsx|excel)\b.*\b(expense|invoice|budget|finance|financial)\b", msg)
    if fin_doc:
        return ["finance"]

    if re.search(r"\b(google\s+drive|drive\s+folder|search\s+(the\s+)?document)\b", msg):
        return ["documents"]

    return None


def detect_intent(user_message: str) -> list:
    """
    Detect which agents should handle the message (keyword scoring).
    Returns list of agent types.
    """
    early = _pre_route_intent(user_message)
    if early is not None:
        return early

    msg = user_message.lower()

    scores = {
        "email": _keyword_score(msg, EMAIL_KEYWORDS),
        "it_support": _keyword_score(msg, IT_KEYWORDS),
        "hr": _keyword_score(msg, HR_KEYWORDS),
        "recruitment": _keyword_score(msg, RECRUITMENT_KEYWORDS, weight=2),
        "finance": _keyword_score(msg, FINANCE_KEYWORDS),
        "documents": _keyword_score(msg, DOCS_KEYWORDS),
    }

    # Disambiguate shared terms
    if "salary" in msg or "payroll" in msg:
        if scores["finance"] >= scores["hr"]:
            scores["hr"] = max(0, scores["hr"] - 1)
        else:
            scores["finance"] = max(0, scores["finance"] - 1)

    if "resume" in msg or "cv" in msg:
        if any(w in msg for w in ("upload", "attached", "shortlist", "rank", "screen")):
            scores["recruitment"] += 3
            scores["email"] = max(0, scores["email"] - 1)

    threshold = 1
    matches = [agent for agent, sc in scores.items() if sc >= threshold]
    matches.sort(key=lambda a: scores[a], reverse=True)

    if not matches:
        return ["general"]

    return normalize_agent_list(matches)


# Canonical agent keys used by AGENT_IDS, graphs, and logging
_CANONICAL = ("general", "hr_gmail", "it_support", "email", "hr", "recruitment", "finance", "documents")

_AGENT_ALIASES = {
    "general": "general",
    "conversation": "general",
    "chitchat": "general",
    "small_talk": "general",
    "assistant_general": "general",
    "hr_gmail": "hr_gmail",
    "gmail_cv_shortlist": "hr_gmail",
    "inbox_cv_fetch": "hr_gmail",
    "it_support": "it_support",
    "it": "it_support",
    "it_support_agent": "it_support",
    "support": "it_support",
    "tech": "it_support",
    "email": "email",
    "mail": "email",
    "gmail": "email",
    "hr": "hr",
    "human_resources": "hr",
    "hiring": "hr",
    "recruitment": "recruitment",
    "recruiting": "recruitment",
    "talent_acquisition": "recruitment",
    "recruitment_pipeline": "recruitment",
    "finance": "finance",
    "financial": "finance",
    "accounting": "finance",
    "documents": "documents",
    "document": "documents",
    "docs": "documents",
    "drive": "documents",
    "google_drive": "documents",
}


def normalize_agent_slug(raw: str) -> Optional[str]:
    """Map LLM / user output to a canonical agent type."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip().lower().replace("-", "_").replace(" ", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    if s in _CANONICAL:
        return s
    return _AGENT_ALIASES.get(s)


def normalize_agent_list(agents: list) -> list:
    seen = set()
    out = []
    for a in agents or []:
        c = normalize_agent_slug(str(a))
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out if out else ["general"]


def _cv_attachment_count(attachments: Optional[List[Dict[str, Any]]]) -> int:
    """Count non–job-description file attachments with extractable text (treated as CVs)."""
    if not attachments:
        return 0
    n = 0
    for a in attachments:
        name = (a.get("name") or a.get("filename") or "").lower()
        if any(k in name for k in ("jd", "job_desc", "job-description", "requisition", "specification")):
            continue
        if (a.get("content") or "").strip():
            n += 1
    return n


def coerce_agents_for_cv_hiring(
    user_message: str,
    attachments: Optional[List[Dict[str, Any]]],
    agents: List[str],
) -> List[str]:
    """
    If the user attached resume/CV files and the text is about hiring or interviews,
    run **recruitment only** so the Email auto-reply agent does not answer in parallel.
    """
    if _cv_attachment_count(attachments) < 1:
        return agents
    msg = (user_message or "").lower()
    hiring = any(
        w in msg
        for w in (
            "candidate", "cv", "resume", "shortlist", "hire", "interview",
            "recruit", "data entry", "job", "role", "position", "jd",
            "select", "best ", "email them", "mail them", "invite", "invitation",
        )
    )
    if not hiring:
        return agents
    return ["recruitment"]


def recruitment_user_requests_email_send(message: str) -> bool:
    """True when the user explicitly wants messages delivered (not drafts-only)."""
    m = (message or "").lower()
    if any(
        x in m
        for x in (
            "don't send",
            "do not send",
            "draft only",
            "no email",
            "without sending",
            "do not email",
            "don't email",
        )
    ):
        return False
    if any(
        h in m
        for h in (
            "email them",
            "email him",
            "email her",
            "send email",
            "send the email",
            "send an email",
            "send interview",
            "email invitation",
            "email invite",
            "notify them",
            "invite them",
            "mail them",
        )
    ):
        return True
    if ("email" in m or "send" in m) and ("interview" in m or "invite" in m or "invitation" in m):
        return True
    return False


def recruitment_user_wants_top_one_only(message: str) -> bool:
    """Prefer emailing a single top-scoring candidate (e.g. 'best candidate')."""
    m = (message or "").lower()
    return any(
        k in m
        for k in (
            "best candidate",
            "top candidate",
            "one candidate",
            "single candidate",
            "select one",
            "pick one",
            "top one",
            "best one",
            "the best ",
            "a best ",
            "highest match",
            "top match",
        )
    )


def build_context_with_attachments(user_message: str, attachments: Optional[List[Dict[str, Any]]]) -> str:
    """Append extracted attachment text so every routed agent sees the same context."""
    if not attachments:
        return user_message
    parts = [user_message.rstrip(), "", "### Attached files (shared context)", ""]
    for att in attachments:
        name = att.get("name") or att.get("filename") or "file"
        text = (att.get("content") or "").strip()
        if not text:
            continue
        cap = 12000
        if len(text) > cap:
            text = text[:cap] + "\n...[truncated]"
        parts.append(f"#### {name}\n{text}\n")
    return "\n".join(parts).strip()


def detect_intent_llm(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> list:
    """
    LLM-powered intent detection for complex/ambiguous messages.
    Falls back gracefully.
    """
    early = _pre_route_intent(user_message)
    if early is not None:
        return early

    try:
        llm = _get_llm()
        hist = _history_context_block(conversation_history, max_turns=8)
        context_block = (
            f"\nRecent conversation:\n{hist}\n" if hist else "\n(No prior turns in this thread.)\n"
        )
        prompt = f"""You are an intent detector for an office automation system.
Use the conversation thread to resolve follow-ups ("that", "them", "approve", "send it", "the shortlist").
{context_block}
User message: "{user_message}"

Available agents (return canonical slugs only):
- general: greetings, thanks, date/time, small talk, clarifying questions, follow-ups that do NOT require running Gmail/IT/HR/Finance/Drive tools
- hr_gmail: fetch Gmail inbox CVs, rank candidates for a role, draft interview emails (approval before SMTP send). Follow-up "approve and send" after a shortlist → hr_gmail
- it_support: computer, laptop, wifi, printer, software install, errors, VPN, passwords (IT hardware/software)
- email: compose/send/reply to a specific person, read inbox (NOT bulk CV shortlist from Gmail — use hr_gmail for that)
- hr: HR policies, leave, onboarding, employee questions, simple CV Q&A without Gmail fetch
- recruitment: user attached CV/resume files AND wants screen/rank/shortlist/interview email workflow
- finance: expenses, invoices, budgets, revenue, tax, payroll reports, export PDF/Excel/CSV financial documents
- documents: Google Drive search, summarize files, contracts, manuals

Rules:
1. Pick the MINIMUM agents needed (usually one). Use multiple only when the user clearly asks for two domains in one message.
2. Bulk Gmail CV fetch + shortlist → hr_gmail only (not email+hr).
3. CV attachments + hiring language → recruitment only.
4. "Salary" in a budget/expense/invoice context → finance; in hiring/employee context → hr.
5. Follow-up approval to send interview emails after hr_gmail shortlist → hr_gmail.

Respond with ONLY a JSON array of agent slugs.
Examples:
  "what day is it today?" → ["general"]
  "fetch last 40 emails with CVs and select 5 Python developers" → ["hr_gmail"]
  "approve and send" (after shortlist in thread) → ["hr_gmail"]
  "my laptop is very slow" → ["it_support"]
  "draft a reply to the client email" → ["email"]
  "what is our leave policy?" → ["hr"]
  "rank these CVs and email top candidate" (with attachments) → ["recruitment"]
  "generate quarterly expense PDF and Excel" → ["finance"]
  "find the contract PDF on Google Drive" → ["documents"]
  "thanks, that helped" → ["general"]

JSON array only:"""

        resp = llm.invoke(prompt)
        text = resp.content.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)
        text = text.strip()
        import json

        agents = json.loads(text)
        if isinstance(agents, list) and agents:
            return normalize_agent_list(agents)
    except Exception:
        pass

    return detect_intent(user_message)  # fallback to keyword


# ── Orchestrator Core ─────────────────────────────────────────────────────────

class Orchestrator:
    """
    Central orchestrator that:
    1. Receives user requests
    2. Detects intent (which agents needed)
    3. Publishes tasks to Message Queue (A2A)
    4. Collects responses from agents
    5. Merges and returns final answer
    """

    def __init__(self):
        self.agent_id   = AGENT_IDS["orchestrator"]
        self.mq         = message_queue
        self._lock      = threading.Lock()
        self._responses = {}  # task_id -> response
        self._finance_export_files: Optional[List[Dict[str, Any]]] = None

    def _try_hr_gmail_approve_send_via_chat(
        self,
        *,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]],
        allowed_agents: Optional[List[str]],
        start_time: float,
    ) -> Optional[dict]:
        """
        Explicit opt-in: user says e.g. **approve and send** after a shortlist in this thread.
        Same RBAC as ``hr_gmail``; resolves batch id from the message or recent assistant replies.
        """
        from tools.hr_gmail_shortlist import (
            approve_and_send_shortlist_batch,
            format_hr_gmail_approve_send_reply,
            resolve_hr_gmail_batch_id_for_send,
            user_requests_hr_gmail_approve_send,
        )

        raw = (user_message or "").strip()
        if not user_requests_hr_gmail_approve_send(raw):
            return None

        def _done(final_answer: str, *, ok: bool, batch_id: Optional[str], agents_used: List[str]) -> dict:
            elapsed = round((time.time() - start_time) * 1000)
            resp_map = {agents_used[0]: final_answer} if agents_used else {}
            return {
                "agents_used": agents_used,
                "responses": resp_map,
                "final_answer": final_answer,
                "task_ids": {},
                "elapsed_ms": elapsed,
                "mq_messages": self.mq.get_all_messages_for_display(limit=30),
                "hr_gmail_batch_id": None if ok else batch_id,
                "hr_gmail_pending_cleared": False,
                "finance_export_files": None,
            }

        allow = set(normalize_agent_list(allowed_agents)) if allowed_agents else None
        if allow is not None and "hr_gmail" not in allow:
            return _done(
                "**Gmail shortlist send blocked**\n\n"
                "Your role is not permitted to run **Gmail CV shortlist** (including **approve and send** in chat). "
                "Use an **HR Manager**, **Office Assistant**, or **Administrator** account.",
                ok=False,
                batch_id=None,
                agents_used=[],
            )

        bid = resolve_hr_gmail_batch_id_for_send(raw, conversation_history)
        if not bid:
            return _done(
                "**Gmail CV shortlist — could not send**\n\n"
                "Say e.g. **approve and send** after the shortlist appears in this thread (the batch id is read from "
                "the last **Gmail CV shortlist** reply), or paste the **Batch ID** UUID in the same message.\n\n"
                "Example: `approve and send` or `approve and send batch a32969b1-4f27-44c3-b34f-d12934213ffb`",
                ok=False,
                batch_id=None,
                agents_used=["hr_gmail"],
            )

        sr = approve_and_send_shortlist_batch(bid, user_message=raw)
        if sr.get("needs_clarification"):
            body = f"**HR Recruitment Assistant**\n\n{sr.get('error', 'Specify recipients.')}"
            return _done(body, ok=False, batch_id=bid, agents_used=["hr_gmail"])
        body = format_hr_gmail_approve_send_reply(sr)
        out = _done(body, ok=bool(sr.get("ok")), batch_id=bid, agents_used=["hr_gmail"])
        if sr.get("ok"):
            out["hr_gmail_pending_cleared"] = True
        return out

    def _try_hr_recruitment_follow_up(
        self,
        *,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]],
        allowed_agents: Optional[List[str]],
        start_time: float,
        user_name: str = "User",
        user_role: str = "",
    ) -> Optional[dict]:
        from tools.hr_gmail_shortlist import handle_hr_recruitment_follow_up, user_requests_hr_recruitment_follow_up

        if not user_requests_hr_recruitment_follow_up(user_message):
            return None

        allow = set(normalize_agent_list(allowed_agents)) if allowed_agents else None
        if allow is not None and "hr_gmail" not in allow:
            elapsed = round((time.time() - start_time) * 1000)
            return {
                "agents_used": [],
                "responses": {},
                "final_answer": "**HR recruitment follow-up blocked** — your role cannot use Gmail CV shortlist.",
                "task_ids": {},
                "elapsed_ms": elapsed,
                "mq_messages": self.mq.get_all_messages_for_display(limit=30),
                "hr_gmail_batch_id": None,
                "finance_export_files": None,
            }

        res = handle_hr_recruitment_follow_up(
            user_message=user_message,
            conversation_history=conversation_history,
            user_name=user_name,
            user_role=user_role,
        )
        if not res:
            return None

        elapsed = round((time.time() - start_time) * 1000)
        agents = res.get("agents_used") or ["hr_gmail"]
        ans = res.get("final_answer") or ""
        out = {
            "agents_used": agents,
            "responses": {agents[0]: ans} if agents else {},
            "final_answer": ans,
            "task_ids": {},
            "elapsed_ms": elapsed,
            "mq_messages": self.mq.get_all_messages_for_display(limit=30),
            "hr_gmail_batch_id": res.get("hr_gmail_batch_id"),
            "finance_export_files": None,
        }
        if res.get("hr_gmail_pending_cleared"):
            out["hr_gmail_pending_cleared"] = True
        return out

    def route(self, user_message: str, user_name: str = "User",
              use_llm_intent: bool = True,
              attachments: Optional[List[Dict[str, Any]]] = None,
              allowed_agents: Optional[List[str]] = None,
              conversation_history: Optional[List[Dict[str, str]]] = None,
              user_role: str = "") -> dict:
        """
        Main entry point.
        Returns:
          {
            "agents_used":  ["it_support", ...],
            "responses":    {"it_support": "...", ...},
            "final_answer": "merged response",
            "task_ids":     {"it_support": "msg-id", ...},
            "mq_messages":  [list of all queue messages],
          }
        """
        start_time = time.time()
        self._finance_export_files = None

        full_message = build_context_with_attachments(user_message, attachments)

        from tools.hr_email_intelligence import try_hr_email_assistant_command
        from tools.hr_gmail_shortlist import parse_gmail_shortlist_prompt

        allow = set(normalize_agent_list(allowed_agents)) if allowed_agents else None
        hr_email_ok = allow is None or "hr_gmail" in allow or "hr" in allow or "recruitment" in allow
        if hr_email_ok:
            hr_early = try_hr_email_assistant_command(
                user_message=user_message,
                conversation_history=conversation_history,
                user_name=user_name,
                user_role=user_role,
                start_time=start_time,
            )
            if hr_early is not None:
                return hr_early

        gspec_early = parse_gmail_shortlist_prompt(user_message)

        if gspec_early is None:
            early_follow = self._try_hr_recruitment_follow_up(
                user_message=user_message,
                conversation_history=conversation_history,
                allowed_agents=allowed_agents,
                start_time=start_time,
                user_name=user_name,
                user_role=user_role,
            )
            if early_follow is not None:
                return early_follow

            early_send = self._try_hr_gmail_approve_send_via_chat(
                user_message=user_message,
                conversation_history=conversation_history,
                allowed_agents=allowed_agents,
                start_time=start_time,
            )
            if early_send is not None:
                return early_send
        if gspec_early:
            agents = ["hr_gmail"]
        elif use_llm_intent:
            agents = detect_intent_llm(user_message, conversation_history)
        else:
            agents = normalize_agent_list(detect_intent(user_message))

        if not gspec_early:
            agents = coerce_agents_for_cv_hiring(user_message, attachments, agents)

        if allowed_agents:
            allow = set(normalize_agent_list(allowed_agents))
            allow.add("general")
            blocked = [a for a in agents if a not in allow]
            agents = [a for a in agents if a in allow]
            if not agents:
                if "general" in allow:
                    agents = ["general"]
                else:
                    elapsed = round((time.time() - start_time) * 1000)
                    allowed_txt = ", ".join(sorted(allow - {"general"})) or "none"
                    return {
                        "agents_used": [],
                        "responses": {},
                        "final_answer": (
                            "**Outside your department scope**\n\n"
                            f"This request matched: **{', '.join(blocked) or 'restricted agents'}**, but your role may use: "
                            f"**{allowed_txt}** (plus general chat).\n\n"
                            "Try rephrasing for your department tab, or ask an **Administrator** for broader access."
                        ),
                        "task_ids": {},
                        "elapsed_ms": elapsed,
                        "mq_messages": self.mq.get_all_messages_for_display(limit=30),
                        "hr_gmail_batch_id": None,
                        "finance_export_files": None,
                    }

        result = {
            "agents_used":  agents,
            "responses":    {},
            "final_answer": "",
            "task_ids":     {},
            "elapsed_ms":   0,
            "mq_messages":  [],
            "hr_gmail_batch_id": None,
            "finance_export_files": None,
        }

        # 2. Optional A2A message queue (off by default — faster orchestration)
        from config import orchestrator_mq_enabled

        task_ids = {}
        if orchestrator_mq_enabled():
            for agent_type in agents:
                agent_receiver = AGENT_IDS.get(agent_type, f"agent-{agent_type}-001")
                msg_id = self.mq.send(
                    sender=self.agent_id,
                    receiver=agent_receiver,
                    topic="task",
                    payload={
                        "user_message": full_message,
                        "user_name":    user_name,
                        "agent_type":   agent_type,
                        "has_attachments": bool(attachments),
                    },
                    priority=2,
                )
                task_ids[agent_type] = msg_id

        result["task_ids"] = task_ids

        # 3. Execute agents in parallel (same context for each)
        responses: Dict[str, str] = {}

        def _run_one(agent_type: str) -> tuple:
            try:
                resp = self._invoke_agent(
                    agent_type, full_message, user_name,
                    user_message_raw=user_message,
                    attachments=attachments,
                    conversation_history=conversation_history,
                    user_role=user_role,
                )
                return agent_type, resp, None
            except Exception as e:
                return agent_type, f"Agent error: {e}", e

        max_workers = max(1, min(len(agents), 8))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_run_one, at): at for at in agents}
            for fut in as_completed(futures):
                agent_type, resp, err = fut.result()
                responses[agent_type] = resp
                if orchestrator_mq_enabled():
                    self.mq.send(
                        sender=AGENT_IDS.get(agent_type, agent_type),
                        receiver=self.agent_id,
                        topic="result",
                        payload={"response": resp, "agent_type": agent_type, "error": str(err) if err else None},
                        reply_to=task_ids.get(agent_type),
                    )

        result["responses"] = responses

        from tools.hr_gmail_shortlist import extract_hr_gmail_batch_id, strip_hr_gmail_batch_marker

        bid = None
        for _at, txt in responses.items():
            b = extract_hr_gmail_batch_id(txt or "")
            if b:
                bid = b
                break
        if bid:
            result["hr_gmail_batch_id"] = bid
        for k in list(responses.keys()):
            responses[k] = strip_hr_gmail_batch_marker(responses[k] or "")

        from tools.assistant_display import build_display_text, build_hr_shortlist_ui_payload
        from database.sqlite_db import hr_shortlist_get_batch

        ui_payload = result.get("ui_payload")
        if bid and not ui_payload:
            try:
                row = hr_shortlist_get_batch(bid)
                if row:
                    pl = row.get("payload") or {}
                    ui_payload = build_hr_shortlist_ui_payload(
                        {
                            "ok": True,
                            "batch_id": bid,
                            "drafts": pl.get("top") or [],
                            "role_title": (row.get("criteria") or "")[:120],
                            "emails_scanned": pl.get("emails_scanned", 0),
                            "attachments_parsed": pl.get("attachments_parsed", 0),
                            "filters_applied": (pl.get("session_memory") or {}).get("filters_applied") or {},
                        }
                    )
            except Exception:
                pass
        if ui_payload:
            result["ui_payload"] = ui_payload
        result["display_answer"] = build_display_text(result.get("final_answer", ""), ui_payload)

        # 4. Merge responses (stable order matching original agent list)
        ordered = [(at, responses[at]) for at in agents if at in responses]
        if len(ordered) == 1:
            result["final_answer"] = ordered[0][1]
        else:
            parts = []
            agent_labels = {
                "general":      "Assistant",
                "hr_gmail":     "Gmail CV shortlist",
                "it_support":   "IT Support",
                "email":        "Email",
                "hr":           "HR",
                "recruitment":  "Recruitment Orchestrator",
                "finance":      "Finance",
                "documents":    "Documents",
            }
            for agent_type, resp in ordered:
                label = agent_labels.get(agent_type, agent_type.upper())
                parts.append(f"**{label}:**\n{resp}")
            result["final_answer"] = "\n\n---\n\n".join(parts)

        result["elapsed_ms"]  = round((time.time() - start_time) * 1000)
        result["mq_messages"] = (
            self.mq.get_all_messages_for_display(limit=30)
            if orchestrator_mq_enabled()
            else []
        )
        result["finance_export_files"] = self._finance_export_files

        return result

    def _invoke_agent(
        self,
        agent_type: str,
        user_message: str,
        user_name: str,
        user_message_raw: str = "",
        attachments: Optional[List[Dict[str, Any]]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        user_role: str = "",
    ) -> str:
        """
        Invoke the correct LangGraph agent or recruitment pipeline.
        This is the A2A execution layer.
        """
        raw = (user_message_raw or user_message or "").strip()
        hist_prefix = _history_context_block(conversation_history)
        contextual = (hist_prefix + user_message) if hist_prefix else user_message

        if agent_type == "general":
            return run_general_assistant(raw, user_name, conversation_history)

        if agent_type == "hr_gmail":
            from tools.hr_gmail_shortlist import run_gmail_shortlist_from_user_prompt, format_hr_gmail_orchestrator_reply

            res = run_gmail_shortlist_from_user_prompt(
                user_message=raw,
                user_name=user_name,
                user_role=user_role or "User",
            )
            return format_hr_gmail_orchestrator_reply(res)

        if agent_type == "it_support":
            from graph.it_graph import it_graph
            state  = {"user_name": user_name, "it_problem": contextual}
            result = it_graph.invoke(state)
            return result.get("it_solution", "No solution returned.")

        elif agent_type == "email":
            from agents.auto_reply_agent import generate_reply
            state  = {"email_content": contextual, "sender_name": user_name, "sender_email": ""}
            result = generate_reply(state)
            return result.get("body", "No reply generated.")

        elif agent_type == "hr":
            from graph.hr_graph import hr_graph
            state  = {"action": "hr_query", "query": contextual, "user_name": user_name}
            result = hr_graph.invoke(state)
            return result.get("output", "No HR response.")

        elif agent_type == "recruitment":
            return self._run_recruitment_orchestration(raw, user_message, user_name, attachments)

        elif agent_type == "finance":
            from graph.finance_graph import finance_graph
            from tools.finance_document_export import detect_finance_export_intent

            attach_blob = ""
            if attachments:
                attach_blob = "\n\n".join(
                    f"### {a.get('name', 'file')}\n{(a.get('content') or '')[:12000]}"
                    for a in attachments
                )
            combined = f"{raw}\n{attach_blob}".strip()
            if detect_finance_export_intent(combined):
                fin_state: dict[str, Any] = {
                    "action": "export_documents",
                    "question": raw,
                    "context": attach_blob,
                    "data": attach_blob,
                    "user_name": user_name,
                }
                fin_result = finance_graph.invoke(fin_state)
                files = fin_result.get("export_files") or []
                if files:
                    self._finance_export_files = files
                out = fin_result.get("output") or ""
                if files:
                    out += (
                        "\n\n**Downloads:** use the **Finance document downloads** section below this chat "
                        "(same browser session)."
                    )
                return out
            state = {"action": "query", "question": contextual, "context": attach_blob, "user_name": user_name}
            fin_result = finance_graph.invoke(state)
            return fin_result.get("output", "No finance response.")

        elif agent_type == "documents":
            from graph.documents_graph import documents_graph
            state  = {"action": "qa", "query": contextual, "user_name": user_name, "documents": []}
            result = documents_graph.invoke(state)
            return result.get("output", "No documents response.")

        else:
            return f"Unknown agent type: {agent_type}"

    def _run_recruitment_orchestration(
        self,
        raw_msg: str,
        full_ctx: str,
        user_name: str,
        attachments: Optional[List[Dict[str, Any]]],
    ) -> str:
        """
        Multi-agent recruitment: parse → JD → match → shortlist → draft.
        If the user explicitly asks to **send** / **email** interview invitations,
        sends via Gmail (top sendable draft, or all sendable, from the shortlist).
        """
        import re

        from recruitment.pipeline import run_recruitment_pipeline, send_recruitment_email_drafts
        from database.sqlite_db import recruitment_get_workflow, recruitment_save_workflow, recruitment_log_audit

        cvs: List[Dict[str, Any]] = []
        jd_chunks: List[str] = [(raw_msg or "").strip()]
        for a in attachments or []:
            text = (a.get("content") or "").strip()
            if not text:
                continue
            name_l = (a.get("name") or "").lower()
            if any(k in name_l for k in ("jd", "job_desc", "job-description", "requisition", "specification")):
                jd_chunks.insert(0, text)
            else:
                cvs.append({
                    "name": a.get("name") or "Candidate",
                    "content": text,
                    "file_name": a.get("name") or "",
                })

        jd = "\n\n---\n\n".join(x for x in jd_chunks if x).strip()
        if not cvs:
            return (
                "**Recruitment** needs resume/CV file attachments. "
                "Put the job description in your message (or name a file with **JD** in the filename) "
                "and attach CVs as PDF/DOCX."
            )

        interview_hint = "As stated in your request — confirm after reply."
        m = re.search(
            r"(tomorrow|today|monday|tuesday|wednesday|thursday|friday|sat|sun)[^.\n]{0,100}("
            r"\d{1,2}:\d{2}\s*(a\.?m\.?|p\.?m\.?|am|pm)?|\d{1,2}\s*(a\.?m\.?|p\.?m\.?|am|pm))",
            raw_msg,
            re.I,
        )
        if m:
            interview_hint = m.group(0).strip()[:220]

        jd_len = len(jd or "")
        min_score = 45 if jd_len < 300 else 52

        res = run_recruitment_pipeline(
            job_description=jd or raw_msg,
            cvs=cvs,
            user_name=user_name,
            company="Our Company",
            role_title_hint="",
            interview_when=interview_hint,
            meeting_details="Confirm attendance by reply; calendar invite or link to follow.",
            top_n=5,
            min_match_score=min_score,
        )
        if not res.get("ok"):
            return f"**Recruitment Orchestrator:** {res.get('error', 'Run failed')}"

        drafts = res.get("email_drafts") or []
        wf_id = res.get("workflow_id") or ""
        auto_send = recruitment_user_requests_email_send(raw_msg)
        want_one = recruitment_user_wants_top_one_only(raw_msg)
        send_report = ""

        if auto_send and drafts:
            sendable_sorted = sorted(
                [d for d in drafts if d.get("sendable") and (d.get("recipient") or "").strip()],
                key=lambda x: -(x.get("match_score") or 0),
            )
            to_send = sendable_sorted[:1] if want_one else sendable_sorted[: min(10, len(sendable_sorted))]
            if not to_send:
                send_report = (
                    "\n\n### Email send\n**Not sent:** no draft had a **recipient email** parsed from the CV. "
                    "Put a clear `email: you@domain.com` line on each resume."
                )
            else:
                try:
                    send_r = send_recruitment_email_drafts(to_send)
                    sr = send_r.get("send_results") or {}
                    n = int(sr.get("emails_sent") or 0)
                    tot = int(sr.get("total") or 0)
                    if send_r.get("ok"):
                        send_report = f"\n\n### Email send (Gmail SMTP)\n**Delivered:** {n}/{tot} message(s)."
                        if send_r.get("partial"):
                            send_report += f"\n**Partial:** {send_r.get('error', '')}"
                    else:
                        send_report = f"\n\n### Email send\n**Failed:** {send_r.get('error', 'Unknown error')}"

                    wf_row = recruitment_get_workflow(wf_id) if wf_id else None
                    if wf_row and wf_id:
                        new_status = "completed"
                        if not send_r.get("ok"):
                            new_status = "pending_approval"
                        elif send_r.get("partial"):
                            new_status = "completed_with_errors"
                        recruitment_save_workflow(
                            workflow_id=wf_id,
                            user_name=wf_row.get("user_name") or user_name,
                            status=new_status,
                            role_title=wf_row.get("role_title") or res.get("role_title") or "",
                            company=wf_row.get("company") or "",
                            interview_when=wf_row.get("interview_when") or "",
                            state=wf_row.get("state") or {},
                            send_results=sr,
                            error_message=((send_r.get("error") or "")[:4000]) if not send_r.get("ok") else "",
                        )
                    if wf_id:
                        recruitment_log_audit(
                            wf_id,
                            "assistant_auto_send",
                            "EmailSendingAgent",
                            bool(send_r.get("ok")),
                            0,
                            {"recipients": [x.get("recipient") for x in to_send], "want_one": want_one},
                        )
                except Exception as ex:
                    send_report = f"\n\n### Email send\n**Error:** {ex}"
        elif auto_send and not drafts:
            send_report = (
                "\n\n### Email send\n**Not sent:** nobody reached the shortlist "
                f"(min score **{min_score}**). Try lowering expectations in the JD or attach clearer CVs."
            )

        header = "**Recruitment Orchestrator** (CV parse → JD → match → shortlist → drafts"
        if auto_send and "Delivered:" in send_report:
            header += " → **Gmail send**"
        header += ")"

        lines = [
            header,
            "",
            f"**Workflow ID:** `{wf_id}`",
            "",
            res.get("human_prompt", ""),
            "",
            "### Shortlist",
        ]
        for d in drafts:
            ok = "yes" if d.get("sendable") else "**missing email in CV**"
            lines.append(
                f"- **{d.get('candidate_name')}** — match **{d.get('match_score')}** — sendable: {ok}"
            )
        if drafts:
            preview = next((d for d in drafts if d.get("sendable")), drafts[0])
            lines += [
                "",
                "### First draft preview",
                "",
                f"**Subject:** {preview.get('subject', '')}",
                "",
                (preview.get("body") or "")[:2000],
            ]

        lines.append(send_report)

        if not auto_send:
            lines += [
                "",
                "To **send** interview emails from here, say e.g. **email them** or **send interview invitation** "
                "in the same request. Otherwise use **Assistant** to review candidates and approve send.",
            ]

        return "\n".join(lines)

    def get_queue_status(self) -> dict:
        return {
            "stats":    self.mq.get_stats(),
            "messages": self.mq.get_all_messages_for_display(limit=50),
        }

    def broadcast(self, message: str, sender_name: str = "Orchestrator"):
        """Broadcast a message to all agents."""
        self.mq.send(
            sender=self.agent_id,
            receiver="broadcast",
            topic="broadcast",
            payload={"message": message, "from": sender_name},
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

orchestrator = Orchestrator()


def dispatch_user_prompt(
    user_message: str,
    user_name: str = "User",
    *,
    use_llm_intent: bool = True,
    attachments: Optional[List[Dict[str, Any]]] = None,
    allowed_agents: Optional[List[str]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    user_role: str = "",
) -> dict:
    """
    Public entry point: one user prompt → orchestrator → sub-agents → merged result.
    Same as ``orchestrator.route``; use whichever reads clearer in your integration.
    """
    return orchestrator.route(
        user_message,
        user_name,
        use_llm_intent=use_llm_intent,
        attachments=attachments,
        allowed_agents=allowed_agents,
        conversation_history=conversation_history,
        user_role=user_role,
    )


# ── Legacy helper (backward compat) ──────────────────────────────────────────

def route_to_agent(user_message: str, user_name: str = "User") -> dict:
    """Legacy wrapper kept for backward compatibility."""
    result = orchestrator.route(user_message, user_name, attachments=None)
    return {
        "user_message": user_message,
        "agent_used":   ", ".join(result["agents_used"]),
        "response":     result["final_answer"],
        "agents_used":  result["agents_used"],
        "responses":    result["responses"],
    }
