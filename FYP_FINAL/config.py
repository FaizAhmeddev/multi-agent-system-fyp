"""
FYP configuration — paths, RBAC, and **secrets from environment variables**.

For local development, copy `.env.example` to `.env` in this folder and fill in values.
Never commit `.env` or real API keys to GitHub.
"""
import json as _json
import os as _os

_PROJECT_ROOT = _os.path.abspath(_os.path.dirname(__file__))


def _env(name: str, default: str = "") -> str:
    """Read env var; strip whitespace; treat empty as missing → use default."""
    raw = _os.environ.get(name)
    if raw is None:
        return default
    s = str(raw).strip()
    return s if s else default


def load_local_env() -> bool:
    """Load FYP_FINAL/.env into os.environ (safe to call multiple times)."""
    path = _os.path.join(_PROJECT_ROOT, ".env")
    if not _os.path.isfile(path):
        return False
    try:
        from dotenv import load_dotenv

        load_dotenv(path, override=True)
        # True if at least one common secret key is present
        return bool(
            _os.environ.get("OPENAI_API_KEY")
            or _os.environ.get("GMAIL_EMAIL")
            or _os.environ.get("GMAIL_APP_PASSWORD")
        )
    except ImportError:
        return False


load_local_env()

# ─── OpenAI ────────────────────────────────────────────────
OPENAI_API_KEY = _env("OPENAI_API_KEY")

# ─── Gmail ─────────────────────────────────────────────────
GMAIL_EMAIL = _env("GMAIL_EMAIL")
GMAIL_APP_PASSWORD = _env("GMAIL_APP_PASSWORD").replace(" ", "")


class GmailNotConfiguredError(RuntimeError):
    """Raised when GMAIL_EMAIL / GMAIL_APP_PASSWORD are missing."""


