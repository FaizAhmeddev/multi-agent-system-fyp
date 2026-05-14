"""
FYP configuration — paths, RBAC, and **secrets from environment variables**.

For local development, copy `.env.example` to `.env` in this folder and fill in values.
Never commit `.env` or real API keys to GitHub.
"""
import os as _os

_PROJECT_ROOT = _os.path.abspath(_os.path.dirname(__file__))


def _env(name: str, default: str = "") -> str:
    """Read env var; strip whitespace; treat empty as missing → use default."""
    raw = _os.environ.get(name)
    if raw is None:
        return default
    s = str(raw).strip()
    return s if s else default


# Load `.env` from project root (optional file; not committed)
try:
    from dotenv import load_dotenv

    load_dotenv(_os.path.join(_PROJECT_ROOT, ".env"))
except ImportError:
    pass

# ─── OpenAI ────────────────────────────────────────────────
OPENAI_API_KEY = _env("OPENAI_API_KEY")

# ─── Gmail ─────────────────────────────────────────────────
GMAIL_EMAIL = _env("GMAIL_EMAIL")
GMAIL_APP_PASSWORD = _env("GMAIL_APP_PASSWORD").replace(" ", "")

# ─── Google Drive OAuth ────────────────────────────────────
_gcf = _env("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_CREDENTIALS_FILE = _gcf if _os.path.isabs(_gcf) else _os.path.join(_PROJECT_ROOT, _gcf)
_gtf = _env("GOOGLE_TOKEN_FILE", "token.json")
GOOGLE_TOKEN_FILE = _gtf if _os.path.isabs(_gtf) else _os.path.join(_PROJECT_ROOT, _gtf)

# ─── Twilio WhatsApp ───────────────────────────────────────
TWILIO_ACCOUNT_SID = _env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = _env("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = _env("TWILIO_WHATSAPP_FROM")
TWILIO_WHATSAPP_TO = _env("TWILIO_WHATSAPP_TO")
TWILIO_CONTENT_SID = _env("TWILIO_CONTENT_SID")

# ─── Database ──────────────────────────────────────────────
DB_PATH = _os.path.join(_PROJECT_ROOT, "database", "fyp_data.db")
CHROMA_PATH = _os.path.join(_PROJECT_ROOT, "database", "chroma_db")

# ─── Message Queue ─────────────────────────────────────────
MESSAGE_QUEUE_MAX_SIZE = 1000
MESSAGE_QUEUE_TTL = 3600

# ─── MCP Server ────────────────────────────────────────────
MCP_SERVER_HOST = _env("MCP_SERVER_HOST", "localhost")
try:
    MCP_SERVER_PORT = int(_env("MCP_SERVER_PORT", "8765"))
except ValueError:
    MCP_SERVER_PORT = 8765

# ─── Demo Mode ─────────────────────────────────────────────
DEMO_MODE = _env("DEMO_MODE", "false").lower() in ("1", "true", "yes")

# ─── Hosted deploy (Streamlit Community Cloud, etc.) ────────
# Set FYP_HOSTED=true in `.env` locally or in Streamlit **Secrets** (flat key) so the UI
# skips starting the in-process MCP HTTP server (often unnecessary or unreliable when hosted).
def is_hosted_deploy() -> bool:
    if _env("FYP_HOSTED", "").lower() in ("1", "true", "yes"):
        return True
    if _env("FYP_HOSTED", "").lower() in ("0", "false", "no"):
        return False
    # Some Streamlit Community Cloud runtimes set this (when present, skip in-process MCP).
    if _env("STREAMLIT_SHARING_MODE", "").lower() == "streamlit":
        return True
    # Legacy Community Cloud mount path (still seen on some runners).
    try:
        if _os.path.isdir("/mount/src"):
            return True
    except Exception:
        pass
    # Public app URL sometimes appears in Streamlit-related env vars on hosted tiers.
    for _k, _v in _os.environ.items():
        if not _k.upper().startswith("STREAMLIT"):
            continue
        if "streamlit.app" in str(_v).lower():
            return True
    try:
        import getpass

        if getpass.getuser() == "appuser":
            return True
    except Exception:
        pass
    return False

# ─── Login Users (passwords overridable via env for production) ─
USERS = {
    "admin": {
        "password": _env("FYP_PASSWORD_ADMIN", "admin123"),
        "role": "Admin",
        "name": "System Admin",
    },
    "hr": {
        "password": _env("FYP_PASSWORD_HR", "hr123"),
        "role": "HR Manager",
        "name": "HR Manager",
    },
    "finance": {
        "password": _env("FYP_PASSWORD_FINANCE", "finance123"),
        "role": "Finance Manager",
        "name": "Finance Manager",
    },
    "it": {
        "password": _env("FYP_PASSWORD_IT", "it123"),
        "role": "IT Staff",
        "name": "IT Support",
    },
    "demo": {
        "password": _env("FYP_PASSWORD_DEMO", "demo123"),
        "role": "Admin",
        "name": "Demo User",
    },
    "assistant": {
        "password": _env("FYP_PASSWORD_ASSISTANT", "assistant123"),
        "role": "Assistant",
        "name": "Office Assistant",
    },
}

# ─── RBAC: which Streamlit tabs each role may open (subset of canonical order) ─
_FULL_TABS = [
    "Assistant",
    "Dashboard",
    "Recruitment AI",
    "IT Support",
    "Email",
    "HR",
    "Finance",
    "Documents",
    "WhatsApp",
    "History",
]

ROLE_VISIBLE_TABS = {
    "Admin": None,
    "Demo User": None,
    "HR Manager": {
        "Assistant",
        "Dashboard",
        "Recruitment AI",
        "Email",
        "HR",
        "History",
    },
    "Assistant": {"Email", "History"},
    "Finance Manager": {"Assistant", "Dashboard", "Finance", "History"},
    "IT Staff": {"Assistant", "Dashboard", "IT Support", "History"},
}

# Orchestrator agent slugs; None = no filter (all agents allowed)
ROLE_ORCHESTRATOR_ALLOWLIST = {
    "Admin": None,
    "Demo User": None,
    "HR Manager": ["hr", "recruitment", "email", "hr_gmail"],
    "Assistant": ["email", "hr_gmail"],
    "Finance Manager": ["finance"],
    "IT Staff": ["it_support"],
}


def get_visible_tabs_for_role(role: str) -> list[str]:
    allowed = ROLE_VISIBLE_TABS.get(role)
    if allowed is None:
        return list(_FULL_TABS)
    return [t for t in _FULL_TABS if t in allowed]


def get_role_orchestrator_allowlist(role: str):
    """
    Return list of agent slugs allowed for this role, or None for unrestricted (admin/demo).
    """
    if role in ("Admin", "Demo User"):
        return None
    v = ROLE_ORCHESTRATOR_ALLOWLIST.get(role)
    if v is None:
        return None
    return list(v)


ROLE_PORTAL_BANNERS = {
    "Admin": """<div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);color:#e2e8f0;padding:16px 20px;border-radius:14px;margin-bottom:14px;border:1px solid #334155">
<b style="font-size:15px">Administrator portal</b> — full orchestrator, all departments, MCP tools, recruitment approvals, and system analytics.</div>""",
    "HR Manager": """<div style="background:linear-gradient(135deg,#4c1d95,#6d28d9);color:#faf5ff;padding:16px 20px;border-radius:14px;margin-bottom:14px;border:1px solid #7c3aed">
<b style="font-size:15px">HR operations portal</b> — CV screening, Gmail shortlist with <b>human approval before send</b>, recruitment pipeline, and email — not generic Q&amp;A: operational hiring workflows.</div>""",
    "Assistant": """<div style="background:linear-gradient(135deg,#0f766e,#115e59);color:#ecfdf5;padding:16px 20px;border-radius:14px;margin-bottom:14px;border:1px solid #14b8a6">
<b style="font-size:15px">Assistant portal</b> — <b>Email</b> plus <b>Gmail CV shortlist</b> (fetch → rank → <b>approve before send</b>). Other departments stay hidden.</div>""",
    "Finance Manager": """<div style="background:linear-gradient(135deg,#14532d,#166534);color:#f0fdf4;padding:16px 20px;border-radius:14px;margin-bottom:14px;border:1px solid #22c55e">
<b style="font-size:15px">Finance portal</b> — budgets, expenses, invoices, and reports. Numbers stay in Finance; no HR or IT agent routes.</div>""",
    "IT Staff": """<div style="background:linear-gradient(135deg,#1e3a8a,#1d4ed8);color:#eff6ff;padding:16px 20px;border-radius:14px;margin-bottom:14px;border:1px solid #3b82f6">
<b style="font-size:15px">IT support portal</b> — tickets, troubleshooting, and inbox auto-reply monitor. Scoped to IT operations.</div>""",
}

# ─── Agent IDs ─────────────────────────────────────────────
AGENT_IDS = {
    "orchestrator": "orch-001",
    "general": "agent-general-001",
    "hr_gmail": "agent-hr-gmail-001",
    "it_support": "agent-it-001",
    "email": "agent-email-001",
    "hr": "agent-hr-001",
    "recruitment": "agent-recruitment-001",
    "finance": "agent-finance-001",
    "documents": "agent-docs-001",
    "auto_reply": "agent-autoreply-001",
    "whatsapp": "agent-whatsapp-001",
}
