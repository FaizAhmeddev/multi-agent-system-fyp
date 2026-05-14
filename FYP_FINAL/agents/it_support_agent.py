"""
AGENTS/IT_SUPPORT_AGENT.PY
===========================
IT Support Agent — uses ChromaDB knowledge base + GPT-4o-mini.
Auto-creates IT tickets in SQLite.
"""
import os

def _get_llm():
    from langchain_openai import ChatOpenAI
    from config import OPENAI_API_KEY
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.3)

IT_KEYWORDS = [
    "computer", "laptop", "pc", "mac", "macbook", "iphone", "android", "phone", "tablet", "ipad",
    "wifi", "wi-fi", "internet", "password", "login", "software", "app", "application",
    "install", "error", "crash", "slow", "printer", "network", "screen", "keyboard",
    "mouse", "virus", "update", "windows", "system", "restart", "freeze", "blue screen", "bsod",
    "not working", "broken", "connection", "vpn", "access", "reset", "boot", "driver",
    "device", "hardware", "monitor", "usb", "teams", "zoom", "outlook", "email", "browser",
    "chrome", "edge", "firefox", "website", "loading", "stuck", "frozen", "sound", "audio",
    "microphone", "camera", "battery", "charger", "black screen", "blank", "file", "folder",
    "onedrive", "sharepoint", "microsoft", "google", "account", "sync", "backup", "disk",
]

def detect_it_issue(text: str):
    t = text.lower()
    matched = [kw for kw in IT_KEYWORDS if kw in t]
    return len(matched) > 0, matched

def solve_it_problem(state: dict) -> dict:
    problem   = state.get("it_problem", "")
    user_name = state.get("user_name", "User")
    is_it, matched = detect_it_issue(problem)

    if not (problem or "").strip():
        state["it_solution"] = "Describe your IT problem above, then click **Get Solution**."
        state["it_handled"] = False
        return state

    # Do not hard-reject by keywords: many real IT issues are phrased without matching
    # ("my PC won't turn on", "Chrome tab keeps reloading"). Keywords only enrich the prompt.
    low_signal = not is_it

    # Search ChromaDB knowledge base first
    kb_context = ""
    try:
        from database.vector_db import semantic_search
        hits = semantic_search(problem, collection_name="it_knowledge", top_k=3)
        if hits:
            kb_context = "\n\n".join([f"Past solution: {h['text']}" for h in hits[:2]])
    except Exception:
        pass

    try:
        llm    = _get_llm()
        kb_sec = f"\n\nKnowledge Base Reference:\n{kb_context}" if kb_context else ""
        hint = (
            "Optional context: wording matched few built-in IT keywords — still treat as IT/tech if it involves "
            "devices, software, accounts, or workplace tools. If it is clearly only HR/finance/recruiting with no "
            "technology angle, reply briefly and suggest the matching tab."
            if low_signal
            else ""
        )
        prompt = f"""You are a professional IT Support Agent.

Employee "{user_name}" reports: "{problem}"
Detected keywords: {', '.join(matched) if matched else '(none — infer from full text)'}{kb_sec}
{hint}

Provide:
1. **Diagnosis** (1-2 sentences)
2. **Step-by-step Solution** (numbered, clear)
3. **Prevention Tip** (1 sentence)
4. If hardware repair needed: "Contact IT dept at ext. 100"

Be friendly, professional, concise."""

        response = llm.invoke(prompt)
        state["it_solution"] = response.content
        state["it_handled"]  = True

        # Save ticket to DB
        try:
            from database.sqlite_db import log_it_ticket, log_agent
            tid = log_it_ticket(user_name, problem, response.content)
            state["ticket_id"] = tid
            log_agent("IT Support Agent", "solve_problem", problem, response.content)
        except Exception:
            pass

    except Exception as e:
        state["it_solution"] = f"❌ Error: {e}. Set OPENAI_API_KEY in `.env` (see `.env.example`)."
        state["it_handled"]  = False

    return state