def refresh_config_from_env() -> None:
    """Reload secrets from os.environ (after .env or Streamlit Secrets hydration)."""
    global OPENAI_API_KEY, GMAIL_EMAIL, GMAIL_APP_PASSWORD
    global TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, TWILIO_WHATSAPP_TO, TWILIO_CONTENT_SID
    global GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, DEMO_MODE, USERS, DATABASE_URL

    OPENAI_API_KEY = _env("OPENAI_API_KEY")
    GMAIL_EMAIL = _env("GMAIL_EMAIL")
    GMAIL_APP_PASSWORD = _env("GMAIL_APP_PASSWORD").replace(" ", "")

    TWILIO_ACCOUNT_SID = _env("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = _env("TWILIO_AUTH_TOKEN")
    TWILIO_WHATSAPP_FROM = _env("TWILIO_WHATSAPP_FROM")
    TWILIO_WHATSAPP_TO = _env("TWILIO_WHATSAPP_TO")
    TWILIO_CONTENT_SID = _env("TWILIO_CONTENT_SID")

    _gcf = _env("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    GOOGLE_CREDENTIALS_FILE = _gcf if _os.path.isabs(_gcf) else _os.path.join(_PROJECT_ROOT, _gcf)
    _gtf = _env("GOOGLE_TOKEN_FILE", "token.json")
    GOOGLE_TOKEN_FILE = _gtf if _os.path.isabs(_gtf) else _os.path.join(_PROJECT_ROOT, _gtf)

    DEMO_MODE = _env("DEMO_MODE", "false").lower() in ("1", "true", "yes")
    DATABASE_URL = _env("DATABASE_URL", "")

    USERS = {
        "admin": {"password": _env("FYP_PASSWORD_ADMIN", "admin123"), "role": "Admin", "name": "System Admin"},
        "hr": {"password": _env("FYP_PASSWORD_HR", "hr123"), "role": "HR Manager", "name": "HR Manager"},
        "finance": {"password": _env("FYP_PASSWORD_FINANCE", "finance123"), "role": "Finance Manager", "name": "Finance Manager"},
        "it": {"password": _env("FYP_PASSWORD_IT", "it123"), "role": "IT Staff", "name": "IT Support"},
        "demo": {"password": _env("FYP_PASSWORD_DEMO", "demo123"), "role": "Admin", "name": "Demo User"},
        "assistant": {"password": _env("FYP_PASSWORD_ASSISTANT", "assistant123"), "role": "Assistant", "name": "Office Assistant"},
    }


def is_gmail_configured() -> bool:
    email = (_env("GMAIL_EMAIL") or GMAIL_EMAIL or "").strip()
    pwd = (_env("GMAIL_APP_PASSWORD") or GMAIL_APP_PASSWORD or "").replace(" ", "")
    return bool(email and pwd)


def gmail_setup_hint() -> str:
    """Human-readable reason Gmail is not ready (for UI warnings)."""
    env_path = _os.path.join(_PROJECT_ROOT, ".env")
    has_file = _os.path.isfile(env_path)
    email = (_env("GMAIL_EMAIL") or GMAIL_EMAIL or "").strip()
    pwd = (_env("GMAIL_APP_PASSWORD") or GMAIL_APP_PASSWORD or "").replace(" ", "")
    if has_file and (not email or not pwd):
        missing = []
        if not email:
            missing.append("`GMAIL_EMAIL`")
        if not pwd:
            missing.append("`GMAIL_APP_PASSWORD`")
        return (
            f"Your **FYP_FINAL/.env** file exists but {', '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} **empty**. "
            "Open that file, paste your Gmail address and App Password, save, then restart the app "
            "(Ctrl+C in terminal, run `python main.py` again)."
        )
    if not has_file:
        return (
            "No **FYP_FINAL/.env** file found. Copy `.env.example` to `.env`, "
            "fill `GMAIL_EMAIL` and `GMAIL_APP_PASSWORD`, then restart."
        )
    return "Gmail credentials missing. Check FYP_FINAL/.env or Streamlit Secrets."


def gmail_credentials() -> tuple[str, str]:
    """Return (email, app_password) or raise GmailNotConfiguredError with setup hints."""
    email = (_env("GMAIL_EMAIL") or GMAIL_EMAIL or "").strip()
    pwd = (_env("GMAIL_APP_PASSWORD") or GMAIL_APP_PASSWORD or "").replace(" ", "")
    if not email or not pwd:
        raise GmailNotConfiguredError(
            "Gmail is not configured (IMAP LOGIN needs email + app password).\n\n"
            "Local terminal:\n"
            "  1. Copy FYP_FINAL/.env.example → FYP_FINAL/.env\n"
            "  2. Set GMAIL_EMAIL and GMAIL_APP_PASSWORD (Google Account → App passwords)\n"
            "     OR copy FYP_FINAL/.streamlit/secrets.toml.example → secrets.toml and fill keys.\n\n"
            "Streamlit Cloud: App settings → Secrets → same keys as .env.example"
        )
    return email, pwd

# ─── Google Drive OAuth ────────────────────────────────────
_gcf = _env("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_CREDENTIALS_FILE = _gcf if _os.path.isabs(_gcf) else _os.path.join(_PROJECT_ROOT, _gcf)
_gtf = _env("GOOGLE_TOKEN_FILE", "token.json")
GOOGLE_TOKEN_FILE = _gtf if _os.path.isabs(_gtf) else _os.path.join(_PROJECT_ROOT, _gtf)


class DriveNotConfiguredError(RuntimeError):
    """Raised when Google Drive credentials are missing or invalid."""


def _env_json_dict(name: str) -> dict | None:
    raw = _env(name, "")
    if not raw:
        return None
    try:
        data = _json.loads(raw)
        return data if isinstance(data, dict) else None
    except _json.JSONDecodeError:
        return None


def google_token_dict() -> dict | None:
    """OAuth user token (token.json) from env JSON or file."""
    data = _env_json_dict("GOOGLE_TOKEN_JSON")
    if data:
        return data
    if _os.path.isfile(GOOGLE_TOKEN_FILE):
        try:
            with open(GOOGLE_TOKEN_FILE, encoding="utf-8") as f:
                loaded = _json.load(f)
            return loaded if isinstance(loaded, dict) else None
        except Exception:
            return None
    return None


def google_oauth_client_config() -> dict | None:
    """OAuth client secrets (credentials.json) from env JSON or file."""
    data = _env_json_dict("GOOGLE_CREDENTIALS_JSON")
    if data:
        return data
    if _os.path.isfile(GOOGLE_CREDENTIALS_FILE):
        try:
            with open(GOOGLE_CREDENTIALS_FILE, encoding="utf-8") as f:
                loaded = _json.load(f)
            return loaded if isinstance(loaded, dict) else None
        except Exception:
            return None
    return None


def google_service_account_info() -> dict | None:
    """Service account JSON from GOOGLE_SERVICE_ACCOUNT_JSON secret."""
    return _env_json_dict("GOOGLE_SERVICE_ACCOUNT_JSON")


def is_google_drive_configured() -> bool:
    if google_service_account_info():
        return True
    if google_token_dict():
        return True
    if google_oauth_client_config() and not is_hosted_deploy():
        return True
    return False


def can_manage_background_services(role: str) -> bool:
    """MCP server + Gmail monitor controls (Admin / IT only)."""
    return role in ("Admin", "IT Staff")

# ─── Twilio WhatsApp ───────────────────────────────────────
TWILIO_ACCOUNT_SID = _env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = _env("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = _env("TWILIO_WHATSAPP_FROM")
TWILIO_WHATSAPP_TO = _env("TWILIO_WHATSAPP_TO")
TWILIO_CONTENT_SID = _env("TWILIO_CONTENT_SID")

# ─── Database ──────────────────────────────────────────────
DB_PATH = _os.path.join(_PROJECT_ROOT, "database", "fyp_data.db")
CHROMA_PATH = _os.path.join(_PROJECT_ROOT, "database", "chroma_db")
DATABASE_URL = _env("DATABASE_URL", "")


def get_database_url() -> str:
    """PostgreSQL when DATABASE_URL is set; otherwise local SQLite file."""
    url = (DATABASE_URL or _env("DATABASE_URL", "")).strip()
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        return url
    return f"sqlite:///{DB_PATH}"


def use_postgresql_database() -> bool:
    return get_database_url().startswith("postgresql")

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


def local_background_services_enabled() -> bool:
    """In-process MCP HTTP server and Gmail IMAP monitor (not available on Streamlit Cloud)."""
    return not is_hosted_deploy()


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
