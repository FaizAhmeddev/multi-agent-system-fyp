"""
UI/APP.PY 
==========================================================
Tabs: Login | Assistant (orchestrator) | Dashboard | specialist tools | History
"""
import sys, os, time, json
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Local dev: load FYP_FINAL/.env before Streamlit / config read credentials
try:
    from config import load_local_env
    load_local_env()
except Exception:
    try:
        from dotenv import load_dotenv
        _env_file = os.path.join(ROOT, ".env")
        if os.path.isfile(_env_file):
            load_dotenv(_env_file)
    except Exception:
        pass

import logging
import warnings

try:
    from langchain_core._api.deprecation import LangChainPendingDeprecationWarning
except Exception:
    LangChainPendingDeprecationWarning = None  # type: ignore
if LangChainPendingDeprecationWarning is not None:
    warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)
warnings.filterwarnings("ignore", message=".*allowed_objects.*")

for _lg in (
    "transformers",
    "transformers.models",
    "huggingface_hub",
    "chromadb",
    "sentence_transformers",
    "torch",
):
    logging.getLogger(_lg).setLevel(logging.CRITICAL)

import streamlit as st

st.set_page_config(
    page_title="Office Automation Agents Pro",
    layout="wide", page_icon="ðŸ¤–",
    initial_sidebar_state="expanded",
)


def _hydrate_streamlit_secrets_into_environ() -> None:
    """
    On Streamlit Community Cloud, secrets live in st.secrets, not os.environ.
    config.py reads API keys from the environment (and .env locally), so copy flat
    secret entries into os.environ before importing config.
    """
    try:
        sec = st.secrets
        items = sec.items()
    except FileNotFoundError:
        # No secrets.toml â€” normal for local dev when using .env instead
        return
    except Exception:
        return
    for key, val in items:
        if val is None or not key or str(key).startswith("_"):
            continue
        if isinstance(val, dict):
            continue
        if isinstance(val, (list, tuple)):
            continue
        k = str(key).strip()
        if os.environ.get(k):
            continue
        s = str(val).strip()
        if s:
            os.environ[k] = s


_hydrate_streamlit_secrets_into_environ()

from config import (
    get_visible_tabs_for_role,
    get_role_orchestrator_allowlist,
    ROLE_PORTAL_BANNERS,
    is_hosted_deploy,
    local_background_services_enabled,
    can_manage_background_services,
    can_use_email_monitor,
    gmail_setup_hint,
    is_gmail_configured,
    is_google_drive_configured,
    DriveNotConfiguredError,
    use_postgresql_database,
    refresh_config_from_env,
    OPENAI_API_KEY,
)

refresh_config_from_env()

# â”€â”€ CSS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
:root {
    --bg: #0b1220;
    --surface: #141d30;
    --surface-2: #1b2740;
    --border: #28344d;
    --text: #e8edf6;
    --muted: #94a3b8;
    --primary: #6366f1;
    --primary-dark: #4f46e5;
    --primary-light: #818cf8;
    --accent: #38bdf8;
    --accent-light: #0c4a6e;
    --success: #34d399;
    --success-bg: #06281f;
    --warning: #fbbf24;
    --warning-bg: #2a2008;
    --danger: #f87171;
    --danger-bg: #2a1115;
    --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.30);
    --shadow-md: 0 4px 10px -2px rgba(0, 0, 0, 0.40);
    --shadow-lg: 0 12px 24px -6px rgba(0, 0, 0, 0.50);
    --shadow-xl: 0 24px 40px -10px rgba(0, 0, 0, 0.55);
    --radius-sm: 6px;
    --radius-md: 12px;
    --radius-lg: 18px;
}
.stApp, .stMarkdown, .stMarkdown p, .stMarkdown li, .stTextInput label, .stTextArea label,
.stSelectbox label, .stHeader label, .stButton button, .stForm label, .stCaption, .stAlert,
[data-testid="stWidgetLabel"], input, textarea, select {
    font-family: 'Plus Jakarta Sans', 'Inter', sans-serif !important;
}
[data-testid="stIconMaterial"], .material-symbols-rounded, .material-icons {
    font-family: 'Material Symbols Rounded', 'Material Icons' !important;
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24 !important;
    letter-spacing: normal !important;
    text-transform: none !important;
    white-space: nowrap !important;
}
.main { padding-top: 0.4rem; background: transparent; }
.stApp {
    background-color: var(--bg);
    background-image:
        radial-gradient(900px 500px at 12% -8%, rgba(99,102,241,0.16), transparent 60%),
        radial-gradient(800px 500px at 100% 0%, rgba(56,189,248,0.10), transparent 55%),
        radial-gradient(rgba(148, 163, 184, 0.07) 1.4px, transparent 1.4px);
    background-size: auto, auto, 24px 24px;
    background-attachment: fixed;
}

/* Custom buttons */
.stButton > button {
    border-radius: 10px !important;
    padding: 10px 20px !important;
    font-weight: 600 !important;
    border: 1px solid var(--border) !important;
    background: var(--surface) !important;
    color: var(--text) !important;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    box-shadow: var(--shadow-sm) !important;
}
.stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: var(--shadow-md) !important;
    border-color: var(--primary-light) !important;
    color: var(--primary) !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--primary), var(--primary-dark)) !important;
    color: white !important;
    border: none !important;
    box-shadow: 0 4px 14px rgba(79, 70, 229, 0.3) !important;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, var(--primary-dark), var(--primary)) !important;
    box-shadow: 0 6px 18px rgba(79, 70, 229, 0.4) !important;
    transform: translateY(-2px) !important;
    color: white !important;
}

/* Tabs styled as segmented pill control */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px !important;
    background: rgba(226, 232, 240, 0.5) !important;
    padding: 6px !important;
    border-radius: var(--radius-md) !important;
    border: 1px solid var(--border) !important;
    backdrop-filter: blur(8px) !important;
    margin-bottom: 20px !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    border: none !important;
    border-radius: 8px !important;
    color: var(--muted) !important;
    padding: 10px 20px !important;
    font-weight: 600 !important;
    transition: all 0.2s ease-in-out !important;
}
.stTabs [data-baseweb="tab"]:hover {
    background: rgba(255, 255, 255, 0.6) !important;
    color: var(--text) !important;
}
.stTabs [aria-selected="true"] {
    background: var(--surface) !important;
    color: var(--primary) !important;
    box-shadow: var(--shadow-md) !important;
    border-bottom: none !important;
}

/* ===== Auth / login screen (enterprise portal) ===== */
body:has(.auth-page-wrap) [data-testid="stSidebar"],
body:has(.auth-page-wrap) [data-testid="stHeader"],
body:has(.auth-page-wrap) footer,
body:has(.auth-page-wrap) [data-testid="stToolbar"] {
    display: none !important;
}
body:has(.auth-page-wrap) .main .block-container {
    max-width: 100% !important;
    padding: 0 !important;
}
body:has(.auth-page-wrap) .stApp {
    background: #050816 !important;
    background-image:
        radial-gradient(ellipse 80% 60% at 15% 20%, rgba(20, 184, 166, 0.22), transparent 55%),
        radial-gradient(ellipse 70% 55% at 85% 75%, rgba(124, 58, 237, 0.20), transparent 50%),
        radial-gradient(ellipse 50% 40% at 50% 100%, rgba(244, 63, 94, 0.08), transparent 45%) !important;
}
.auth-page-wrap {
    min-height: 100vh;
    display: flex;
    align-items: stretch;
    padding: 0;
}
.auth-hero-panel {
    position: relative;
    border-radius: 0 28px 28px 0;
    padding: 3rem 2.5rem;
    background: linear-gradient(155deg, #0f766e 0%, #1e3a8a 42%, #5b21b6 100%);
    color: #f8fafc;
    overflow: hidden;
    min-height: 520px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    box-shadow: 0 30px 60px -20px rgba(15, 118, 110, 0.45);
}
.auth-hero-panel::before {
    content: "";
    position: absolute;
    inset: 0;
    background:
        radial-gradient(circle at 20% 30%, rgba(255,255,255,0.14), transparent 42%),
        radial-gradient(circle at 80% 70%, rgba(45, 212, 191, 0.18), transparent 40%);
    pointer-events: none;
}
.auth-hero-panel::after {
    content: "";
    position: absolute;
    width: 320px;
    height: 320px;
    right: -80px;
    bottom: -80px;
    border-radius: 50%;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10);
}
.auth-hero-inner { position: relative; z-index: 1; }
.auth-hero-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    background: rgba(255,255,255,0.12);
    border: 1px solid rgba(255,255,255,0.22);
    color: #ccfbf1;
    margin-bottom: 1.25rem;
}
.auth-hero-logo {
    width: 56px;
    height: 56px;
    border-radius: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 26px;
    background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.25);
    backdrop-filter: blur(8px);
    margin-bottom: 1.25rem;
    box-shadow: 0 8px 24px rgba(0,0,0,0.2);
}
.auth-hero-panel h1 {
    font-size: 2rem;
    font-weight: 800;
    letter-spacing: -0.04em;
    margin: 0 0 0.5rem;
    line-height: 1.15;
    color: #ffffff;
}
.auth-hero-panel p {
    font-size: 15px;
    color: rgba(226, 232, 240, 0.88);
    margin: 0 0 1.75rem;
    line-height: 1.6;
    max-width: 340px;
}
.auth-feature-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 12px;
}
.auth-feature-list li {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 13.5px;
    font-weight: 500;
    color: rgba(241, 245, 249, 0.92);
}
.auth-feature-icon {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    background: rgba(255,255,255,0.12);
    border: 1px solid rgba(255,255,255,0.18);
    flex-shrink: 0;
}
.auth-form-shell {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem 1.5rem;
    min-height: 520px;
}
.auth-card {
    width: 100%;
    max-width: 420px;
    background: rgba(15, 23, 42, 0.72);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-radius: 22px;
    padding: 2rem 1.75rem 1.5rem;
    border: 1px solid rgba(148, 163, 184, 0.18);
    box-shadow:
        0 24px 48px -12px rgba(0, 0, 0, 0.55),
        inset 0 1px 0 rgba(255, 255, 255, 0.06);
}
.auth-card-header { margin-bottom: 1.25rem; }
.auth-card-icon {
    width: 44px;
    height: 44px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    margin-bottom: 0.85rem;
    background: linear-gradient(135deg, rgba(20, 184, 166, 0.25), rgba(99, 102, 241, 0.25));
    border: 1px solid rgba(45, 212, 191, 0.35);
}
.auth-card-header h2 {
    font-size: 1.45rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: #f1f5f9;
    margin: 0 0 0.35rem;
}
.auth-card-header p {
    font-size: 13.5px;
    color: #94a3b8;
    margin: 0;
    line-height: 1.5;
}
.auth-demo-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-top: 0.85rem;
    padding: 8px 12px;
    border-radius: 10px;
    font-size: 12px;
    color: #99f6e4;
    background: rgba(20, 184, 166, 0.12);
    border: 1px solid rgba(45, 212, 191, 0.25);
}
.auth-divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(148,163,184,0.25), transparent);
    margin: 1.25rem 0 0.75rem;
}
.auth-footer-note {
    text-align: center;
    font-size: 11.5px;
    color: #64748b;
    margin-top: 1rem;
}
body:has(.auth-page-wrap) .stTextInput label,
body:has(.auth-page-wrap) [data-testid="stWidgetLabel"] p {
    color: #cbd5e1 !important;
    font-weight: 600 !important;
    font-size: 13px !important;
}
body:has(.auth-page-wrap) .stTextInput input {
    background: rgba(2, 6, 23, 0.65) !important;
    border: 1px solid rgba(148, 163, 184, 0.22) !important;
    border-radius: 12px !important;
    color: #f8fafc !important;
    padding: 0.65rem 0.85rem !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
}
body:has(.auth-page-wrap) .stTextInput input:focus {
    border-color: #2dd4bf !important;
    box-shadow: 0 0 0 3px rgba(45, 212, 191, 0.18) !important;
}
body:has(.auth-page-wrap) .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #14b8a6, #6366f1) !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 0.7rem 1.25rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.01em !important;
    box-shadow: 0 8px 24px rgba(20, 184, 166, 0.35) !important;
}
body:has(.auth-page-wrap) .stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #0d9488, #4f46e5) !important;
    box-shadow: 0 12px 28px rgba(99, 102, 241, 0.4) !important;
}
body:has(.auth-page-wrap) .stButton > button:not([kind="primary"]) {
    background: rgba(30, 41, 59, 0.6) !important;
    border: 1px solid rgba(148, 163, 184, 0.2) !important;
    color: #e2e8f0 !important;
    border-radius: 12px !important;
}
body:has(.auth-page-wrap) .stButton > button:not([kind="primary"]):hover {
    background: rgba(51, 65, 85, 0.75) !important;
    border-color: rgba(45, 212, 191, 0.35) !important;
    color: #ffffff !important;
}
body:has(.auth-page-wrap) [data-testid="stVerticalBlockBorderWrapper"] {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
}
body:has(.auth-page-wrap) .stCaption,
body:has(.auth-page-wrap) [data-testid="stCaptionContainer"] {
    color: #94a3b8 !important;
}
@media (max-width: 900px) {
    .auth-hero-panel { border-radius: 0; min-height: auto; padding: 2rem 1.5rem; }
    .auth-form-shell { min-height: auto; padding: 1.5rem 1rem 2.5rem; }
}

/* Floating Glassmorphic Header */
.main-header {
    background: rgba(15, 23, 42, 0.9) !important;
    backdrop-filter: blur(12px) !important;
    -webkit-backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    padding: 20px 28px !important;
    border-radius: var(--radius-md) !important;
    margin-bottom: 24px !important;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 10px 30px -10px rgba(15, 23, 42, 0.3) !important;
}
.header-title {
    font-size: 24px !important;
    font-weight: 800 !important;
    letter-spacing: -0.6px !important;
    background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%);
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
}
.header-sub {
    font-size: 12px !important;
    color: #94a3b8 !important;
    margin-top: 4px !important;
    letter-spacing: 0.2px !important;
}

/* Modernized Left-Border Section Headers */
.sec-hdr {
    background: rgba(255, 255, 255, 0.8) !important;
    border-left: 5px solid var(--primary) !important;
    color: var(--text) !important;
    border-radius: 0 var(--radius-md) var(--radius-md) 0 !important;
    padding: 12px 18px !important;
    margin: 20px 0 14px 0 !important;
    font-weight: 700 !important;
    font-size: 15px !important;
    letter-spacing: 0.1px !important;
    box-shadow: var(--shadow-sm) !important;
    border: 1px solid var(--border) !important;
    border-left-width: 5px !important;
}
.sec-blue   { border-left-color: #3b82f6 !important; }
.sec-green  { border-left-color: var(--success) !important; }
.sec-purple { border-left-color: #8b5cf6 !important; }
.sec-teal   { border-left-color: var(--accent) !important; }
.sec-orange { border-left-color: #f97316 !important; }
.sec-wa     { border-left-color: #22c55e !important; }

/* Metrics */
.metric-card {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    padding: 20px 24px !important;
    box-shadow: var(--shadow-md) !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
.metric-card:hover {
    transform: translateY(-4px) !important;
    box-shadow: var(--shadow-lg) !important;
    border-color: var(--primary-light) !important;
}
.metric-num {
    font-size: 36px !important;
    font-weight: 800 !important;
    background: linear-gradient(135deg, var(--primary), var(--accent)) !important;
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
}

/* Agent cards */
.agent-status-card {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    padding: 16px 20px !important;
    display: flex;
    align-items: center;
    gap: 12px;
    box-shadow: var(--shadow-sm) !important;
    transition: all 0.3s ease !important;
}
.agent-status-card:hover {
    transform: translateY(-2px) !important;
    box-shadow: var(--shadow-md) !important;
}
.agent-dot { width: 10px; height: 10px; border-radius: 50%; background: #10b981; flex-shrink: 0; animation: pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.55} }

/* Response boxes */
.resp-box {
    background: var(--surface);
    border-left: 4px solid var(--primary);
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
    padding: 18px 22px;
    margin: 14px 0;
    box-shadow: var(--shadow-md);
    border: 1px solid var(--border);
    border-left-width: 4px;
    line-height: 1.7;
    white-space: pre-wrap;
}
.resp-green  { border-left-color: #059669; }
.resp-purple { border-left-color: #7c3aed; }
.resp-orange { border-left-color: #ea580c; }
.resp-teal   { border-left-color: #0d9488; }
.resp-red    { border-left-color: #dc2626; }

/* Chat Panel & Conversational Bubbles */
.chat-panel {
    background: rgba(248, 250, 252, 0.8) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-lg) !important;
    padding: 20px !important;
    margin-bottom: 20px !important;
    box-shadow: inset 0 2px 4px rgba(15, 23, 42, 0.03) !important;
    backdrop-filter: blur(6px) !important;
}
.chat-user {
    background: linear-gradient(135deg, var(--primary), var(--primary-dark)) !important;
    color: white !important;
    padding: 12px 18px !important;
    border-radius: 18px 18px 4px 18px !important;
    margin: 10px 0 10px auto !important;
    max-width: 75% !important;
    display: block !important;
    font-size: 14px !important;
    line-height: 1.6 !important;
    word-wrap: break-word;
    box-shadow: 0 8px 16px -4px rgba(79, 70, 229, 0.3) !important;
}
.chat-agent {
    background: var(--surface) !important;
    color: var(--text) !important;
    padding: 14px 20px !important;
    border-radius: 18px 18px 18px 4px !important;
    margin: 10px 0 !important;
    max-width: 80% !important;
    display: block !important;
    font-size: 14px !important;
    border: 1px solid var(--border) !important;
    box-shadow: var(--shadow-md) !important;
    line-height: 1.65 !important;
    word-wrap: break-word;
}
.chat-wrap  { width: 100%; margin-bottom: 4px; overflow: hidden; }
.thread-bar {
    background: linear-gradient(90deg, #f0fdf4, #f8fafc) !important;
    border: 1px solid #bbf7d0 !important;
    border-radius: var(--radius-md) !important;
    padding: 12px 18px !important;
    margin-bottom: 16px !important;
    font-size: 13.5px !important;
    color: #166534 !important;
    font-weight: 500 !important;
}

/* Service Pill */
.svc-pill {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
    margin-left: 4px;
    cursor: default;
    border: 1px solid transparent;
}
.svc-on  { background: #dcfce7; color: #15803d; border-color: #86efac; }
.svc-off { background: #f1f5f9; color: #64748b; border-color: #e2e8f0; }
.svc-cloud { background: #e0f2fe; color: #0369a1; border-color: #7dd3fc; }

/* Queue messages */
.qmsg { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 12px; margin-bottom: 5px; font-size: 12px; font-family: monospace; }
.qmsg-task   { border-left: 3px solid #2563eb; }
.qmsg-result { border-left: 3px solid #16a34a; }
.qmsg-status { border-left: 3px solid #f59e0b; }
.qmsg-broadcast { border-left: 3px solid #7c3aed; }

/* Candidate ATS cards */
.cand-card {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    padding: 18px 20px !important;
    margin-bottom: 12px !important;
    box-shadow: var(--shadow-sm) !important;
    border-left: 4px solid var(--primary) !important;
    transition: all 0.2s ease !important;
}
.cand-card:hover {
    transform: translateY(-2px) !important;
    box-shadow: var(--shadow-md) !important;
    border-color: var(--primary-light) !important;
}
.cand-card.rejected { border-left-color: var(--danger) !important; opacity: 0.75 !important; }
.score-bar  { height: 6px; border-radius: 3px; background: #e2e8f0; margin: 8px 0 4px 0; }
.score-fill { height: 6px; border-radius: 3px; background: linear-gradient(90deg, var(--primary), var(--accent)); }

/* History table */
.hist-row { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; margin-bottom: 6px; font-size: 13px; }

/* Notification */
.notif { border-radius: 10px; padding: 10px 14px; margin-bottom: 6px; font-size: 13px; }
.notif-info    { background: #eff6ff; border-left: 4px solid #2563eb; }
.notif-success { background: #f0fdf4; border-left: 4px solid #16a34a; }
.notif-warning { background: #fffbeb; border-left: 4px solid #f59e0b; }
.notif-error   { background: #fef2f2; border-left: 4px solid #dc2626; }

/* A2A flow */
.a2a-flow { background: #0f172a; color: #e2e8f0; border-radius: 12px; padding: 16px 20px; font-family: monospace; font-size: 12px; line-height: 2; }
.a2a-arrow { color: #22c55e; }
.a2a-agent { color: #60a5fa; font-weight: 700; }
.a2a-topic { color: #fbbf24; }

/* Output alignment */
.block-container { max-width: 1280px; }
.stMarkdown, .stMarkdown p, .stMarkdown li { text-align: left; }
.resp-box, .hist-row, .cand-card, .qmsg, .a2a-flow, .chat-agent { text-align: left; }
div[data-testid="column"] { min-width: 0; }

div[data-testid="stForm"] { border: none !important; padding: 0 !important; }
[data-testid="stFileUploader"] section[data-testid="stFileUploadDropzone"] {
    border: 1.5px dashed #cbd5e1; border-radius: 12px; background: #fff;
}
[data-testid="stFileUploader"] section button {
    background: #f8fafc !important; border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important; min-height: 2.75rem;
}
[data-testid="stFileUploader"] section button p { font-size: 14px !important; line-height: 1.4 !important; }
[data-testid="stCheckbox"] label { gap: 0.5rem !important; align-items: center !important; }
[data-testid="stCheckbox"] label p { line-height: 1.4 !important; margin: 0 !important; }
[data-testid="stExpander"] summary { font-weight: 600 !important; }
.email-detail-box {
    background: white; border: 1px solid #e2e8f0; border-radius: 14px;
    padding: 20px 22px; margin-top: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.06);
}
.email-body-full {
    white-space: pre-wrap; line-height: 1.65; font-size: 14px; color: #334155;
    max-height: 420px; overflow-y: auto; padding: 12px; background: #f8fafc;
    border-radius: 8px; border: 1px solid #e2e8f0;
}
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 4px; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
</style>""", unsafe_allow_html=True)

# â”€â”€ Sidebar navigation + layout polish â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.markdown("""<style>
/* ===== Sidebar shell ===== */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #111c33 55%, #0b1426 100%) !important;
    border-right: 1px solid rgba(148,163,184,0.12) !important;
    width: 290px !important;
}
section[data-testid="stSidebar"] > div { padding-top: 0.6rem !important; }
section[data-testid="stSidebar"] * { color: #e2e8f0; }

/* Brand */
.side-brand {
    display:flex; align-items:center; gap:12px;
    padding: 6px 6px 16px; margin-bottom: 4px;
    border-bottom: 1px solid rgba(148,163,184,0.14);
}
.side-logo {
    width:42px; height:42px; border-radius:12px; flex-shrink:0;
    display:flex; align-items:center; justify-content:center; font-size:22px;
    background: linear-gradient(135deg,#6366f1,#8b5cf6);
    box-shadow: 0 6px 16px rgba(99,102,241,0.4);
}
.side-title { font-size:15px; font-weight:800; letter-spacing:-0.02em; color:#f8fafc; }
.side-sub   { font-size:11px; color:#94a3b8; margin-top:2px; }

.side-nav-label {
    font-size:10.5px; font-weight:700; letter-spacing:0.12em; text-transform:uppercase;
    color:#64748b; margin: 14px 6px 8px;
}

/* Nav buttons (override global button look inside sidebar) */
section[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    border: 1px solid transparent !important;
    color: #cbd5e1 !important;
    text-align: left !important;
    justify-content: flex-start !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    padding: 11px 14px !important;
    border-radius: 10px !important;
    box-shadow: none !important;
    margin-bottom: 2px !important;
    transition: all 0.15s ease !important;
}
section[data-testid="stSidebar"] .stButton > button > div { justify-content:flex-start !important; }
section[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(148,163,184,0.12) !important;
    border-color: rgba(148,163,184,0.18) !important;
    color: #ffffff !important;
    transform: none !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, rgba(99,102,241,0.95), rgba(139,92,246,0.95)) !important;
    color: #ffffff !important;
    border: none !important;
    box-shadow: 0 6px 16px rgba(99,102,241,0.35) !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
    transform: none !important;
    box-shadow: 0 8px 20px rgba(99,102,241,0.45) !important;
}

.side-divider { height:1px; background:rgba(148,163,184,0.14); margin:16px 4px; }

.side-pills { display:flex; gap:6px; flex-wrap:wrap; margin: 0 4px 12px; }

/* User card */
.side-user {
    display:flex; align-items:center; gap:11px;
    background: rgba(148,163,184,0.10);
    border:1px solid rgba(148,163,184,0.16);
    border-radius:12px; padding:10px 12px; margin: 0 4px;
}
.side-avatar {
    width:36px; height:36px; border-radius:10px; flex-shrink:0;
    display:flex; align-items:center; justify-content:center;
    font-weight:800; font-size:15px; color:#fff;
    background: linear-gradient(135deg,#0ea5e9,#6366f1);
}
.side-user-name { font-size:13.5px; font-weight:700; color:#f1f5f9; line-height:1.2; }
.side-user-role { font-size:11px; color:#94a3b8; margin-top:2px; }
.side-stack { font-size:10.5px; color:#64748b; margin:8px 6px 12px; }

/* ===== Main page heading ===== */
.page-head {
    display:flex; align-items:center; gap:12px;
    margin: 2px 0 16px; padding-bottom:14px;
    border-bottom:1px solid var(--border);
}
.page-head-icon {
    width:40px; height:40px; border-radius:12px; flex-shrink:0;
    display:flex; align-items:center; justify-content:center; font-size:20px;
    background: linear-gradient(135deg, var(--primary), var(--primary-light));
    box-shadow: 0 6px 16px rgba(79,70,229,0.28);
}
.page-head-title { font-size:1.55rem; font-weight:800; letter-spacing:-0.03em; color:var(--text); }

/* Block container width breathing room */
.block-container { padding-top: 1.4rem !important; max-width: 1400px; }

/* Metric cards (native st.metric) polish */
[data-testid="stMetric"] {
    background: var(--surface);
    border:1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 14px 16px;
    box-shadow: var(--shadow-sm);
    transition: all 0.2s ease;
}
[data-testid="stMetric"]:hover {
    box-shadow: var(--shadow-lg);
    transform: translateY(-2px);
    border-color: var(--primary-light);
}
[data-testid="stMetricValue"] { font-weight:800 !important; color:var(--primary-dark) !important; }

/* Inputs */
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div {
    border-radius: 10px !important;
}

/* Expanders */
[data-testid="stExpander"] {
    border:1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm) !important;
    overflow:hidden;
}

/* ===== Pinned chat input bar (Assistant) â€” ChatGPT / Claude style ===== */
[data-testid="stChatInput"] {
    background: transparent !important;
    /* background: rgba(248, 250, 252, 0.85) !important; */
    backdrop-filter: none !important;
    border-top: none !important;
    padding-bottom: 10px !important;
}
[data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] { background: transparent !important; }
[data-testid="stChatInput"] > div {
    max-width: 820px !important;
    margin: 0 auto !important;
}
[data-testid="stChatInput"] textarea,
[data-testid="stChatInput"] > div > div {
    border-radius: 16px !important;
}
[data-testid="stChatInput"] textarea {
    font-size: 15px !important;
}
/* leave room so messages don't hide behind the fixed bar */
[data-testid="stAppViewBlockContainer"], .block-container { padding-bottom: 120px !important; }

/* ===== Chat panel: roomier + subtle scroll ===== */
.chat-panel { max-width: 880px; margin-left:auto; margin-right:auto; }

/* ===== Alerts (info / success / warning / error) ===== */
[data-testid="stAlert"] {
    border-radius: var(--radius-md) !important;
    border: 1px solid var(--border) !important;
    box-shadow: var(--shadow-sm) !important;
}

/* ===== Plotly / native charts as cards ===== */
[data-testid="stPlotlyChart"], [data-testid="stVegaLiteChart"], .stPlotlyChart {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 8px;
    box-shadow: var(--shadow-sm);
    margin-bottom: 8px;
}

/* ===== Dataframes ===== */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    overflow: hidden;
    box-shadow: var(--shadow-sm) !important;
}

/* ===== Download buttons ===== */
[data-testid="stDownloadButton"] > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
}

/* ===== Inner tabs (e.g. finance preview) ===== */
.stTabs [data-baseweb="tab-list"] { border-radius: var(--radius-md) !important; }

/* ===== Dividers / captions ===== */
hr { border-color: var(--border) !important; opacity: 0.7; }
[data-testid="stCaptionContainer"], .stCaption { color: var(--muted) !important; }

/* ===== File uploader dropzone ===== */
[data-testid="stFileUploaderDropzone"] {
    border-radius: var(--radius-md) !important;
    border: 1.5px dashed var(--border) !important;
    background: rgba(255,255,255,0.03) !important;
}

/* ===================================================================== */
/* DARK THEME OVERRIDES â€” custom components that used hardcoded light hues */
/* ===================================================================== */
.chat-panel {
    background: rgba(20, 29, 48, 0.6) !important;
    border-color: var(--border) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.03) !important;
}
.chat-agent {
    background: var(--surface) !important;
    color: var(--text) !important;
    border-color: var(--border) !important;
}
.thread-bar {
    background: linear-gradient(90deg, rgba(52,211,153,0.10), rgba(20,29,48,0.6)) !important;
    border-color: rgba(52,211,153,0.30) !important;
    color: #86efac !important;
}
.metric-card, .agent-status-card, .cand-card, .hist-row, .qmsg, .notif {
    background: var(--surface) !important;
    border-color: var(--border) !important;
    color: var(--text) !important;
}
.metric-card:hover, .agent-status-card:hover, .cand-card:hover {
    border-color: var(--primary) !important;
}
.resp-box {
    background: var(--surface-2) !important;
    color: var(--text) !important;
    border-color: var(--border) !important;
}
.sec-hdr {
    color: var(--text) !important;
    background: linear-gradient(90deg, rgba(99,102,241,0.10), transparent) !important;
}
.a2a-flow {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: var(--radius-md);
    padding: 12px 14px;
}
.a2a-agent { color: var(--primary-light) !important; }
.score-bar { background: var(--surface-2) !important; }
.main-header { background: rgba(2, 6, 18, 0.6) !important; }

/* Native widgets / containers on dark */
[data-testid="stMetric"] { background: var(--surface) !important; border-color: var(--border) !important; }
[data-testid="stMetricValue"] { color: var(--primary-light) !important; }
[data-testid="stExpander"] { background: var(--surface) !important; }
[data-testid="stExpander"] summary { color: var(--text) !important; }
[data-testid="stDataFrame"] { background: var(--surface) !important; }
.stTextInput input, .stTextArea textarea, [data-baseweb="select"] > div, [data-baseweb="input"] {
    background: var(--surface-2) !important;
    color: var(--text) !important;
    border-color: var(--border) !important;
}
[data-testid="stChatInput"] { background: transparent !important; }
[data-testid="stChatInput"] textarea, [data-testid="stChatInput"] > div > div {
    background: var(--surface-2) !important; color: var(--text) !important;
    border: 1px solid var(--border) !important;
    box-shadow: 0 10px 28px -6px rgba(0,0,0,0.55) !important;
}
/* secondary buttons readable on dark */
.stButton > button { background: var(--surface) !important; color: var(--text) !important; border-color: var(--border) !important; }
.stButton > button:hover { background: var(--surface-2) !important; color: #fff !important; }

</style>""", unsafe_allow_html=True)

# â”€â”€ Session defaults â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_defs = {
    "logged_in": False, "username": "", "user_role": "", "user_name": "",
    "orch_chat": [], "coord_chat": [], "docs_chat": [],
    "it_chat": [], "hr_chat": [], "fin_chat": [],
    "pending_email": None, "monitor_log": [], "monitor_import_error": "",
    "hr_results": None,
    "uploaded_cvs": [], "drive_documents": [], "mcp_running": False,
    "system_start": time.time(),
    "db_hr_cvs": [], "orch_last_proc": None,
    "recruitment_wf_id": None,
    "recruitment_last": None,
    "hr_gmail_batch_id": None,
    "hr_gmail_last": None,
    "pending_hr_gmail_batch_id": None,
    "hr_ats_candidates": [],
    "hr_ats_batch_id": None,
    "hr_ats_selected": [],
    "hr_ats_filters": {},
    "orch_finance_export_files": None,
    "auth_session_id": "",
    "orch_conversation_id": None,
    "coord_conversation_id": None,
    "docs_conversation_id": None,
    "inbox_emails": [],
    "selected_inbox_idx": None,
    "active_tab": None,
}
for k, v in _defs.items():
    if k not in st.session_state:
        st.session_state[k] = v


# â”€â”€ Per-agent quick-chat (the pinned bottom bar feeds these) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_AGENT_CHAT = {
    "Email":      ("coord_chat", "ðŸ“§", "Ask the Email agent â€” e.g. 'email Ahmed about the 3pm meeting'â€¦"),
    "Documents":  ("docs_chat",  "ðŸ“‚", "Ask anything about your loaded documentsâ€¦"),
    "IT Support": ("it_chat",    "ðŸ› ï¸", "Describe your IT problemâ€¦"),
    "HR":         ("hr_chat",    "ðŸ‘¥", "Ask the HR agent â€” policies, process, leavesâ€¦"),
    "Finance":    ("fin_chat",   "ðŸ’°", "Ask the Finance agent â€” tax, budgets, expensesâ€¦"),
}


def _agent_answer(tab: str, prompt: str, user_name: str) -> str:
    """Route a single free-text prompt to the right specialist agent."""
    if tab == "IT Support":
        from graph.it_graph import it_graph
        r = it_graph.invoke({"user_name": user_name, "it_problem": prompt})
        tid = r.get("ticket_id", "")
        sol = r.get("it_solution", "") or "No solution produced."
        return (f"**Ticket {tid}**\n\n" if tid else "") + sol
    if tab == "Finance":
        from database.vector_db import collection_stats
        if collection_stats().get("finance_docs", 0) > 0:
            from database.vector_db import rag_answer
            return rag_answer(prompt, "finance_docs", top_k=4, user_name=user_name)
        from graph.finance_graph import finance_graph
        return finance_graph.invoke(
            {"action": "query", "question": prompt, "context": "", "user_name": user_name}
        ).get("output", "")
    if tab == "HR":
        from database.vector_db import collection_stats
        if collection_stats().get("hr_policies", 0) > 0:
            from database.vector_db import rag_answer
            return rag_answer(prompt, "hr_policies", top_k=4, user_name=user_name)
        from graph.hr_graph import hr_graph
        return hr_graph.invoke(
            {"action": "hr_query", "query": prompt, "user_name": user_name}
        ).get("output", "")
    if tab == "Documents":
        from agents.documents_agent import answer_question_from_documents
        return answer_question_from_documents(prompt, st.session_state.get("drive_documents", []), user_name)
    if tab == "Email":
        import re
        from agents.auto_reply_agent import generate_reply
        from tools.email_search import find_email_by_name
        m = re.search(r"(?:email|send|message|contact|write to|notify)\s+([A-Za-z]+)", prompt, re.IGNORECASE)
        if m:
            contacts = find_email_by_name(m.group(1))
            if contacts:
                c = contacts[0]
                reply = generate_reply({"email_content": prompt, "sender_name": user_name})
                st.session_state.pending_email = {
                    "name": c["name"], "email": c["email"],
                    "subject": f"Message from {user_name}", "body": reply.get("body", prompt),
                }
                return f"ðŸ“§ Found **{c['name']}** ({c['email']}). Drafted a message â€” review & confirm below."
            return f"ðŸ” Could not find **{m.group(1)}**'s email. Provide the address directly."
        reply = generate_reply({"email_content": prompt, "sender_name": user_name})
        return reply.get("body", "")
    return "Unsupported agent."


def _render_agent_quick_chat(tab: str) -> None:
    """Render a per-agent chat history + process a pending pinned-bar prompt."""
    chat_key, icon, _ph = _AGENT_CHAT[tab]
    history = st.session_state.get(chat_key, [])
    if history:
        st.markdown('<div class="chat-panel">', unsafe_allow_html=True)
        for e in history:
            if e.get("role") == "user":
                st.markdown(
                    f'<div class="chat-wrap"><div class="chat-user">{_hesc_html(e.get("content",""))}</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="chat-wrap"><div class="chat-agent">{icon} {_hesc_html(e.get("content",""))}</div></div>',
                    unsafe_allow_html=True,
                )
        st.markdown("</div>", unsafe_allow_html=True)
        if st.button("Clear chat", key=f"clear_{chat_key}"):
            st.session_state[chat_key] = []
            st.rerun()
    pend = (st.session_state.pop(f"_pending_{tab}", "") or "").strip()
    if pend:
        st.session_state.setdefault(chat_key, [])
        st.session_state[chat_key].append({"role": "user", "content": pend})
        with st.spinner(f"{tab} agent workingâ€¦"):
            try:
                ans = _agent_answer(tab, pend, st.session_state.user_name or "User")
            except Exception as e:
                ans = f"Error: {e}"
        st.session_state[chat_key].append({"role": "agent", "content": ans})
        st.rerun()


def _new_auth_session_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _record_login_event(username: str, display_name: str, role: str, event: str) -> None:
    try:
        from database.sqlite_db import log_login_event
        log_login_event(
            username=username,
            display_name=display_name,
            role=role,
            event=event,
            session_id=st.session_state.get("auth_session_id") or "",
        )
    except Exception:
        pass


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# AUTH (login Â· sign-up Â· forgot) â€” early exit before heavy UI setup
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
if not st.session_state.logged_in:
    from ui.auth_pages import render_auth_gate

    render_auth_gate(
        new_session_id_fn=_new_auth_session_id,
        record_login_fn=_record_login_event,
    )


def _extract_text_from_uploaded_file(f) -> str:
    """Return plain text from an uploaded Streamlit file (pdf / docx / txt)."""
    import io

    try:
        f.seek(0)
    except Exception:
        pass
    name = (f.name or "").lower()
    try:
        if name.endswith(".pdf"):
            pdf_bytes = f.read()
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                    return "\n".join((p.extract_text() or "") for p in pdf.pages)
            except Exception:
                try:
                    import PyPDF2
                    reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
                    return " ".join(p.extract_text() or "" for p in reader.pages)
                except Exception:
                    return pdf_bytes.decode("utf-8", errors="ignore")
        if name.endswith(".docx"):
            try:
                import docx
                doc = docx.Document(io.BytesIO(f.read()))
                return "\n".join(p.text for p in doc.paragraphs)
            except Exception:
                return f.read().decode("utf-8", errors="ignore")
        if name.endswith((".xlsx", ".xls")):
            rawb = f.read()
            try:
                import pandas as pd
                df = pd.read_excel(io.BytesIO(rawb))
                return df.to_csv(index=False)
            except Exception:
                return rawb.decode("utf-8", errors="ignore")
        if name.endswith(".csv"):
            return f.read().decode("utf-8", errors="ignore")
        return f.read().decode("utf-8", errors="ignore")
    except Exception:
        try:
            return f.read().decode("utf-8", errors="ignore")
        except Exception:
            return ""


def _hesc_html(text: str) -> str:
    """Escape user/model text for safe HTML chat bubbles."""
    from html import escape
    return escape(str(text or "")).replace("\n", "<br>")


def _sync_orch_chat_from_db(force: bool = False) -> None:
    """Load persisted thread into Assistant UI (survives rerun / new session)."""
    cid = st.session_state.get("orch_conversation_id")
    if not cid:
        return
    active = st.session_state.get("_orch_active_cid")
    if force or active != cid:
        try:
            from database.sqlite_db import load_conversation_ui_messages
            st.session_state.orch_chat = load_conversation_ui_messages(cid)
            st.session_state["_orch_active_cid"] = cid
        except Exception:
            pass


def _sync_hr_ats_from_result(result: dict) -> None:
    """Keep last fetched candidates in session for ATS panel + follow-up commands."""
    if not result or not result.get("ok"):
        return
    drafts = result.get("drafts") or []
    if not drafts:
        return
    st.session_state.hr_ats_candidates = drafts
    st.session_state.hr_ats_batch_id = result.get("batch_id")
    st.session_state.hr_ats_filters = result.get("filters_applied") or {}
    if result.get("batch_id"):
        st.session_state.pending_hr_gmail_batch_id = result.get("batch_id")
    mem = result.get("session_memory") or {}
    if mem.get("candidates"):
        st.session_state.hr_ats_candidates = mem["candidates"]


def _render_hr_ats_candidate_panel(batch_id: str | None, key_prefix: str = "ats") -> None:
    """Professional ATS cards: select, send, shortlist, reject."""
    candidates = st.session_state.get("hr_ats_candidates") or []
    if not candidates:
        return
    bid = batch_id or st.session_state.get("hr_ats_batch_id") or ""
    filters = st.session_state.get("hr_ats_filters") or {}
    st.markdown(
        '<div class="sec-hdr sec-teal">Candidate pipeline <span class="badge badge-indigo">ATS</span></div>',
        unsafe_allow_html=True,
    )
    if filters.get("required_skills"):
        st.caption(f"Skill filter: **{', '.join(filters['required_skills'])}** Â· Min score: **{filters.get('min_score', 55)}%**")
    st.caption("Select candidates, then **Send email** per person, or use bulk actions. Emails are never sent without your action.")

    selected: list[str] = []
    for i, c in enumerate(candidates):
        cid = c.get("candidate_id") or f"c{i}"
        name = c.get("candidate_name") or "Candidate"
        score = int(c.get("match_score") or 0)
        status = c.get("status") or "â€”"
        skills = ", ".join(c.get("key_skills") or []) or "â€”"
        exp = c.get("experience_level") or "â€”"
        hr_st = c.get("hr_state") or "pending"
        status_cls = "badge-green" if status == "Recommended" else "badge-orange"
        if hr_st == "rejected":
            status_cls = "badge-red"
        st.markdown(
            f'<div class="cand-card">'
            f'<b>{_hesc_html(name)}</b> <span class="badge {status_cls}">{_hesc_html(status)}</span> '
            f'<span class="badge badge-blue">{score}% Match</span><br>'
            f'<span style="font-size:12px;color:#64748b">Skills: {_hesc_html(skills)} Â· {_hesc_html(exp)}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
        cols = st.columns([0.5, 1.2, 1, 1, 1])
        with cols[0]:
            sel = st.checkbox("Select", key=f"{key_prefix}_sel_{bid}_{cid}", value=cid in (st.session_state.hr_ats_selected or []))
            if sel:
                selected.append(cid)
        with cols[1]:
            st.caption(f"To: {c.get('recipient') or 'â€”'}")
        with cols[2]:
            if st.button("Send email", key=f"{key_prefix}_send_{bid}_{cid}", disabled=hr_st == "rejected" or not c.get("sendable")):
                if bid:
                    with st.spinner(f"Sending to {name}..."):
                        try:
                            from tools.hr_gmail_shortlist import approve_and_send_shortlist_batch
                            sr = approve_and_send_shortlist_batch(
                                bid,
                                user_message=f"send to {name}",
                                ui_selected_ids=[cid],
                            )
                            if sr.get("ok"):
                                st.success(f"Sent to **{name}**.")
                            else:
                                st.error(sr.get("error", "Send failed."))
                        except Exception as ex:
                            st.error(str(ex))
        with cols[3]:
            if st.button("Shortlist", key=f"{key_prefix}_sl_{bid}_{cid}"):
                c["hr_state"] = "shortlisted"
                st.toast(f"{name} shortlisted")
        with cols[4]:
            if st.button("Reject", key=f"{key_prefix}_rej_{bid}_{cid}"):
                c["hr_state"] = "rejected"
                st.toast(f"{name} rejected")
    st.session_state.hr_ats_selected = selected

    st.markdown("")
    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("Send to selected", key=f"{key_prefix}_bulk_sel", use_container_width=True):
            if bid and selected:
                from tools.hr_gmail_shortlist import approve_and_send_shortlist_batch
                sr = approve_and_send_shortlist_batch(bid, user_message="send to selected", ui_selected_ids=selected)
                if sr.get("ok"):
                    st.success(f"Sent **{sr.get('emails_sent', 0)}** email(s).")
                    st.session_state.pending_hr_gmail_batch_id = None
                    st.rerun()
                else:
                    st.error(sr.get("error", "Failed"))
            else:
                st.warning("Select at least one candidate.")
    with b2:
        if st.button("Email recommended", key=f"{key_prefix}_bulk_rec", use_container_width=True):
            if bid:
                from tools.hr_gmail_shortlist import approve_and_send_shortlist_batch
                sr = approve_and_send_shortlist_batch(bid, user_message="email all recommended candidates")
                if sr.get("ok"):
                    st.success(f"Sent **{sr.get('emails_sent', 0)}** to recommended.")
                    st.rerun()
                else:
                    st.error(sr.get("error", "Failed"))
    with b3:
        if st.button("Invite top 2", key=f"{key_prefix}_bulk_top2", use_container_width=True):
            if bid:
                from tools.hr_gmail_shortlist import approve_and_send_shortlist_batch
                sr = approve_and_send_shortlist_batch(bid, user_message="invite top 2 candidates")
                if sr.get("ok"):
                    st.success(f"Sent **{sr.get('emails_sent', 0)}**.")
                    st.rerun()
                else:
                    st.error(sr.get("error", "Failed"))
    with b4:
        if st.button("Email all (explicit)", key=f"{key_prefix}_bulk_all", use_container_width=True):
            st.caption("Sends every sendable candidate in this batch.")
            if bid:
                from tools.hr_gmail_shortlist import approve_and_send_shortlist_batch
                sr = approve_and_send_shortlist_batch(bid, user_message="email all candidates send to everyone")
                if sr.get("ok"):
                    st.success(f"Sent **{sr.get('emails_sent', 0)}**.")
                    st.session_state.pending_hr_gmail_batch_id = None
                    st.rerun()
                else:
                    st.error(sr.get("error", "Failed"))


def _render_assistant_ui_payload(ui: dict | None, key_prefix: str = "aui") -> None:
    """Structured results (candidates, inbox rows) â€” not raw markdown dumps."""
    if not ui or not isinstance(ui, dict):
        return
    t = ui.get("type") or ""
    if t == "hr_shortlist":
        bid = ui.get("batch_id")
        if bid:
            st.session_state.pending_hr_gmail_batch_id = bid
            st.session_state.hr_ats_batch_id = bid
        st.session_state.hr_ats_candidates = ui.get("candidates") or []
        st.session_state.hr_ats_filters = ui.get("stats") or {}
        stats = ui.get("stats") or {}
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Shortlisted", len(ui.get("candidates") or []))
        c2.metric("Emails scanned", stats.get("emails_scanned", "â€”"))
        c3.metric("CVs parsed", stats.get("attachments_parsed", "â€”"))
        skills = stats.get("required_skills") or []
        c4.metric("Skill filter", ", ".join(skills) if skills else "â€”")
        send_result = ui.get("send_result") or {}
        if send_result.get("ok"):
            st.success(
                f"Sent {send_result.get('emails_sent', 0)} invitation(s) via Gmail."
            )
        _render_hr_ats_candidate_panel(bid, key_prefix=key_prefix)
    elif t == "hr_inventory":
        st.markdown(
            '<div class="sec-hdr sec-blue" style="margin-top:12px">CV inventory</div>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        c1.metric("CV attachments scanned", ui.get("total_cvs", 0))
        c2.metric("Matching filter", ui.get("matched_cvs", 0))
        skills = ui.get("skills") or []
        if skills:
            st.caption(f"Skills: {', '.join(skills)}")
        if ui.get("message"):
            st.info(ui.get("message"))
    elif t == "email_list":
        st.markdown(
            '<div class="sec-hdr sec-blue" style="margin-top:12px">Inbox results</div>',
            unsafe_allow_html=True,
        )
        for i, em in enumerate(ui.get("emails") or []):
            cls = em.get("classification") or ""
            badge = f'<span class="badge badge-indigo">{_hesc_html(cls)}</span> ' if cls else ""
            st.markdown(
                f'<div class="cand-card" style="margin-bottom:8px">'
                f"<b>{_hesc_html(em.get('from_name', ''))}</b> "
                f"<span style='font-size:12px;color:#64748b'>&lt;{_hesc_html(em.get('from_email', ''))}&gt;</span><br>"
                f"<span style='font-size:13px'>{_hesc_html(em.get('subject', ''))}</span> "
                f"{badge}"
                f"<span style='font-size:11px;color:#94a3b8'> Â· {_hesc_html(em.get('date', ''))}</span>"
                f"<br><span style='font-size:12px;color:#475569'>{_hesc_html(em.get('snippet', ''))}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if int(em.get("attachment_count") or 0) > 0:
                st.caption(f"Attachments: {em.get('attachment_count', 0)}")
    elif t == "email_send":
        if ui.get("ok"):
            st.success(ui.get("message") or "Emails sent.")
        else:
            st.warning(ui.get("message") or "Send could not be completed.")
    elif t == "hr_error":
        st.error(ui.get("message") or "Request failed.")


def _start_new_orch_conversation() -> None:
    from database.sqlite_db import create_new_conversation
    cid = create_new_conversation(
        st.session_state.get("auth_session_id") or "",
        st.session_state.username,
        "orchestrator",
    )
    if cid:
        st.session_state.orch_conversation_id = cid
        st.session_state.orch_chat = []
        st.session_state.orch_last_proc = None
        st.session_state["_orch_active_cid"] = cid
        st.session_state.pending_hr_gmail_batch_id = None


def _render_inbox_email_detail(em: dict) -> None:
    from html import escape as _esc
    import base64

    fn = _esc(em.get("from_name", "") or "")
    fe = _esc(em.get("from_email", "") or "")
    subj = _esc(em.get("subject", "") or "")
    date_s = _esc(em.get("date", "") or "")
    body = _esc(em.get("body", "") or "(No body)")

    header_html = (
        '<div class="email-detail-box">'
        + f"<h4 style='margin:0 0 12px 0;color:#0f172a'>{subj}</h4>"
        + f"<p style='margin:0 0 6px 0;font-size:13px;color:#64748b'>"
        + f"<b>From:</b> {fn} &lt;{fe}&gt;<br><b>Date:</b> {date_s}</p>"
        + "</div>"
    )
    st.markdown(header_html, unsafe_allow_html=True)
    st.markdown('<div class="email-body-full">' + body + "</div>",
        unsafe_allow_html=True,
    )

    attachments = em.get("attachments") or []
    if attachments:
        st.markdown("**Attachments**")
        cols = st.columns(min(3, len(attachments)))
        for i, att in enumerate(attachments):
            with cols[i % len(cols)]:
                try:
                    data = base64.b64decode(att.get("data_b64") or "")
                except Exception:
                    data = b""
                size_kb = (att.get("size") or len(data)) / 1024.0
                st.download_button(
                    label="Download " + str(att.get("filename", "file")),
                    data=data,
                    file_name=att.get("filename") or "attachment",
                    mime=att.get("content_type") or "application/octet-stream",
                    key=f"inbox_att_{em.get('uid', i)}_{i}",
                    use_container_width=True,
                )
                st.caption(f"{size_kb:.1f} KB")
    else:
        st.caption("No attachments in this message.")

# â”€â”€ DB init â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    from database.sqlite_db import init_db
    init_db()
except Exception:
    pass

# â”€â”€ MCP auto-start (local only; skip on Streamlit Cloud â€” set FYP_HOSTED=true in Secrets) â”€
if is_hosted_deploy():
    st.session_state.mcp_running = False
else:
    try:
        from mcp_server import start_mcp_server, is_mcp_running
        from config import MCP_SERVER_HOST, MCP_SERVER_PORT

        if not is_mcp_running():
            start_mcp_server(MCP_SERVER_HOST, MCP_SERVER_PORT)
        st.session_state.mcp_running = True
    except Exception:
        st.session_state.mcp_running = False

# â”€â”€ Monitor logs (skip heavy IMAP stack on hosted â€” not usable headless anyway) â”€
if is_hosted_deploy():

    def get_pending_logs():
        return []

    def is_running():
        return False

    def start_monitor():
        return False, "Not available on hosted deploy."

    def stop_monitor():
        pass

else:
    try:
        from tools.gmail_auto_reply_monitor import get_pending_logs, is_running, start_monitor, stop_monitor

        st.session_state.monitor_import_error = ""
    except Exception as _mon_ex:
        st.session_state.monitor_import_error = str(_mon_ex)

        def get_pending_logs():
            return []

        def is_running():
            return False

        def start_monitor():
            return False, "Monitor module failed to load."

        def stop_monitor():
            pass


def _service_status_pill(label: str, state: str) -> str:
    """HTML status pill for header/dashboard. state: on | off | cloud."""
    from html import escape as _esc

    lbl = _esc(label)
    if state == "on":
        text, cls, tip = "On", "svc-on", f"{label} is running (local deploy)."
    elif state == "cloud":
        text, cls, tip = "Off", "svc-cloud", f"{label} is not available in this environment."
    else:
        text, cls, tip = "Off", "svc-off", f"{label} is stopped."
    return (
        f'{lbl}: <span class="svc-pill {cls}" title="{_esc(tip)}">{text}</span>'
    )


def _mcp_header_state() -> str:
    if not local_background_services_enabled():
        return "cloud"
    return "on" if st.session_state.mcp_running else "off"


def _monitor_header_state() -> str:
    if not local_background_services_enabled():
        return "cloud"
    return "on" if is_running() else "off"


def _cached_dashboard_stats():
    # Counts are cheap and must reflect the latest tasks immediately (no cache),
    # otherwise the "X calls" agent cards lag behind the live A2A queue.
    from database.sqlite_db import get_dashboard_stats
    return get_dashboard_stats()


@st.cache_data(ttl=20, show_spinner=False)
def _cached_vector_stats():
    from database.vector_db import collection_stats
    return collection_stats()


def _drain_monitor_logs() -> None:
    """Pull background monitor log lines into session state (main thread only)."""
    try:
        for lg in get_pending_logs():
            st.session_state.monitor_log.append(lg)
    except Exception:
        pass


def _render_email_auto_monitor_panel(*, key_prefix: str = "mon"):
    """Gmail IMAP auto-reply â€” Email and IT tabs (local + Gmail configured)."""
    if not can_use_email_monitor(st.session_state.user_role or ""):
        return
    st.markdown('<div class="sec-hdr sec-orange">ðŸ“¬ Email auto-reply monitor</div>', unsafe_allow_html=True)
    _hosted = not local_background_services_enabled()
    _gmail_ok = is_gmail_configured()
    if st.session_state.get("monitor_import_error"):
        st.error(f"Monitor unavailable: {st.session_state.monitor_import_error}")
    if _hosted:
        st.info("Auto-reply monitor runs on **local** installs only (not Streamlit Cloud).")
    elif not _gmail_ok:
        st.warning(gmail_setup_hint())

    toggle_key = f"{key_prefix}_auto_reply_on"
    if toggle_key not in st.session_state:
        st.session_state[toggle_key] = is_running()

    want_on = st.toggle(
        "Auto-reply monitor",
        key=toggle_key,
        disabled=_hosted or not _gmail_ok,
        help="ON â€” automatically reply to new inbox emails every 30s. OFF â€” no auto-replies.",
    )

    running = is_running()
    if not _hosted and _gmail_ok and want_on != running:
        if want_on:
            ok, msg = start_monitor()
            st.session_state.monitor_log.append(msg)
            if ok:
                st.session_state[toggle_key] = True
                st.success(msg)
            else:
                st.session_state[toggle_key] = False
                st.error(msg)
        else:
            stop_monitor()
            st.session_state[toggle_key] = False
            st.session_state.monitor_log.append("Auto-reply monitor stopped.")
        st.rerun()

    if is_running():
        st.markdown(
            '<div style="background:#dcfce7;border:1px solid #16a34a;padding:8px 14px;'
            'border-radius:8px;margin:8px 0">ðŸŸ¢ <b>Auto-reply ON</b> â€” checking inbox every 30s</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="background:var(--surface-2);border:1px solid var(--border);padding:8px 14px;'
            'border-radius:8px;margin:8px 0">âšª <b>Auto-reply OFF</b></div>',
            unsafe_allow_html=True,
        )

    _drain_monitor_logs()
    if st.session_state.monitor_log:
        with st.expander("ðŸ“‹ Activity log", expanded=False):
            for log in reversed(st.session_state.monitor_log[-25:]):
                st.caption(log)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MAIN APP (after login)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

if st.session_state.logged_in:
    try:
        from database.sqlite_db import get_or_create_conversation, touch_user_session

        touch_user_session(
            st.session_state.auth_session_id,
            st.session_state.username,
            st.session_state.user_name,
            st.session_state.user_role,
        )
        if not st.session_state.get("orch_conversation_id"):
            st.session_state.orch_conversation_id = get_or_create_conversation(
                st.session_state.auth_session_id,
                st.session_state.username,
                "orchestrator",
            )
        _sync_orch_chat_from_db(force=True)
    except Exception:
        pass

# â”€â”€ Sidebar navigation (RBAC: visible items depend on role) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from html import escape as _hesc

tab_labels = get_visible_tabs_for_role(st.session_state.user_role)

# Keep the active tab valid for the current role; default to the first item.
if st.session_state.get("active_tab") not in tab_labels:
    st.session_state.active_tab = tab_labels[0] if tab_labels else None

_NAV_ICONS = {
    "Assistant": "💬",
    "Dashboard": "📊",
    "IT Support": "🛠️",
    "Email": "✉️",
    "HR": "👥",
    "Finance": "💰",
    "Documents": "📄",
    "History": "🕑",
}

with st.sidebar:
    _db_label = "PostgreSQL" if use_postgresql_database() else "SQLite"
    st.markdown(
        '<div class="side-brand">'
        '<div class="side-logo">🤖</div>'
        '<div class="side-brand-text">'
        '<div class="side-title">Office Automation</div>'
        '<div class="side-sub">Multi-Agent · A2A · MCP</div>'
        "</div></div>",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="side-nav-label">KIET Workspace</div>', unsafe_allow_html=True)
    for _lbl in tab_labels:
        _icon = _NAV_ICONS.get(_lbl, "•")
        _is_active = st.session_state.active_tab == _lbl
        if st.button(
            f"{_icon}  {_lbl}",
            key=f"nav_{_lbl}",
            use_container_width=True,
            type="primary" if _is_active else "secondary",
        ):
            st.session_state.active_tab = _lbl
            st.rerun()

    st.markdown('<div class="side-divider"></div>', unsafe_allow_html=True)

    # Service status (only for roles that manage background services)
    _role = st.session_state.user_role or ""
    if can_manage_background_services(_role):
        mcp_pill = _service_status_pill("MCP", _mcp_header_state())
        mon_pill = _service_status_pill("Monitor", _monitor_header_state())
        st.markdown(
            f'<div class="side-pills">{mcp_pill} {mon_pill}</div>',
            unsafe_allow_html=True,
        )

    # User card
    _unm = _hesc(st.session_state.user_name or "")
    _rol = _hesc(st.session_state.user_role or "")
    _initial = (_unm[:1] or "U").upper()
    st.markdown(
        f'<div class="side-user">'
        f'<div class="side-avatar">{_initial}</div>'
        f'<div class="side-user-text"><div class="side-user-name">{_unm}</div>'
        f'<div class="side-user-role">{_rol}</div></div>'
        f"</div>"
        f'<div class="side-stack">Stack · SQLite · LangGraph Â· OpenAI</div>',
        unsafe_allow_html=True,
    )

    if st.button("Sign out", key="side_logout", use_container_width=True):
        _record_login_event(
            username=st.session_state.username,
            display_name=st.session_state.user_name,
            role=st.session_state.user_role,
            event="logout",
        )
        try:
            from database.sqlite_db import deactivate_user_session

            deactivate_user_session(st.session_state.auth_session_id or "")
        except Exception:
            pass
        for k in ("username", "user_role", "user_name", "auth_session_id"):
            st.session_state[k] = ""
        st.session_state.logged_in = False
        st.session_state.auth_screen = "login"
        st.session_state.signup_step = 1
        st.session_state.forgot_step = 1
        for k in ("orch_conversation_id", "coord_conversation_id", "docs_conversation_id"):
            st.session_state[k] = None
        st.session_state.orch_chat = []
        st.session_state.active_tab = None
        st.rerun()

# â”€â”€ Main content area â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
active_tab = st.session_state.active_tab
_MAIN = st.container()

with _MAIN:
    # Page heading + role banner
    _icon = _NAV_ICONS.get(active_tab, "•")
    st.markdown(
        f'<div class="page-head"><span class="page-head-icon">{_icon}</span>'
        f'<span class="page-head-title">{_hesc(active_tab or "")}</span></div>',
        unsafe_allow_html=True,
    )
    _pb = ROLE_PORTAL_BANNERS.get(st.session_state.user_role)
    if _pb:
        st.markdown(_pb, unsafe_allow_html=True)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 2 â€” DASHBOARD
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
if active_tab == "Dashboard":
    with _MAIN:
        try:
            from database.sqlite_db import get_notifications
            stats = _cached_dashboard_stats()
            notifs = get_notifications(unread_only=True)
        except Exception:
            stats = {"total_tasks":0,"total_emails":0,"total_candidates":0,"total_it_tickets":0,
                     "total_finance":0,"unread_notifs":0,"recent_tasks":[],
                     "agent_usage":{}}
            notifs = []

        try:
            vdb = _cached_vector_stats()
            total_vecs = sum(vdb.values()) if isinstance(vdb, dict) and "error" not in vdb else 0
        except Exception:
            vdb, total_vecs = {}, 0

        # Metrics row
        m = st.columns(5)
        labels = ["Tasks", "Emails", "Candidates", "IT tickets", "Vector rows"]
        vals = [
            stats.get("total_tasks", 0),
            stats.get("total_emails", 0),
            stats.get("total_candidates", 0),
            stats.get("total_it_tickets", 0),
            total_vecs,
        ]
        for col, lab, val in zip(m, labels, vals):
            with col:
                st.metric(lab, val)

        st.markdown("")
        c1, c2, c3 = st.columns([1.2, 1.2, 1])

        with c1:
            st.markdown('<div class="sec-hdr sec-blue">Agent status</div>', unsafe_allow_html=True)
            agents = [
                ("IT Support Agent", "agent-it-001"),
                ("Email Agent", "agent-email-001"),
                ("HR Agent", "agent-hr-001"),
                ("Recruitment Orchestrator", "agent-recruitment-001"),
                ("Finance Agent", "agent-finance-001"),
                ("Documents Agent", "agent-docs-001"),
                ("Auto-Reply", "agent-autoreply-001"),
            ]
            for name, aid in agents:
                usage = stats.get("agent_usage", {}).get(name, 0)
                st.markdown(
                    f'<div class="agent-status-card" style="margin-bottom:6px">'
                    f'<div class="agent-dot"></div>'
                    f'<div style="flex:1"><b style="font-size:13px">{name}</b><br>'
                    f'<span style="font-size:11px;color:#64748b">{aid}</span></div>'
                    f'<span class="badge badge-green">{usage} calls</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )

        with c2:
            st.markdown('<div class="sec-hdr">A2A message queue</div>', unsafe_allow_html=True)
            try:
                from message_queue import message_queue
                msgs = message_queue.get_all_messages_for_display(limit=8)
                if msgs:
                    for msg in msgs:
                        tc = {"task":"qmsg-task","result":"qmsg-result","status":"qmsg-status","broadcast":"qmsg-broadcast"}.get(msg["topic"],"qmsg")
                        from html import escape as _he
                        pv = _he(str(msg.get("preview", ""))[:90])
                        st.markdown(
                            f'<div class="qmsg {tc}">'
                            f"<b>{msg['time']}</b> [{msg['topic'].upper()}] "
                            f"<b>{msg['sender']}</b> to <b>{msg['receiver']}</b><br>"
                            f'<span style="color:#64748b">{pv}</span>'
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.caption("No messages yet. Use the **Assistant** tab.")
            except Exception as e:
                st.caption(f"Queue: {e}")

            st.markdown('<div class="sec-hdr">ChromaDB collections</div>', unsafe_allow_html=True)
            if vdb and "error" not in vdb:
                mx = max(vdb.values()) if vdb.values() else 1
                for cname, cnt in vdb.items():
                    pct = min(100, int(100 * cnt / mx)) if mx else 0
                    st.markdown(
                        f'<div style="margin-bottom:6px">'
                        f'<div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:2px">'
                        f"<b>{cname}</b><span>{cnt} vectors</span></div>"
                        f'<div style="background:rgba(148,163,184,0.18);border-radius:4px;height:6px">'
                        f'<div style="background:#7c3aed;width:{pct}%;height:6px;border-radius:4px"></div></div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("No collections yet. Load documents or run data loader.")

        with c3:
            st.markdown('<div class="sec-hdr sec-purple">Notifications</div>', unsafe_allow_html=True)
            if notifs:
                for n in notifs[:6]:
                    cls = {"info":"notif-info","success":"notif-success","warning":"notif-warning","error":"notif-error"}.get(n.get("level","info"),"notif-info")
                    from html import escape as _esc
                    nt = _esc(n.get("title", "") or "")
                    tm = _esc(n.get("time", "") or "")
                    ag = _esc(n.get("agent", "") or "")
                    st.markdown(
                        f'<div class="notif {cls}">'
                        f"<b>{nt}</b><br>"
                        f'<span style="font-size:11px;color:#64748b">{tm} | {ag}</span>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                if st.button("Mark all read", key="mark_read"):
                    from database.sqlite_db import mark_notifications_read
                    mark_notifications_read(); st.rerun()
            else:
                st.success("No unread notifications")

            st.markdown('<div class="sec-hdr" style="margin-top:12px">System info</div>', unsafe_allow_html=True)
            uptime = int(time.time() - st.session_state.system_start)
            try:
                from config import MCP_SERVER_PORT as _mcp_port
                _port_disp = int(_mcp_port)
            except Exception:
                _port_disp = 8765
            _dash_svc = can_manage_background_services(st.session_state.user_role or "")
            if _dash_svc:
                mcp_st = f"Running :{_port_disp}" if st.session_state.mcp_running else "Stopped"
                mon_st = "Active" if is_running() else "Stopped"
            else:
                mcp_st = mon_st = "â€”"
            vdb_st = "ChromaDB (has rows)" if total_vecs > 0 else "ChromaDB (empty)"
            from html import escape as _escu
            un = _escu(st.session_state.user_name or "")
            st.markdown(
                f'<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 16px;font-size:13px;color:var(--text)">'
                f"<b>Uptime:</b> {uptime}s<br>"
                f"<b>DB:</b> {'PostgreSQL' if use_postgresql_database() else 'SQLite'} connected<br>"
                f"<b>VectorDB:</b> {vdb_st}<br>"
                + (f"<b>MCP:</b> {mcp_st}<br><b>Monitor:</b> {mon_st}<br>" if _dash_svc else "")
                + f"<b>User:</b> {un}"
                f"</div>",
                unsafe_allow_html=True,
            )

            st.markdown('<div class="sec-hdr sec-green" style="margin-top:12px">Data loader</div>', unsafe_allow_html=True)
            if st.button("Load all datasets into ChromaDB", use_container_width=True, key="load_datasets"):
                with st.spinner("Embedding all datasets..."):
                    try:
                        from data_loader.loader import load_all_datasets
                        load_all_datasets()
                        st.success("All datasets embedded.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

        try:
            from data_loader.loader import DATA_DIR
            _dd = DATA_DIR
            if os.path.isdir(_dd):
                _files = sorted([f for f in os.listdir(_dd) if os.path.isfile(os.path.join(_dd, f))])
            else:
                _files = []
        except Exception:
            _dd, _files = "", []

        st.markdown('<div class="sec-hdr" style="margin-top:8px">Local dataset files (on this computer)</div>', unsafe_allow_html=True)
        st.caption(f"Folder: `{_dd}`" if _dd else "Data folder not configured.")
        if _files:
            for fn in _files[:20]:
                fp = os.path.join(_dd, fn)
                try:
                    sz = os.path.getsize(fp)
                    st.text(f"{fn}  ({sz // 1024} KB)")
                except Exception:
                    st.text(fn)
            if len(_files) > 20:
                st.caption(f"... and {len(_files) - 20} more files")
        else:
            st.caption("No files in the data folder yet. Run the data loader above to generate sample datasets.")

        # A2A Architecture
        st.markdown('<div class="sec-hdr" style="margin-top:4px">Live A2A flow</div>', unsafe_allow_html=True)
        try:
            from message_queue import message_queue
            all_msgs = message_queue.get_all_messages_for_display(limit=6)
            flow_lines = []
            for msg in reversed(all_msgs):
                topic_color = {"task":"#fbbf24","result":"#22c55e","status":"#60a5fa","broadcast":"#a78bfa"}.get(msg["topic"],"#e2e8f0")
                flow_lines.append(
                    f'<span class="a2a-agent">{msg["sender"]}</span> '
                    f'<span class="a2a-arrow">--[<span style="color:{topic_color}">{msg["topic"]}</span>]-- to </span> '
                    f'<span class="a2a-agent">{msg["receiver"]}</span> '
                    f'<span style="color:#64748b;font-size:11px">({msg["time"]})</span>'
                )
            flow_html = "<br>".join(flow_lines) if flow_lines else '<span style="color:#64748b">No messages yet. Send a task via **Assistant** to see A2A flow.</span>'
            st.markdown(f'<div class="a2a-flow">{flow_html}</div>', unsafe_allow_html=True)
        except Exception:
            pass

        if st.button("Refresh dashboard", key="dash_refresh"):
            try:
                _cached_dashboard_stats.clear()
            except Exception:
                pass
            _cached_vector_stats.clear()
            st.rerun()

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 1 â€” ASSISTANT (single entry â†’ orchestrator â†’ sub-agents)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
if active_tab == "Assistant":
    with _MAIN:
        st.markdown(
            '<div class="sec-hdr sec-blue">Unified Assistant <span class="badge badge-a2a">Orchestrator</span> '
            '<span class="badge badge-mcp">MCP</span></div>',
            unsafe_allow_html=True,
        )
        try:
            from config import is_openai_configured, openai_missing_message

            if not is_openai_configured():
                st.error(openai_missing_message("AI features (Assistant, Finance, email auto-reply)"))
        except Exception:
            pass
        _allow = get_role_orchestrator_allowlist(st.session_state.user_role)
        if _allow is None:
            st.info(
                "**One assistant for everything** â€” IT, finance, documents, and **HR hiring** in plain language. "
                "Examples: *Fetch the latest 10 candidate emails*, *fetch 20 and select two for python*, "
                "*Show emails received on 15 May 2026*, *Send interview invitations for Monday at 3 PM*. "
                "Ask *What can you do?* in chat for the full task list from the orchestrator. "
                "Results appear as cards below your message (not raw reports)."
            )
        else:
            st.warning(
                "**Department-scoped (RBAC).** Allowed: "
                f"**{', '.join(_allow)}** + general chat. "
                "HR hiring runs here when your role includes Gmail shortlist (fetch, rank, invite, follow-up)."
            )

        _sync_orch_chat_from_db()
        tc1, tc2, tc3 = st.columns([2, 1, 1])
        with tc1:
            try:
                from database.sqlite_db import list_user_conversations, get_conversation_for_user

                threads = list_user_conversations(st.session_state.username, "orchestrator", limit=20)
                thread_opts = {0: "â€” Open a saved thread â€”"}
                for t in threads:
                    label = f"#{t['id']} Â· {t['updated_at']} Â· {t['message_count']} msgs"
                    if t.get("preview"):
                        label += f" â€” {t['preview'][:50]}"
                    thread_opts[t["id"]] = label
                pick = st.selectbox(
                    "Saved conversations",
                    options=list(thread_opts.keys()),
                    format_func=lambda x: thread_opts.get(x, str(x)),
                    key="orch_thread_pick",
                    label_visibility="collapsed",
                )
            except Exception:
                pick = 0
        with tc2:
            if st.button("Load thread", use_container_width=True, key="orch_load_thread"):
                if pick and pick != 0:
                    try:
                        from database.sqlite_db import get_conversation_for_user
                        if get_conversation_for_user(pick, st.session_state.username):
                            st.session_state.orch_conversation_id = pick
                            st.session_state.orch_chat = []
                            st.session_state.orch_last_proc = None
                            _sync_orch_chat_from_db(force=True)
                            st.rerun()
                    except Exception:
                        pass
        with tc3:
            if st.button("New chat", use_container_width=True, key="orch_new_chat"):
                _start_new_orch_conversation()
                st.rerun()
        n_msgs = len(st.session_state.orch_chat or [])
        st.markdown(
            f'<div class="thread-bar">'
            f'Active thread <b>#{st.session_state.get("orch_conversation_id") or "—"}</b> · '
            f'{n_msgs} messages · persisted across sessions</div>',
            unsafe_allow_html=True,
        )

        with st.expander("➕ Attachments & options", expanded=False):
            orch_up = st.file_uploader(
                "Attach files (optional, PDF / TXT / DOCX)",
                accept_multiple_files=True,
                type=["pdf", "txt", "docx"],
                key="orch_files",
            )
            st.checkbox(
                "Use LLM for intent routing",
                value=st.session_state.get("orch_use_llm", True),
                key="orch_use_llm",
                help="When on, the orchestrator uses the LLM to understand and route your request.",
            )
        orch_attachments = []
        if orch_up:
            for f in orch_up:
                txt = _extract_text_from_uploaded_file(f)
                if txt.strip():
                    orch_attachments.append({"name": f.name, "content": txt})

        st.markdown('<div class="chat-panel">', unsafe_allow_html=True)
        if not st.session_state.orch_chat:
            st.caption("Start a conversation â€” messages are saved automatically and reload when you return or open a saved thread.")
        for idx, entry in enumerate(st.session_state.orch_chat):
            if entry["role"] == "user":
                body = _hesc_html(entry.get("content", ""))
                st.markdown(f'<div class="chat-wrap"><div class="chat-user">{body}</div></div>', unsafe_allow_html=True)
            else:
                from tools.assistant_display import build_display_text

                display = entry.get("display_content") or build_display_text(
                    entry.get("content", ""),
                    entry.get("ui_payload"),
                )
                body = _hesc_html(display)
                badges = " ".join(
                    f'<span class="badge badge-indigo">{_hesc_html(a)}</span>'
                    for a in entry.get("agents", [])
                )
                ms = entry.get("elapsed_ms", 0)
                st.markdown(
                    f'<div class="chat-wrap"><div class="chat-agent">{badges} '
                    f'<small style="color:#94a3b8">({ms} ms)</small><br><br>{body}</div></div>',
                    unsafe_allow_html=True,
                )
                ui = entry.get("ui_payload")
                if ui:
                    _render_assistant_ui_payload(ui, key_prefix=f"orch_{idx}")
        st.markdown("</div>", unsafe_allow_html=True)

        _orch_fe = st.session_state.get("orch_finance_export_files")
        if _orch_fe:
            st.divider()
            with st.expander("Finance document downloads (parallel export)", expanded=True):
                st.caption("Binary files from the last routed **Finance** document request. Formats were built in parallel.")
                ncols = min(3, max(1, len(_orch_fe)))
                cols = st.columns(ncols)
                for i, fe in enumerate(_orch_fe):
                    with cols[i % ncols]:
                        st.download_button(
                            label=f"â¬‡ {(fe.get('format') or 'file').upper()}",
                            data=fe.get("data") or b"",
                            file_name=fe.get("filename") or "export.bin",
                            mime=fe.get("mime_type") or "application/octet-stream",
                            key=f"orch_fin_dl_{i}",
                        )
                        st.caption(fe.get("filename", ""))

        # The input is the chat bar pinned to the bottom of the page (rendered
        # outside the main container, at the end of the script). It stores the
        # submitted text in session_state, which we pick up here.
        use_llm = st.session_state.get("orch_use_llm", True)
        inp = (st.session_state.pop("_pending_orch_prompt", "") or "")

        if inp.strip():
            dedupe = (inp.strip(), tuple((a["name"], len(a.get("content", ""))) for a in orch_attachments))
            if st.session_state.orch_last_proc == dedupe:
                st.caption("Same request was just processed; change the message or attachments to send again.")
            else:
                orch_hist: list = []
                if st.session_state.get("orch_conversation_id"):
                    try:
                        from database.sqlite_db import load_conversation_openai_history

                        orch_hist = load_conversation_openai_history(
                            st.session_state.orch_conversation_id, limit=16
                        )
                    except Exception:
                        pass
                if not orch_hist:
                    for e in st.session_state.orch_chat[-14:]:
                        if e.get("role") == "user":
                            orch_hist.append({"role": "user", "content": e.get("content", "")})
                        elif e.get("role") == "agent":
                            orch_hist.append({"role": "assistant", "content": e.get("content", "")})
                st.session_state.orch_chat.append({"role": "user", "content": inp.strip()})
                try:
                    from database.sqlite_db import append_conversation_message

                    append_conversation_message(
                        st.session_state.get("orch_conversation_id"),
                        "user",
                        inp.strip(),
                    )
                except Exception:
                    pass
                with st.spinner("Routing and running agents (parallel)..."):
                    try:
                        from Orchestrator.orchestrator_brain import orchestrator

                        result = orchestrator.route(
                            inp.strip(),
                            st.session_state.user_name,
                            use_llm_intent=use_llm,
                            attachments=orch_attachments or None,
                            allowed_agents=get_role_orchestrator_allowlist(st.session_state.user_role),
                            conversation_history=orch_hist,
                            user_role=st.session_state.user_role or "",
                        )
                        st.session_state.orch_last_proc = dedupe
                        if result.get("hr_gmail_pending_cleared"):
                            st.session_state.pending_hr_gmail_batch_id = None
                        elif result.get("hr_gmail_batch_id"):
                            st.session_state.pending_hr_gmail_batch_id = result["hr_gmail_batch_id"]
                        st.session_state.orch_finance_export_files = result.get("finance_export_files")
                        if "hr_gmail" in (result.get("agents_used") or []):
                            try:
                                from database.sqlite_db import hr_shortlist_get_batch
                                bid = result.get("hr_gmail_batch_id")
                                if bid:
                                    row = hr_shortlist_get_batch(bid)
                                    if row:
                                        payload = row.get("payload") or {}
                                        st.session_state.hr_ats_candidates = payload.get("top") or []
                                        st.session_state.hr_ats_batch_id = bid
                                        st.session_state.hr_ats_filters = (payload.get("session_memory") or {}).get("filters_applied") or {}
                            except Exception:
                                pass
                        from tools.assistant_display import prepare_assistant_chat_entry

                        chat_entry = prepare_assistant_chat_entry(result)
                        st.session_state.orch_chat.append(chat_entry)
                        try:
                            from database.sqlite_db import append_conversation_message

                            append_conversation_message(
                                st.session_state.get("orch_conversation_id"),
                                "agent",
                                result["final_answer"],
                                agents_used=", ".join(result.get("agents_used") or []),
                                metadata={
                                    "agents_used": result.get("agents_used"),
                                    "elapsed_ms": result.get("elapsed_ms"),
                                    "ui_payload": result.get("ui_payload"),
                                    "display_content": chat_entry.get("display_content"),
                                },
                            )
                        except Exception:
                            pass
                        try:
                            from database.sqlite_db import log_task, add_notification

                            log_task(
                                st.session_state.user_name,
                                st.session_state.user_role,
                                inp.strip(),
                                result["agents_used"],
                                result["final_answer"],
                                result["elapsed_ms"],
                            )
                            add_notification(
                                "Task completed",
                                f"Agents: {', '.join(result['agents_used']) if result.get('agents_used') else 'general'}",
                                "success",
                                "Orchestrator",
                            )
                        except Exception:
                            pass
                        st.rerun()
                    except Exception as e:
                        if st.session_state.orch_chat and st.session_state.orch_chat[-1].get("role") == "user":
                            st.session_state.orch_chat.pop()
                        st.error(f"Orchestrator error: {e}")

        with st.expander("Message queue (live)"):
            try:
                from message_queue import message_queue

                for msg in message_queue.get_all_messages_for_display(limit=15):
                    tc = {"task": "qmsg-task", "result": "qmsg-result", "status": "qmsg-status", "broadcast": "qmsg-broadcast"}.get(msg["topic"], "qmsg")
                    st.markdown(
                        f'<div class="qmsg {tc}"><b>{msg["time"]}</b> [{msg["topic"].upper()}] <b>{msg["sender"]}</b> to <b>{msg["receiver"]}</b> <span style="color:#64748b">{msg["preview"][:100]}</span></div>',
                        unsafe_allow_html=True,
                    )
            except Exception:
                st.caption("Queue unavailable")

        _pbid = st.session_state.get("pending_hr_gmail_batch_id") or st.session_state.get("hr_ats_batch_id")
        if (
            _pbid
            and st.session_state.user_role in ("Admin", "HR Manager", "Assistant", "Demo User")
            and st.session_state.get("hr_ats_candidates")
            and not any((e.get("ui_payload") or {}).get("type") == "hr_shortlist" for e in st.session_state.orch_chat if e.get("role") == "agent")
        ):
            st.divider()
            st.caption("Active shortlist â€” use chat to send invites or the actions below.")
            _render_hr_ats_candidate_panel(_pbid, key_prefix="asst_sticky")
            if st.button("Dismiss shortlist panel", key="asst_hitl_clear"):
                st.session_state.pending_hr_gmail_batch_id = None
                st.session_state.hr_ats_candidates = []
                st.rerun()

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB â€” IT SUPPORT
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
if active_tab == "IT Support":
    with _MAIN:
        _render_agent_quick_chat("IT Support")
        st.caption(
            "Tip: for most tasks, use **Assistant** â€” the orchestrator routes to IT (and other agents) automatically."
        )
        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="sec-hdr sec-blue">ðŸ’» IT Support Agent</div>', unsafe_allow_html=True)
            it_name = st.text_input("Your Name", value=st.session_state.user_name, key="it_name")
            it_prob = st.text_area("Describe Your IT Problem", placeholder="e.g. WiFi not connecting, laptop freezes, can't login...", height=160)
            pri_col, btn_col = st.columns([1,2])
            with pri_col:
                priority = st.selectbox("Priority", ["Normal","High","Urgent"], key="it_pri")
            with btn_col:
                it_btn = st.button("ðŸ” Get Solution", use_container_width=True, key="it_btn")

            if it_btn and it_prob.strip():
                with st.spinner("ðŸ”„ IT Agent analyzing..."):
                    try:
                        from graph.it_graph import it_graph
                        result = it_graph.invoke({"user_name":it_name,"it_problem":it_prob})
                        sol = result.get("it_solution","")
                        tid = result.get("ticket_id","")
                        if tid:
                            st.success(f"âœ… Ticket created: **{tid}**")
                        if result.get("it_handled"):
                            st.markdown(f'<div class="resp-box">{sol}</div>', unsafe_allow_html=True)
                        else:
                            st.warning(sol)
                    except Exception as e:
                        st.error(f"Error: {e}")

        with c2:
            _render_email_auto_monitor_panel(key_prefix="it_mon")
            st.markdown('<div class="sec-hdr" style="margin-top:14px">ðŸŽ« Recent IT Tickets</div>', unsafe_allow_html=True)
            try:
                from database.sqlite_db import get_session
                from database.sqlite_db import ITTicket
                s    = get_session()
                tix  = s.query(ITTicket).order_by(ITTicket.timestamp.desc()).limit(5).all()
                s.close()
                for t in tix:
                    from html import escape as _esc

                    prob = _esc((t.problem or "")[:80])
                    un = _esc(t.user_name or "")
                    ts = t.timestamp.strftime("%Y-%m-%d %H:%M")
                    badge = "green" if t.status == "resolved" else "orange"
                    tid = _esc(t.ticket_id or "")
                    st.markdown(
                        f'<div class="hist-row">'
                        f'<b>{tid}</b> &nbsp; <span class="badge badge-{badge}">{t.status}</span><br>'
                        f'<small style="color:#64748b">{un} | {ts}</small><br>'
                        f"{prob}...</div>",
                        unsafe_allow_html=True,
                    )
            except Exception:
                st.caption("No tickets yet.")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 5 â€” EMAIL
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
if active_tab == "Email":
    with _MAIN:
        st.caption(
            "Tip: use **Assistant** for email-related tasks routed with other domains; this tab is for drafts, inbox, and confirm-send flows."
        )
        st.markdown('<div class="sec-hdr sec-teal">ðŸ“§ Email Coordinator <span class="badge badge-a2a">A2A</span></div>', unsafe_allow_html=True)
        _render_email_auto_monitor_panel(key_prefix="email_mon")
        st.divider()

        _render_agent_quick_chat("Email")

        if st.session_state.pending_email:
            p = st.session_state.pending_email
            st.warning(f"**ðŸ“§ Ready to Send**\n\n**To:** {p.get('name','')} `{p.get('email','')}`\n**Subject:** {p.get('subject','')}\n\n{p.get('body','')[:300]}...")
            cy, cn = st.columns(2)
            with cy:
                if st.button("âœ… Confirm & Send", use_container_width=True, key="send_yes"):
                    try:
                        from tools.gmail_send import send_email
                        from database.sqlite_db import log_email
                        send_email({"recipient":p["email"],"subject":p["subject"],"body":p["body"]})
                        log_email("sent", __import__("config").GMAIL_EMAIL, p["email"], p["subject"], p["body"])
                        st.session_state.coord_chat.append({"role":"agent","content":f"âœ… Email sent to {p.get('name',p['email'])}!"})
                        st.session_state.pending_email = None; st.rerun()
                    except Exception as e:
                        st.error(f"Send failed: {e}")
            with cn:
                if st.button("âŒ Cancel", use_container_width=True, key="send_no"):
                    st.session_state.pending_email = None; st.rerun()

        st.markdown('<div class="sec-hdr sec-teal" style="font-size:13px">ðŸ“¥ Read Inbox</div>', unsafe_allow_html=True)
        if not is_gmail_configured():
            st.warning("Gmail is not configured.")
        inbox_count = st.number_input("How many emails to fetch", min_value=1, max_value=30, value=10, key="inbox_fetch_n")
        if st.button("ðŸ“¬ Fetch Latest Emails", key="fetch_emails", type="primary", disabled=not is_gmail_configured()):
            with st.spinner("Connecting to Gmail..."):
                try:
                    from tools.gmail_read import read_emails
                    result = read_emails({"max_emails": int(inbox_count)})
                    st.session_state.inbox_emails = result.get("emails", [])
                    st.session_state.selected_inbox_idx = 0 if st.session_state.inbox_emails else None
                    if not st.session_state.inbox_emails:
                        err = result.get("email_error", "No emails found.")
                        if "not configured" in str(err).lower() or "not enough arguments" in str(err).lower():
                            st.error(err)
                        else:
                            st.info(f"ðŸ“­ {err}")
                    else:
                        st.success(f"Loaded **{len(st.session_state.inbox_emails)}** email(s). Select one below to read the full message.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        if st.session_state.inbox_emails:
            st.caption("Select an email to view the full message and download attachments.")
            list_col, detail_col = st.columns([1, 1.4])
            with list_col:
                labels = []
                for em in st.session_state.inbox_emails:
                    att_n = em.get("attachment_count") or 0
                    att_tag = f" ðŸ“Ž{att_n}" if att_n else ""
                    labels.append(
                        f"{em.get('date', '')} | {em.get('from_name', '?')[:28]}{att_tag}\n{em.get('subject', '')[:55]}"
                    )
                picked = st.radio(
                    "Inbox",
                    options=list(range(len(labels))),
                    format_func=lambda i: labels[i],
                    index=st.session_state.selected_inbox_idx or 0,
                    key="inbox_pick_radio",
                    label_visibility="collapsed",
                )
                st.session_state.selected_inbox_idx = picked
            with detail_col:
                sel_em = st.session_state.inbox_emails[st.session_state.selected_inbox_idx or 0]
                _render_inbox_email_detail(sel_em)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 6 â€” HR
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
if active_tab == "HR":
    with _MAIN:
        _render_agent_quick_chat("HR")
        st.info(
            "**Inbox fetch, CV shortlist, interview invites, and follow-ups** are handled in the **Assistant** tab "
            "using natural language (e.g. *fetch 20 and select two for python*, *send interview invitations Monday 3 PM*)."
        )

        st.markdown('<div class="sec-hdr sec-purple">HR operations</div>', unsafe_allow_html=True)
        hr_user = st.text_input("Your Name", value=st.session_state.user_name, key="hr_user")
        hr_action = st.selectbox(
            "HR Action",
            [
                "Screen CVs",
                "Match JD: shortlist + draft emails",
                "HR Policy Q&A",
                "Interview Questions",
                "Onboarding Checklist",
                "Draft Job Description",
            ],
            key="hr_action",
        )

        if hr_action == "Screen CVs":
            jd = st.text_area("Job Description", placeholder="Paste full job description...", height=120, key="hr_jd")
            uploaded = st.file_uploader("Upload CV Files (PDF, DOCX, TXT)", accept_multiple_files=True, type=["pdf", "docx", "txt"], key="cv_up")
            if uploaded:
                for f in uploaded:
                    if not any(c["name"] == f.name for c in st.session_state.uploaded_cvs):
                        text = _extract_text_from_uploaded_file(f)
                        st.session_state.uploaded_cvs.append({"name": f.name, "content": text or ""})
                st.success(f"{len(st.session_state.uploaded_cvs)} CV(s) in session")

            if st.session_state.uploaded_cvs:
                st.caption("CVs: " + ", ".join(c["name"] for c in st.session_state.uploaded_cvs))
                if st.button("Clear CVs", key="clr_cvs"):
                    st.session_state.uploaded_cvs = []
                    st.rerun()

            if st.button("Screen candidates", key="hr_screen", use_container_width=True):
                if not jd.strip():
                    st.warning("Enter job description")
                elif not st.session_state.uploaded_cvs:
                    st.warning("Upload CVs first")
                else:
                    with st.spinner(f"Screening {len(st.session_state.uploaded_cvs)} candidates..."):
                        try:
                            from graph.hr_graph import hr_graph

                            result = hr_graph.invoke(
                                {"action": "screen_cvs", "job_description": jd, "cvs": st.session_state.uploaded_cvs}
                            )
                            st.session_state.hr_results = result.get("results", [])
                            try:
                                from database.sqlite_db import log_candidate

                                for r in st.session_state.hr_results:
                                    log_candidate(
                                        r.get("name", ""),
                                        jd[:100],
                                        r.get("score", 0),
                                        r.get("recommendation", ""),
                                        r.get("strengths", []),
                                        r.get("weaknesses", []),
                                        r.get("summary", ""),
                                    )
                            except Exception:
                                pass
                        except Exception as e:
                            st.error(f"Error: {e}")

            if st.session_state.hr_results:
                st.markdown('<div class="sec-hdr sec-purple" style="font-size:13px">Screening results</div>', unsafe_allow_html=True)
                for i, r in enumerate(st.session_state.hr_results, 1):
                    score = r.get("score", 0)
                    rec = r.get("recommendation", "")
                    color = "#16a34a" if score >= 70 else ("#ca8a04" if score >= 50 else "#dc2626")
                    rb = {"Highly Recommended": "badge-green", "Recommended": "badge-blue", "Maybe": "badge-yellow", "Not Recommended": "badge-red"}.get(
                        rec, "badge-yellow"
                    )
                    with st.expander(f"#{i} {r.get('name', 'Unknown')} - {score}/100", expanded=i == 1):
                        from html import escape as _esc

                        summ = _esc(r.get("summary", "") or "")
                        nm = _esc(r.get("name", "") or "")
                        rec_e = _esc(rec or "")
                        st.markdown(
                            f'<div class="cand-card">'
                            f'<div style="display:flex;justify-content:space-between;align-items:center">'
                            f'<b style="font-size:16px">{nm}</b>'
                            f'<span class="badge {rb}">{rec_e}</span></div>'
                            f'<div class="score-bar"><div class="score-fill" style="width:{score}%;background:{color}"></div></div>'
                            f'<small style="color:{color}"><b>Score: {score}/100</b></small><br><br>'
                            f"{summ}"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                        sc1, sc2 = st.columns(2)
                        with sc1:
                            if r.get("strengths"):
                                st.markdown("**Strengths:**")
                                for s in r["strengths"]:
                                    st.markdown(f"- {s}")
                        with sc2:
                            if r.get("weaknesses"):
                                st.markdown("**Weaknesses:**")
                                for w in r["weaknesses"]:
                                    st.markdown(f"- {w}")

        elif hr_action == "Match JD: shortlist + draft emails":
            jd_m = st.text_area("Job description", placeholder="Paste the full JD...", height=120, key="hr_jd_match")
            top_n = st.number_input("How many candidates to select", min_value=1, max_value=20, value=5, step=1, key="hr_top_n")
            company = st.text_input("Company name", value="Our Company", key="hr_company_m")
            up_m = st.file_uploader("Upload CVs (PDF, DOCX, TXT)", accept_multiple_files=True, type=["pdf", "docx", "txt"], key="cv_up_match")
            if up_m:
                for f in up_m:
                    if not any(c["name"] == f.name for c in st.session_state.uploaded_cvs):
                        text = _extract_text_from_uploaded_file(f)
                        st.session_state.uploaded_cvs.append({"name": f.name, "content": text or ""})
            inc_db = st.checkbox("Include saved candidate profiles from database", value=False, key="hr_inc_db")
            pool = list(st.session_state.uploaded_cvs)
            if inc_db:
                from database.sqlite_db import get_candidates_as_cvs

                seen = {x["name"] for x in pool}
                for x in get_candidates_as_cvs(80):
                    if x["name"] not in seen:
                        pool.append(x)
                        seen.add(x["name"])
            if pool:
                st.caption(f"{len(pool)} candidate profile(s) in pool (files + optional database).")
            if st.button("Select top matches and draft outreach emails", key="hr_jd_match_btn", use_container_width=True):
                if not jd_m.strip():
                    st.warning("Enter job description")
                elif not pool:
                    st.warning("Upload CVs and/or load profiles from the database")
                else:
                    with st.spinner("Ranking candidates and drafting emails..."):
                        try:
                            from graph.hr_graph import hr_graph

                            r = hr_graph.invoke(
                                {
                                    "action": "jd_match_email",
                                    "job_description": jd_m,
                                    "cvs": pool,
                                    "top_n": int(top_n),
                                    "user_name": hr_user,
                                    "company_name": company,
                                }
                            )
                            st.markdown(f'<div class="resp-box resp-purple">{r.get("output", "")}</div>', unsafe_allow_html=True)
                        except Exception as e:
                            st.error(f"Error: {e}")

        elif hr_action == "HR Policy Q&A":
            q = st.text_area("HR Question", placeholder="e.g. How many leaves per year? What is the recruitment process?", height=100)
            if st.button("Get answer", key="hr_qa", use_container_width=True) and q.strip():
                with st.spinner("HR Agent thinking..."):
                    try:
                        from database.vector_db import rag_answer, collection_stats

                        stats2 = collection_stats()
                        if stats2.get("hr_policies", 0) > 0:
                            ans = rag_answer(q, "hr_policies", top_k=4, user_name=hr_user)
                        else:
                            from graph.hr_graph import hr_graph

                            result = hr_graph.invoke({"action": "hr_query", "query": q, "user_name": hr_user})
                            ans = result.get("output", "")
                        st.markdown(f'<div class="resp-box resp-purple">{ans}</div>', unsafe_allow_html=True)
                        from database.sqlite_db import log_agent

                        log_agent("HR Agent", "hr_qa", q, ans[:500])
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif hr_action == "Interview Questions":
            iq_jd = st.text_area("Job Description", height=100, key="iq_jd")
            iq_name = st.text_input("Candidate Name", key="iq_name")
            iq_cv = st.text_area("CV Summary (optional)", height=80, key="iq_cv")
            if st.button("Generate questions", key="iq_btn", use_container_width=True):
                with st.spinner("Generating..."):
                    try:
                        from graph.hr_graph import hr_graph

                        r = hr_graph.invoke(
                            {
                                "action": "interview_questions",
                                "job_description": iq_jd,
                                "candidate_name": iq_name or "Candidate",
                                "cv_content": iq_cv,
                            }
                        )
                        st.markdown(f'<div class="resp-box resp-purple">{r.get("output", "")}</div>', unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif hr_action == "Onboarding Checklist":
            ob1, ob2 = st.columns(2)
            with ob1:
                ob_title = st.text_input("Job Title", key="ob_title")
            with ob2:
                ob_dept = st.text_input("Department", key="ob_dept")
            if st.button("Generate checklist", key="ob_btn", use_container_width=True):
                with st.spinner("Generating..."):
                    try:
                        from graph.hr_graph import hr_graph

                        r = hr_graph.invoke(
                            {"action": "onboarding", "job_title": ob_title or "Employee", "department": ob_dept or "General"}
                        )
                        st.markdown(f'<div class="resp-box resp-purple">{r.get("output", "")}</div>', unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif hr_action == "Draft Job Description":
            jd1, jd2 = st.columns(2)
            with jd1:
                jd_role = st.text_input("Role", key="jd_role")
            with jd2:
                jd_dept = st.text_input("Department", key="jd_dept")
            jd_req = st.text_area("Key Requirements", height=80, key="jd_req")
            if st.button("Draft JD", key="jd_btn", use_container_width=True):
                with st.spinner("Drafting..."):
                    try:
                        from graph.hr_graph import hr_graph

                        r = hr_graph.invoke(
                            {"action": "job_description", "job_title": jd_role, "department": jd_dept, "query": jd_req}
                        )
                        st.markdown(f'<div class="resp-box resp-purple">{r.get("output", "")}</div>', unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Error: {e}")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 7 â€” FINANCE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
if active_tab == "Finance":
    with _MAIN:
        _render_agent_quick_chat("Finance")
        st.caption("Tip: use **Assistant** for mixed requests; this tab is for focused finance workflows.")
        st.markdown('<div class="sec-hdr sec-green">Finance</div>', unsafe_allow_html=True)
        fin_user = st.text_input("Your Name", value=st.session_state.user_name, key="fin_user")
        fin_action = st.selectbox(
            "Finance Action",
            [
                "Finance Q&A",
                "Analyze Expenses",
                "Upload data dashboard & charts",
                "Summarize Invoice",
                "Generate Report",
                "Budget vs Actual",
                "Generate documents (PDF / Excel / â€¦)",
            ],
            key="fin_act",
        )

        if fin_action == "Finance Q&A":
            fin_q   = st.text_area("Question", placeholder="e.g. What is the tax rate for IT services in Pakistan?", height=100)
            fin_ctx = st.text_area("Additional context (optional)", height=70, key="fin_ctx")
            if st.button("Ask Finance Agent", key="fin_qa", use_container_width=True) and fin_q.strip():
                with st.spinner("Finance Agent analyzing..."):
                    try:
                        # Try ChromaDB finance docs first
                        from database.vector_db import rag_answer, collection_stats
                        fstats = collection_stats()
                        if fstats.get("finance_docs",0) > 0:
                            ans = rag_answer(fin_q, "finance_docs", top_k=4, user_name=fin_user)
                        else:
                            from graph.finance_graph import finance_graph
                            r   = finance_graph.invoke({"action":"query","question":fin_q,"context":fin_ctx,"user_name":fin_user})
                            ans = r.get("output","")
                        st.markdown(f'<div class="resp-box resp-green">{ans}</div>', unsafe_allow_html=True)
                        from database.sqlite_db import log_finance
                        log_finance(fin_user,"qa",fin_q,ans[:500])
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif fin_action == "Analyze Expenses":
            fin_csv = st.file_uploader("Upload expense CSV or TXT (optional)", type=["csv", "txt"], key="fin_csv_up")
            fin_data = st.text_area(
                "Paste expense data (CSV or text)",
                placeholder="Date, Description, Amount, Category\n2024-01-05, Office Supplies, 2500, Operations",
                height=180,
                key="fin_exp",
            )
            if st.button("Analyze", key="fin_exp_btn", use_container_width=True):
                with st.spinner("Analyzing expenses..."):
                    try:
                        from graph.finance_graph import finance_graph

                        data_src = ""
                        if fin_csv is not None:
                            data_src = fin_csv.read().decode("utf-8", errors="ignore")
                        else:
                            data_src = fin_data
                        if not (data_src or "").strip():
                            st.warning("Paste data or upload a file.")
                        else:
                            r = finance_graph.invoke({"action": "analyze_expenses", "data": data_src, "user_name": fin_user})
                            ans = r.get("output", "")
                            st.markdown(f'<div class="resp-box resp-green">{ans}</div>', unsafe_allow_html=True)
                            try:
                                import pandas as pd
                                import io as _io
                                from utils.finance_upload_charts import coerce_numeric_columns

                                df = pd.read_csv(_io.StringIO(data_src))
                                df = coerce_numeric_columns(df)
                                if df.shape[1] >= 3:
                                    amt_col = df.columns[2]
                                    cat_col = df.columns[3] if df.shape[1] > 3 else df.columns[1]
                                    chart_df = (
                                        df[[cat_col, amt_col]]
                                        .dropna(subset=[amt_col])
                                        .groupby(cat_col)[amt_col]
                                        .sum()
                                        .reset_index()
                                    )
                                    if not chart_df.empty:
                                        st.bar_chart(chart_df.set_index(cat_col))
                            except Exception:
                                pass
                            from database.sqlite_db import log_finance

                            log_finance(fin_user, "analyze_expenses", data_src[:500], ans[:500])
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif fin_action == "Upload data dashboard & charts":
            st.markdown(
                "Upload **one or more** CSV, Excel, or tab-separated text files. "
                "Each file gets a **stats panel** and **chart settings**. Choose chart types, then click **Build dashboard** to render plots for every file at once."
            )
            dash_files = st.file_uploader(
                "Data files (multiple allowed)",
                type=["csv", "txt", "xlsx", "xls"],
                accept_multiple_files=True,
                key="fin_dash_up",
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                chart_choices = st.multiselect(
                    "Chart types",
                    ["Bar", "Line", "Area", "Pie", "Scatter"],
                    default=["Bar", "Pie"],
                    key="fin_dash_charts",
                    help="Scatter uses two numeric columns (X vs Y). Other charts group by category and aggregate the value column.",
                )
            with c2:
                st.selectbox(
                    "Aggregation (Bar / Line / Area / Pie)",
                    ["sum", "mean", "count"],
                    key="fin_dash_agg",
                )
            with c3:
                st.checkbox(
                    "AI summary (Finance Agent)",
                    value=False,
                    key="fin_dash_ai",
                    help="When you build the dashboard, sends a CSV snippet of each file to the agent for a short narrative.",
                )

            plotly_ok = False
            try:
                import plotly

                plotly_ok = bool(plotly.__version__)
            except Exception:
                plotly_ok = False

            if dash_files:
                import pandas as pd
                from utils.finance_upload_charts import (
                    file_to_dataframe,
                    coerce_numeric_columns,
                    guess_category_value_columns,
                    dataframe_profile,
                )

                if not plotly_ok:
                    st.warning("Install **plotly** to render charts: `pip install plotly`. Tables and stats still appear below.")

                for idx, dfile in enumerate(dash_files):
                    key_s = f"{idx}_{abs(hash(dfile.name)) % 10_000_000}"
                    df, err = file_to_dataframe(dfile)
                    with st.expander(f"ðŸ“„ {dfile.name}", expanded=(idx == 0)):
                        if err or df is None:
                            st.error(f"Could not read file: {err or 'unknown error'}")
                            continue
                        if df.empty:
                            st.warning("This file is empty.")
                            continue

                        df = coerce_numeric_columns(df)
                        prof = dataframe_profile(df)
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Rows", prof["rows"])
                        m2.metric("Columns", prof["columns"])
                        m3.metric("Numeric columns", len(prof["numeric_columns"]))
                        m4.metric("Total missing cells", int(sum(prof["null_counts"].values())))

                        t1, t2 = st.tabs(["Preview & stats", "Chart column mapping"])
                        with t1:
                            st.caption("First rows")
                            st.dataframe(df.head(25), use_container_width=True)
                            st.caption("Numeric summary")
                            try:
                                st.dataframe(df.describe(), use_container_width=True)
                            except Exception:
                                st.info("No numeric columns to describe.")
                            nulls_pos = {k: v for k, v in prof["null_counts"].items() if v > 0}
                            if nulls_pos:
                                st.caption("Missing values per column")
                                null_df = pd.DataFrame(
                                    [{"Column": k, "Missing": v} for k, v in nulls_pos.items()]
                                )
                                st.dataframe(null_df, use_container_width=True)
                                st.bar_chart(null_df.set_index("Column"))

                        with t2:
                            cols = [str(c) for c in df.columns]
                            cat_guess, val_guess = guess_category_value_columns(df)
                            num_cols = prof["numeric_columns"]
                            cx1, cx2 = st.columns(2)
                            with cx1:
                                st.selectbox(
                                    "Category / labels column",
                                    cols,
                                    index=cols.index(cat_guess) if cat_guess in cols else 0,
                                    key=f"fin_dash_cat_{key_s}",
                                )
                            with cx2:
                                val_opts = [c for c in cols if c in num_cols] or cols
                                vi = val_opts.index(val_guess) if val_guess in val_opts else 0
                                st.selectbox(
                                    "Value column (numeric)",
                                    val_opts,
                                    index=min(vi, len(val_opts) - 1),
                                    key=f"fin_dash_val_{key_s}",
                                )
                            sx1, sx2 = st.columns(2)
                            with sx1:
                                x_opts = num_cols or cols
                                st.selectbox(
                                    "Scatter X (numeric)",
                                    x_opts,
                                    index=0,
                                    key=f"fin_dash_sx_{key_s}",
                                )
                            with sx2:
                                _xk = f"fin_dash_sx_{key_s}"
                                x_pick = st.session_state.get(_xk, x_opts[0] if x_opts else "")
                                y_opts = [c for c in (num_cols or cols) if c != x_pick] or cols
                                st.selectbox(
                                    "Scatter Y (numeric)",
                                    y_opts,
                                    index=min(1, len(y_opts) - 1) if len(y_opts) > 1 else 0,
                                    key=f"fin_dash_sy_{key_s}",
                                )

            go_dash = st.button("Build dashboard", key="fin_dash_go", use_container_width=True)
            if go_dash:
                if not dash_files:
                    st.warning("Upload at least one data file.")
                elif not chart_choices:
                    st.warning("Select at least one chart type.")
                elif not plotly_ok:
                    st.error("Plotly is required for charts. Run: `pip install plotly`")
                else:
                    import pandas as pd
                    from utils.finance_upload_charts import (
                        file_to_dataframe,
                        coerce_numeric_columns,
                        dataframe_profile,
                        build_chart_figure,
                    )

                    agg_use = st.session_state.get("fin_dash_agg", "sum")
                    want_ai = st.session_state.get("fin_dash_ai", False)
                    charts_use = st.session_state.get("fin_dash_charts") or chart_choices

                    for idx, dfile in enumerate(dash_files):
                        key_s = f"{idx}_{abs(hash(dfile.name)) % 10_000_000}"
                        df, err = file_to_dataframe(dfile)
                        if err or df is None or df.empty:
                            continue
                        df = coerce_numeric_columns(df)
                        prof = dataframe_profile(df)
                        cat_col = st.session_state.get(f"fin_dash_cat_{key_s}")
                        val_col = st.session_state.get(f"fin_dash_val_{key_s}")
                        x_col = st.session_state.get(f"fin_dash_sx_{key_s}")
                        y_col = st.session_state.get(f"fin_dash_sy_{key_s}")
                        st.markdown(f"##### Charts: {dfile.name}")
                        for ct in charts_use:
                            raw = (ct or "").strip().lower()
                            fig = build_chart_figure(
                                raw,
                                df,
                                category_col=cat_col or "",
                                value_col=val_col or "",
                                x_col=x_col or "",
                                y_col=y_col or "",
                                agg=agg_use,
                            )
                            if fig is None:
                                st.caption(f"**{ct}** â€” could not build (check columns and numeric values).")
                            else:
                                st.plotly_chart(fig, use_container_width=True)
                        if want_ai:
                            with st.spinner(f"AI summary for {dfile.name}â€¦"):
                                try:
                                    from graph.finance_graph import finance_graph

                                    snippet = df.head(80).to_csv(index=False)
                                    r = finance_graph.invoke(
                                        {
                                            "action": "analyze_expenses",
                                            "data": f"File: {dfile.name}\n{snippet}",
                                            "user_name": fin_user,
                                        }
                                    )
                                    st.markdown(
                                        f'<div class="resp-box resp-green">{r.get("output", "")}</div>',
                                        unsafe_allow_html=True,
                                    )
                                except Exception as ex:
                                    st.warning(f"AI summary skipped for {dfile.name}: {ex}")
                        st.divider()

                    try:
                        from database.sqlite_db import log_finance

                        names = ",".join(f.name for f in dash_files)[:400]
                        log_finance(fin_user, "dashboard_charts", names, ",".join(charts_use)[:200])
                    except Exception:
                        pass

        elif fin_action == "Summarize Invoice":
            inv_text = st.text_area("Paste Invoice Text", height=200, key="inv_txt")
            if st.button("Summarize", key="inv_btn", use_container_width=True):
                with st.spinner("Processing invoice..."):
                    try:
                        from graph.finance_graph import finance_graph
                        r = finance_graph.invoke({"action":"summarize_invoice","data":inv_text})
                        st.markdown(f'<div class="resp-box resp-green">{r.get("output","")}</div>', unsafe_allow_html=True)
                        from database.sqlite_db import log_finance
                        log_finance(fin_user,"summarize_invoice",inv_text[:300],r.get("output","")[:500])
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif fin_action == "Generate Report":
            rep_data = st.text_area("Financial Data", height=160, key="rep_data")
            rep_type = st.selectbox("Report Type", ["general","budget","expense","invoice"], key="rep_type")
            if st.button("Generate report", key="rep_btn", use_container_width=True):
                with st.spinner("Generating report..."):
                    try:
                        from graph.finance_graph import finance_graph
                        r = finance_graph.invoke({"action":"report","data":rep_data,"report_type":rep_type})
                        st.markdown(f'<div class="resp-box resp-green">{r.get("output","")}</div>', unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif fin_action == "Budget vs Actual":
            bc1, bc2 = st.columns(2)
            with bc1: bdata = st.text_area("Budget Data", placeholder="IT, 500000\nMarketing, 200000", height=140, key="bdata")
            with bc2: adata = st.text_area("Actual Data", placeholder="IT, 485000\nMarketing, 267000", height=140, key="adata")
            if st.button("Analyze budget vs actual", key="bva_btn", use_container_width=True):
                with st.spinner("Analyzing..."):
                    try:
                        from graph.finance_graph import finance_graph
                        r = finance_graph.invoke({"action":"budget_vs_actual","data":f"{bdata}|||{adata}"})
                        ans = r.get("output","")
                        st.markdown(f'<div class="resp-box resp-green">{ans}</div>', unsafe_allow_html=True)
                        # Chart
                        try:
                            import pandas as pd, io
                            bdf = pd.read_csv(io.StringIO(bdata), header=None, names=["Category","Budget"])
                            adf = pd.read_csv(io.StringIO(adata), header=None, names=["Category","Actual"])
                            for _d, _c in ((bdf, "Budget"), (adf, "Actual")):
                                _d[_c] = pd.to_numeric(
                                    _d[_c].astype("string").str.replace(",", "", regex=False).str.strip(),
                                    errors="coerce",
                                )
                            merged = bdf.merge(adf, on="Category").dropna().set_index("Category")
                            if not merged.empty:
                                st.bar_chart(merged)
                        except Exception:
                            pass
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif fin_action == "Generate documents (PDF / Excel / â€¦)":
            st.markdown(
                "Describe the **report, summary, or analysis** you want and paste **source numbers or text**. "
                "Pick one or more formats; binaries are built **in parallel** (ThreadPoolExecutor)."
            )
            fin_exp_instr = st.text_area(
                "What to generate (instructions)",
                placeholder="e.g. Monthly expense variance: Operations vs IT, PKR, with recommendations",
                height=90,
                key="fin_exp_instr",
            )
            fin_exp_up = st.file_uploader(
                "Upload source documents (optional)",
                type=["csv", "txt", "pdf", "docx", "xlsx", "xls"],
                accept_multiple_files=True,
                key="fin_exp_up",
                help="Text is extracted and merged with the source data box for the LLM and exports.",
            )
            fin_exp_data = st.text_area(
                "Source data (optional)",
                placeholder="Paste CSV rows, budget lines, invoice text, or notesâ€¦",
                height=160,
                key="fin_exp_data",
            )
            fin_exp_fm = st.multiselect(
                "Output formats",
                ["pdf", "xlsx", "csv", "txt", "docx"],
                default=["pdf"],
                format_func=lambda x: {
                    "pdf": "PDF",
                    "xlsx": "Excel (.xlsx)",
                    "csv": "CSV",
                    "txt": "Plain text (.txt)",
                    "docx": "Word (.docx)",
                }.get(x, x),
                key="fin_exp_fm",
            )
            if st.button("Generate & download", type="primary", key="fin_exp_go", use_container_width=True):
                instr = (fin_exp_instr or "").strip()
                data_src = (fin_exp_data or "").strip()
                if not instr and not data_src and not fin_exp_up:
                    st.warning("Add instructions and/or source data, or upload a file.")
                else:
                    with st.spinner("LLM structuring + parallel export (PDF / Excel / â€¦)â€¦"):
                        try:
                            from graph.finance_graph import finance_graph

                            upload_blob = ""
                            if fin_exp_up:
                                parts_u: list[str] = []
                                for uf in fin_exp_up:
                                    tx = _extract_text_from_uploaded_file(uf)
                                    if tx.strip():
                                        parts_u.append(f"### {uf.name}\n{tx}")
                                upload_blob = "\n\n".join(parts_u)
                            merged_data = "\n\n".join(x for x in (data_src, upload_blob) if (x or "").strip())

                            q = instr or (merged_data[:800] + " â€” finance document export")
                            r = finance_graph.invoke(
                                {
                                    "action": "export_documents",
                                    "question": q,
                                    "data": merged_data,
                                    "user_name": fin_user,
                                    "export_formats": list(fin_exp_fm) if fin_exp_fm else None,
                                }
                            )
                            st.markdown(
                                f'<div class="resp-box resp-green">{r.get("output", "")}</div>',
                                unsafe_allow_html=True,
                            )
                            for i, fe in enumerate(r.get("export_files") or []):
                                st.download_button(
                                    label=f"Download {fe.get('filename', 'file')}",
                                    data=fe.get("data") or b"",
                                    file_name=fe.get("filename") or "export.bin",
                                    mime=fe.get("mime_type") or "application/octet-stream",
                                    key=f"fin_tab_dl_{i}",
                                )
                            try:
                                from database.sqlite_db import log_finance

                                log_finance(fin_user, "export_documents", q[:500], (r.get("output") or "")[:500])
                            except Exception:
                                pass
                        except Exception as e:
                            st.error(str(e))

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 8 â€” DOCUMENTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
if active_tab == "Documents":
    with _MAIN:
        _render_agent_quick_chat("Documents")
        st.caption("Tip: **Assistant** can route document Q&A; use this tab for Drive load, embeddings, and batch tools.")
        st.markdown('<div class="sec-hdr sec-teal">ðŸ“‚ Documents Agent <span class="badge badge-mcp">MCP</span> <span class="badge badge-purple">ChromaDB</span></div>', unsafe_allow_html=True)
        docs_user = st.text_input("Your Name", value=st.session_state.user_name, key="docs_user")

        lc1, lc2 = st.columns(2)
        with lc1:
            if st.button("â˜ï¸ Load from Google Drive", key="load_drive", use_container_width=True):
                if not is_google_drive_configured():
                    st.error("Google Drive is not configured.")
                else:
                    with st.spinner("ðŸ“‚ Loading and reading Drive files..."):
                        try:
                            from tools.mcp_drive_client import DriveClient

                            client = DriveClient()
                            docs = client.load_documents(max_results=50)
                            if docs:
                                st.session_state.drive_documents = docs
                                from database.vector_db import embed_documents

                                with st.spinner("ðŸ§  Embedding into ChromaDB..."):
                                    res = embed_documents(docs, "documents")
                                st.success(
                                    f"âœ… Loaded {len(docs)} docs Â· Embedded {res.get('embedded', 0)} into ChromaDB"
                                )
                                try:
                                    from database.sqlite_db import get_session, DocumentMeta

                                    s = get_session()
                                    for d in docs:
                                        s.add(
                                            DocumentMeta(
                                                file_name=d.get("file", ""),
                                                content_len=len(d.get("content", "")),
                                                source="drive",
                                                embedded=True,
                                            )
                                        )
                                    s.commit()
                                    s.close()
                                except Exception:
                                    pass
                            else:
                                files = client.list_files(max_results=50)
                                if files:
                                    st.session_state.drive_documents = [
                                        {"file": f.get("name", ""), "id": f.get("id", ""), "content": ""}
                                        for f in files
                                    ]
                                    st.warning(f"âš ï¸ Listed {len(files)} files but could not read content.")
                                else:
                                    st.warning("No files found in Google Drive.")
                        except DriveNotConfiguredError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"Drive error: {e}")

        with lc2:
            up_docs = st.file_uploader("ðŸ“ Upload Files", accept_multiple_files=True, type=["pdf","txt","docx"], key="doc_up")
            if up_docs:
                for f in up_docs:
                    if not any(d["file"]==f.name for d in st.session_state.drive_documents):
                        try:
                            if f.name.endswith(".pdf"):
                                import io, pdfplumber
                                with pdfplumber.open(io.BytesIO(f.read())) as pdf:
                                    content = "\n".join(p.extract_text() or "" for p in pdf.pages)
                            else:
                                content = f.read().decode("utf-8","ignore")
                            st.session_state.drive_documents.append({"file":f.name,"content":content})
                        except Exception:
                            st.session_state.drive_documents.append({"file":f.name,"content":f.read().decode("utf-8","ignore")})
                # Auto-embed
                if st.session_state.drive_documents:
                    from database.vector_db import embed_documents
                    embed_documents([d for d in st.session_state.drive_documents if d.get("content")], "documents")
                st.success(f"âœ… {len(st.session_state.drive_documents)} documents ready & embedded")

        if st.session_state.drive_documents:
            names = " | ".join(d["file"] for d in st.session_state.drive_documents[:5])
            extra = f" | +{len(st.session_state.drive_documents)-5} more" if len(st.session_state.drive_documents)>5 else ""
            st.markdown(f"**{len(st.session_state.drive_documents)} documents** | {names}{extra}")
            if st.button("ðŸ—‘ï¸ Clear", key="clr_docs"): st.session_state.drive_documents=[]; st.rerun()

        st.divider()
        docs_action = st.selectbox("Document Action", [
            "ðŸ’¬ Q&A (RAG via ChromaDB)","ðŸ” Search","ðŸ“ Summarize",
            "ðŸ”Ž Extract Data","âš–ï¸ Compare Two Docs","ðŸ“Š Batch Analyze","ðŸ“‹ List All"
        ], key="docs_action")

        if docs_action.startswith("ðŸ’¬"):
            st.caption("Type your question in the chat bar pinned at the bottom of the page. Your conversation appears at the top of this tab.")

        elif docs_action.startswith("ðŸ”"):
            sq = st.text_input("Search query", key="doc_sq")
            if st.button("ðŸ” Search", key="doc_srch", use_container_width=True) and sq.strip():
                with st.spinner("Searching..."):
                    try:
                        from agents.documents_agent import search_documents
                        ans = search_documents(sq, st.session_state.drive_documents, docs_user)
                        st.markdown(f'<div class="resp-box resp-teal">{ans}</div>', unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif docs_action.startswith("ðŸ“"):
            if st.session_state.drive_documents:
                sel = st.selectbox("Select Document", [d["file"] for d in st.session_state.drive_documents], key="sum_sel")
                if st.button("ðŸ“ Summarize", key="sum_btn", use_container_width=True):
                    doc = next((d for d in st.session_state.drive_documents if d["file"]==sel), None)
                    if doc:
                        with st.spinner("Summarizing..."):
                            try:
                                from agents.documents_agent import summarize_document
                                ans = summarize_document(doc["content"], doc["file"], docs_user)
                                st.markdown(f'<div class="resp-box resp-teal">{ans}</div>', unsafe_allow_html=True)
                            except Exception as e:
                                st.error(f"Error: {e}")
            else:
                st.info("Load documents first.")

        elif docs_action.startswith("ðŸ”Ž"):
            ext_type = st.selectbox("Extract Type", ["all","dates","amounts","parties","clauses","contacts"], key="ext_t")
            if st.session_state.drive_documents:
                sel = st.selectbox("Select Document", [d["file"] for d in st.session_state.drive_documents], key="ext_sel")
                if st.button("ðŸ”Ž Extract", key="ext_btn", use_container_width=True):
                    doc = next((d for d in st.session_state.drive_documents if d["file"]==sel), None)
                    if doc:
                        with st.spinner("Extracting..."):
                            try:
                                from agents.documents_agent import extract_data_from_document
                                ans = extract_data_from_document(doc["content"], ext_type, doc["file"])
                                st.markdown(f'<div class="resp-box resp-teal">{ans}</div>', unsafe_allow_html=True)
                            except Exception as e:
                                st.error(f"Error: {e}")

        elif docs_action.startswith("âš–ï¸"):
            if len(st.session_state.drive_documents) >= 2:
                names = [d["file"] for d in st.session_state.drive_documents]
                cc1, cc2 = st.columns(2)
                with cc1: d1n = st.selectbox("Document 1", names, key="cmp1")
                with cc2: d2n = st.selectbox("Document 2", names, index=1, key="cmp2")
                if st.button("âš–ï¸ Compare", key="cmp_btn", use_container_width=True):
                    d1 = next((d for d in st.session_state.drive_documents if d["file"]==d1n), {})
                    d2 = next((d for d in st.session_state.drive_documents if d["file"]==d2n), {})
                    with st.spinner("Comparing..."):
                        try:
                            from agents.documents_agent import compare_documents
                            ans = compare_documents(d1.get("content",""), d2.get("content",""), d1n, d2n)
                            st.markdown(f'<div class="resp-box resp-teal">{ans}</div>', unsafe_allow_html=True)
                        except Exception as e:
                            st.error(f"Error: {e}")
            else:
                st.info("Load at least 2 documents.")

        elif docs_action.startswith("ðŸ“Š"):
            bat = st.selectbox("Analysis Type", ["overview","financial","contracts","policies","compliance"], key="bat_t")
            if st.button("ðŸ“Š Batch Analyze", key="bat_btn", use_container_width=True):
                with st.spinner(f"Analyzing {len(st.session_state.drive_documents)} documents..."):
                    try:
                        from agents.documents_agent import batch_analyze_documents
                        ans = batch_analyze_documents(st.session_state.drive_documents, bat)
                        st.markdown(f'<div class="resp-box resp-teal">{ans}</div>', unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif docs_action.startswith("ðŸ“‹"):
            if st.button("ðŸ“‹ List All", key="lst_btn", use_container_width=True):
                from agents.documents_agent import list_documents_summary
                st.markdown(f'<div class="resp-box resp-teal">{list_documents_summary(st.session_state.drive_documents)}</div>', unsafe_allow_html=True)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB â€” HISTORY
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
if active_tab == "History":
    with _MAIN:
        st.markdown('<div class="sec-hdr sec-blue">Chat &amp; activity history</div>', unsafe_allow_html=True)

        st.markdown('<div class="sec-hdr" style="margin-top:8px">Saved chat threads</div>', unsafe_allow_html=True)
        try:
            from database.sqlite_db import (
                list_user_conversations,
                load_conversation_ui_messages,
                get_conversation_for_user,
            )

            threads = list_user_conversations(st.session_state.username, "orchestrator", limit=25)
            if threads:
                for t in threads:
                    with st.expander(
                        f"Thread #{t['id']} Â· {t['updated_at']} Â· {t['message_count']} messages",
                        expanded=False,
                    ):
                        if t.get("preview"):
                            st.caption(t["preview"])
                        msgs = load_conversation_ui_messages(t["id"], limit=40)
                        for m in msgs:
                            role_lbl = "You" if m.get("role") == "user" else "Assistant"
                            agents = ", ".join(m.get("agents") or [])
                            st.markdown(
                                f'<div class="hist-row"><b>{role_lbl}</b>'
                                + (f' <span class="badge badge-blue">{_hesc_html(agents)}</span>' if agents else "")
                                + f"<br>{_hesc_html(m.get('content', '')[:800])}</div>",
                                unsafe_allow_html=True,
                            )
                        if st.button(f"Open in Assistant", key=f"hist_open_{t['id']}"):
                            if get_conversation_for_user(t["id"], st.session_state.username):
                                st.session_state.orch_conversation_id = t["id"]
                                st.session_state.orch_chat = []
                                _sync_orch_chat_from_db(force=True)
                                st.info(f"Thread #{t['id']} loaded â€” open the **Assistant** tab to continue.")
                                st.rerun()
            else:
                st.info("No saved chat threads yet. Use **Assistant** â€” each thread is stored automatically.")
        except Exception as ex:
            st.error(f"Chat threads: {ex}")

        st.divider()
        st.markdown('<div class="sec-hdr">Task audit log</div>', unsafe_allow_html=True)

        hist_filter = st.selectbox("Filter by source", ["All", "ui", "api"], key="hist_filter")
        try:
            from database.sqlite_db import get_task_history
            history = get_task_history(limit=50)
            if hist_filter != "All":
                history = [h for h in history if h.get("source") == hist_filter]

            if history:
                st.caption(f"Showing {len(history)} tasks")
                for h in history:
                    src_badge = {"ui": "badge-blue", "api": "badge-purple"}.get(h.get("source", "ui"), "badge-blue")
                    with st.expander(f"#{h['id']} | {h['time']} | {h.get('user','')} | {h.get('agents','')}", expanded=False):
                        resp = h.get("response", "") or ""
                        tail = "..." if len(resp) > 500 else ""
                        body = (
                            f'<div class="hist-row">'
                            f'<span class="badge {src_badge}">{_hesc_html(h.get("source", "ui").upper())}</span> '
                            f'<span class="badge badge-green">{_hesc_html(h.get("role", ""))}</span> '
                            f'<span style="font-size:12px;color:#64748b"> {h.get("elapsed", 0)}ms</span><br><br>'
                            f'<b>Input:</b> {_hesc_html(h.get("input", ""))}<br><br>'
                            f'<b>Agents:</b> {_hesc_html(h.get("agents", ""))}<br><br>'
                            f'<b>Response:</b><br>{_hesc_html(resp[:500])}{tail}'
                            f"</div>"
                        )
                        st.markdown(body, unsafe_allow_html=True)
            else:
                st.info("No task history yet. Use the **Assistant** tab to send tasks.")
        except Exception as e:
            st.error(f"History error: {e}")

        st.divider()
        st.markdown('<div class="sec-hdr">ðŸ” Login History (database)</div>', unsafe_allow_html=True)
        try:
            from database.sqlite_db import get_login_history
            if st.session_state.user_role == "Admin":
                login_rows = get_login_history(limit=200)
                st.caption("All users â€” stored in the database login history table.")
            else:
                login_rows = get_login_history(limit=100, username=st.session_state.username)
                st.caption("Your sign-in / sign-out events only.")
            if login_rows:
                for row in login_rows:
                    ev = (row.get("event") or "").lower()
                    badge = "badge-green" if ev == "login" else "badge-orange"
                    st.markdown(
                        f'<div class="hist-row">'
                        f'<span class="badge {badge}">{(row.get("event") or "").upper()}</span> '
                        f'<b>{row.get("display_name", "")}</b> '
                        f'<span style="color:#64748b">({row.get("username", "")} Â· {row.get("role", "")})</span><br>'
                        f'<small style="color:#94a3b8">{row.get("time", "")}</small>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No login history yet. Sign in and out to record events.")
        except Exception as e:
            st.error(f"Login history error: {e}")



# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PINNED CHAT BAR â€” rendered at top level so Streamlit anchors it to the bottom
# of the viewport, like ChatGPT / Claude / Gemini. Shown for every agent tab.
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
if st.session_state.get("logged_in"):
    _act = st.session_state.get("active_tab")
    if _act == "Assistant":
        _prompt = st.chat_input(
            "Message the assistantâ€¦  (e.g. fetch latest 10 candidate emails, then shortlist 2 for Python)"
        )
        if _prompt and _prompt.strip():
            st.session_state["_pending_orch_prompt"] = _prompt.strip()
            st.rerun()
    elif _act in _AGENT_CHAT:
        _ph = _AGENT_CHAT[_act][2]
        _prompt = st.chat_input(_ph)
        if _prompt and _prompt.strip():
            st.session_state[f"_pending_{_act}"] = _prompt.strip()
            st.rerun()



