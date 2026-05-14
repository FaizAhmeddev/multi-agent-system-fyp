"""
UI/APP.PY — Office Automation Agents Pro v7.0 — FYP FINAL
==========================================================
Tabs: Login | Assistant (orchestrator) | Dashboard | Recruitment AI | specialist tools | History
"""
import sys, os, time, json
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

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
    layout="wide", page_icon=None,
    initial_sidebar_state="collapsed",
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
    OPENAI_API_KEY,
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
* { font-family: 'Inter', sans-serif !important; }
.main { padding-top: 0.3rem; background: #f8fafc; }
.stApp { background: #f8fafc; }

/* Login card */
.login-wrap { display:flex; justify-content:center; align-items:center; min-height:80vh; }
.login-card {
    background: white; border-radius: 20px; padding: 40px 48px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.12); max-width: 420px; width:100%;
    border: 1px solid #e2e8f0;
}
.login-logo { text-align:center; font-size:48px; margin-bottom:8px; }
.login-title { text-align:center; font-size:24px; font-weight:800; color:#1e293b; margin-bottom:4px; }
.login-sub { text-align:center; font-size:13px; color:#64748b; margin-bottom:28px; }

/* Header */
.main-header {
    background: linear-gradient(135deg, #1e293b 0%, #334155 50%, #0f172a 100%);
    color: white; padding: 14px 24px; border-radius: 14px; margin-bottom: 16px;
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: 0 4px 20px rgba(0,0,0,0.2);
}
.header-title { font-size:22px; font-weight:800; letter-spacing:-0.3px; }
.header-sub { font-size:11px; color:#94a3b8; margin-top:2px; }

/* Metric cards */
.metric-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }
.metric-card {
    background:white; border:1px solid #e2e8f0; border-radius:14px;
    padding:16px 20px; box-shadow:0 2px 8px rgba(0,0,0,0.06);
    transition: transform 0.2s, box-shadow 0.2s;
}
.metric-card:hover { transform:translateY(-2px); box-shadow:0 6px 20px rgba(0,0,0,0.1); }
.metric-icon { font-size:28px; margin-bottom:6px; }
.metric-num { font-size:32px; font-weight:800; color:#1e293b; line-height:1; }
.metric-label { font-size:12px; color:#64748b; margin-top:4px; font-weight:500; }
.metric-delta { font-size:11px; color:#16a34a; font-weight:600; }

/* Agent cards */
.agent-status-card {
    background:white; border:1px solid #e2e8f0; border-radius:12px;
    padding:14px 18px; display:flex; align-items:center; gap:12px;
    box-shadow:0 2px 6px rgba(0,0,0,0.05);
}
.agent-dot { width:10px; height:10px; border-radius:50%; background:#16a34a; flex-shrink:0; animation: pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }

/* Response boxes */
.resp-box {
    background:white; border-left:4px solid #2563eb; border-radius:0 12px 12px 0;
    padding:18px 22px; margin:10px 0; box-shadow:0 2px 8px rgba(0,0,0,0.07);
    line-height:1.7; white-space:pre-wrap;
}
.resp-green  { border-left-color:#16a34a; }
.resp-purple { border-left-color:#7c3aed; }
.resp-orange { border-left-color:#ea580c; }
.resp-teal   { border-left-color:#0d9488; }
.resp-red    { border-left-color:#dc2626; }

/* Chat */
.chat-user  { background:linear-gradient(135deg,#2563eb,#1d4ed8); color:white; padding:10px 16px; border-radius:18px 18px 4px 18px; margin:6px 0 6px auto; max-width:75%; display:inline-block; float:right; clear:both; font-size:14px; }
.chat-agent { background:white; color:#1e293b; padding:12px 16px; border-radius:18px 18px 18px 4px; margin:6px 0; max-width:80%; display:inline-block; float:left; clear:both; font-size:14px; border:1px solid #e2e8f0; box-shadow:0 2px 6px rgba(0,0,0,0.06); line-height:1.6; white-space:pre-wrap; }
.chat-wrap  { overflow:hidden; margin-bottom:6px; }

/* Sections */
.sec-hdr {
    background:linear-gradient(90deg,#1e293b,#334155); color:white;
    padding:10px 18px; border-radius:10px; margin:14px 0 10px 0;
    font-weight:700; font-size:14px; letter-spacing:0.2px;
}
.sec-blue   { background:linear-gradient(90deg,#1d4ed8,#3b82f6) !important; }
.sec-green  { background:linear-gradient(90deg,#15803d,#22c55e) !important; }
.sec-purple { background:linear-gradient(90deg,#6d28d9,#a855f7) !important; }
.sec-teal   { background:linear-gradient(90deg,#0f766e,#14b8a6) !important; }
.sec-orange { background:linear-gradient(90deg,#c2410c,#f97316) !important; }
.sec-wa     { background:linear-gradient(90deg,#15803d,#16a34a) !important; }

/* Badges */
.badge { padding:3px 10px; border-radius:20px; font-size:11px; font-weight:700; display:inline-block; }
.badge-green  { background:#dcfce7; color:#15803d; }
.badge-blue   { background:#dbeafe; color:#1d4ed8; }
.badge-purple { background:#f3e8ff; color:#6d28d9; }
.badge-orange { background:#ffedd5; color:#c2410c; }
.badge-red    { background:#fee2e2; color:#dc2626; }
.badge-yellow { background:#fef9c3; color:#854d0e; }
.badge-mcp    { background:#0d9488; color:white; }
.badge-a2a    { background:#7c3aed; color:white; }
.badge-wa     { background:#16a34a; color:white; }

/* Queue messages */
.qmsg { background:white; border:1px solid #e2e8f0; border-radius:8px; padding:8px 12px; margin-bottom:5px; font-size:12px; font-family:monospace; }
.qmsg-task   { border-left:3px solid #2563eb; }
.qmsg-result { border-left:3px solid #16a34a; }
.qmsg-status { border-left:3px solid #f59e0b; }
.qmsg-broadcast { border-left:3px solid #7c3aed; }

/* Candidate */
.cand-card { background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px; margin-bottom:10px; box-shadow:0 2px 6px rgba(0,0,0,0.05); }
.score-bar  { height:8px; border-radius:4px; background:#e2e8f0; margin:8px 0 4px 0; }
.score-fill { height:8px; border-radius:4px; }

/* WhatsApp */
.wa-bubble-out { background:#dcf8c6; border-radius:18px 4px 18px 18px; padding:10px 14px; margin:6px 0 6px auto; max-width:75%; display:inline-block; float:right; clear:both; font-size:14px; }
.wa-bubble-in  { background:white; border-radius:4px 18px 18px 18px; padding:10px 14px; margin:6px 0; max-width:75%; display:inline-block; float:left; clear:both; font-size:14px; border:1px solid #e2e8f0; }

/* History table */
.hist-row { background:white; border:1px solid #e2e8f0; border-radius:8px; padding:10px 14px; margin-bottom:6px; font-size:13px; }

/* Notification */
.notif { border-radius:10px; padding:10px 14px; margin-bottom:6px; font-size:13px; }
.notif-info    { background:#eff6ff; border-left:4px solid #2563eb; }
.notif-success { background:#f0fdf4; border-left:4px solid #16a34a; }
.notif-warning { background:#fffbeb; border-left:4px solid #f59e0b; }
.notif-error   { background:#fef2f2; border-left:4px solid #dc2626; }

/* A2A flow */
.a2a-flow { background:#0f172a; color:#e2e8f0; border-radius:12px; padding:16px 20px; font-family:monospace; font-size:12px; line-height:2; }
.a2a-arrow { color:#22c55e; }
.a2a-agent { color:#60a5fa; font-weight:700; }
.a2a-topic { color:#fbbf24; }

/* Output alignment */
.block-container { max-width: 1280px; }
.stMarkdown, .stMarkdown p, .stMarkdown li { text-align: left; }
.resp-box, .hist-row, .cand-card, .qmsg, .a2a-flow, .chat-agent { text-align: left; }
.chat-wrap { clear: both; overflow: auto; width: 100%; }
.chat-user { float: right; }
.chat-agent { float: left; }
div[data-testid="column"] { min-width: 0; }

div[data-testid="stForm"] { border:none !important; padding:0 !important; }
</style>""", unsafe_allow_html=True)

# ── Session defaults ──────────────────────────────────────────────────────────
_defs = {
    "logged_in": False, "username": "", "user_role": "", "user_name": "",
    "orch_chat": [], "coord_chat": [], "docs_chat": [], "wa_chat": [],
    "pending_email": None, "monitor_log": [], "hr_results": None,
    "uploaded_cvs": [], "drive_documents": [], "mcp_running": False,
    "system_start": time.time(), "wa_log": [],
    "db_hr_cvs": [], "orch_last_proc": None,
    "recruitment_wf_id": None,
    "recruitment_last": None,
    "hr_gmail_batch_id": None,
    "hr_gmail_last": None,
    "pending_hr_gmail_batch_id": None,
    "orch_finance_export_files": None,
}
for k, v in _defs.items():
    if k not in st.session_state:
        st.session_state[k] = v


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

# ── DB init ───────────────────────────────────────────────────────────────────
try:
    from database.sqlite_db import init_db
    init_db()
except Exception:
    pass

# ── MCP auto-start (local only; skip on Streamlit Cloud — set FYP_HOSTED=true in Secrets) ─
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

# ── Monitor logs ──────────────────────────────────────────────────────────────
try:
    from tools.gmail_auto_reply_monitor import get_pending_logs, is_running, start_monitor, stop_monitor
    for lg in get_pending_logs():
        st.session_state.monitor_log.append(lg)
except Exception:
    def is_running(): return False
    def start_monitor(): pass
    def stop_monitor(): pass

# ══════════════════════════════════════════════════════════════════════════════
# LOGIN PAGE
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    st.markdown("""
    <div style="display:flex;justify-content:center;align-items:center;min-height:85vh">
    <div style="background:white;border-radius:20px;padding:44px 52px;box-shadow:0 20px 60px rgba(0,0,0,0.13);max-width:420px;width:100%;border:1px solid #e2e8f0">
        <div style="text-align:center;font-size:26px;font-weight:800;color:#1e293b;margin-bottom:4px">Office Automation Pro</div>
        <div style="text-align:center;font-size:13px;color:#64748b;margin-bottom:30px">Multi-Agent System - FYP v7.0</div>
    </div></div>""", unsafe_allow_html=True)

    col = st.columns([1,1.6,1])[1]
    with col:
        st.markdown("")
        username = st.text_input("Username", placeholder="admin · hr · finance · it · assistant · demo")
        password = st.text_input("Password", type="password", placeholder="Enter password")
        if st.button("Sign In", use_container_width=True):
            from config import USERS
            if username in USERS and USERS[username]["password"] == password:
                st.session_state.logged_in  = True
                st.session_state.username   = username
                st.session_state.user_role  = USERS[username]["role"]
                st.session_state.user_name  = USERS[username]["name"]
                try:
                    from database.sqlite_db import add_notification
                    add_notification(f"{USERS[username]['name']} logged in", f"Role: {USERS[username]['role']}", "info", "System")
                except Exception:
                    pass
                st.rerun()
            else:
                st.error("Invalid username or password")
        st.markdown("""<div style="background:#f8fafc;border-radius:10px;padding:12px 16px;margin-top:12px;font-size:12px;color:#64748b">
        <b>Demo credentials:</b><br>
        admin / admin123 &nbsp;|&nbsp; hr / hr123<br>
        finance / finance123 &nbsp;|&nbsp; it / it123<br>
        assistant / assistant123 &nbsp;|&nbsp; demo / demo123
        </div>""", unsafe_allow_html=True)
        if is_hosted_deploy():
            if not (OPENAI_API_KEY or "").strip():
                st.warning(
                    "Hosted deploy: add **OPENAI_API_KEY** to Streamlit **Secrets** (same names as `.env.example`). "
                    "Secrets are applied before the app loads."
                )
            st.caption(
                "Tip: in Streamlit Cloud **Secrets**, set **FYP_HOSTED** = `true` to disable the local MCP HTTP server."
            )
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN APP (after login)
# ══════════════════════════════════════════════════════════════════════════════

# ── Top header ────────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns([3, 1.5, 1])
with c1:
    mcp_b = "On" if st.session_state.mcp_running else "Off"
    mon_b = "On" if is_running() else "Off"
    from html import escape as _hesc
    unm = _hesc(st.session_state.user_name or "")
    rol = _hesc(st.session_state.user_role or "")
    st.markdown(
        f'<div class="main-header">'
        f"<div>"
        f'<div class="header-title">Office Automation Agents Pro</div>'
        f'<div class="header-sub">LangGraph | OpenAI | MCP | A2A | ChromaDB | SQLite | WhatsApp</div>'
        f"</div>"
        f'<div style="text-align:right;font-size:12px">'
        f"MCP: {mcp_b} &nbsp; Monitor: {mon_b}<br>"
        f'<span style="color:#94a3b8">{unm} ({rol})</span>'
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
with c3:
    if st.button("Logout", use_container_width=True):
        for k in ["logged_in","username","user_role","user_name"]:
            st.session_state[k] = "" if k != "logged_in" else False
        st.rerun()

# ── Tabs (RBAC: visible labels depend on role) ──────────────────────────────────
tab_labels = get_visible_tabs_for_role(st.session_state.user_role)
tabs = st.tabs(tab_labels)
_tab_idx = {name: i for i, name in enumerate(tab_labels)}
_pb = ROLE_PORTAL_BANNERS.get(st.session_state.user_role)
if _pb:
    st.markdown(_pb, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
_ti = _tab_idx.get("Dashboard")
if _ti is not None:
    with tabs[_ti]:
        try:
            from database.sqlite_db import get_dashboard_stats, get_notifications
            stats = get_dashboard_stats()
            notifs = get_notifications(unread_only=True)
        except Exception:
            stats = {"total_tasks":0,"total_emails":0,"total_candidates":0,"total_it_tickets":0,
                     "total_finance":0,"total_whatsapp":0,"unread_notifs":0,"recent_tasks":[],
                     "agent_usage":{}}
            notifs = []

        try:
            from database.vector_db import collection_stats
            vdb = collection_stats()
            total_vecs = sum(vdb.values()) if isinstance(vdb, dict) and "error" not in vdb else 0
        except Exception:
            vdb, total_vecs = {}, 0

        # Metrics row
        m = st.columns(6)
        labels = ["Tasks", "Emails", "Candidates", "IT tickets", "WhatsApp", "Vector rows"]
        vals = [
            stats.get("total_tasks", 0),
            stats.get("total_emails", 0),
            stats.get("total_candidates", 0),
            stats.get("total_it_tickets", 0),
            stats.get("total_whatsapp", 0),
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
                ("WhatsApp Agent", "agent-whatsapp-001"),
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
                        f'<div style="background:#e2e8f0;border-radius:4px;height:6px">'
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
            mcp_st = f"Running :{_port_disp}" if st.session_state.mcp_running else "Stopped"
            mon_st = "Active" if is_running() else "Stopped"
            vdb_st = "ChromaDB (has rows)" if total_vecs > 0 else "ChromaDB (empty)"
            from html import escape as _escu
            un = _escu(st.session_state.user_name or "")
            st.markdown(
                f'<div style="background:white;border:1px solid #e2e8f0;border-radius:10px;padding:12px 16px;font-size:13px">'
                f"<b>Uptime:</b> {uptime}s<br>"
                f"<b>MCP:</b> {mcp_st}<br>"
                f"<b>Monitor:</b> {mon_st}<br>"
                f"<b>DB:</b> SQLite connected<br>"
                f"<b>VectorDB:</b> {vdb_st}<br>"
                f"<b>User:</b> {un}"
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
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — ASSISTANT (single entry → orchestrator → sub-agents)
# ══════════════════════════════════════════════════════════════════════════════
_ti = _tab_idx.get("Assistant")
if _ti is not None:
    with tabs[_ti]:
        st.markdown(
            '<div class="sec-hdr sec-blue">Unified Assistant <span class="badge badge-a2a">Orchestrator</span> '
            '<span class="badge badge-mcp">MCP</span></div>',
            unsafe_allow_html=True,
        )
        _allow = get_role_orchestrator_allowlist(st.session_state.user_role)
        if _allow is None:
            st.info(
                "**One place for every task.** The orchestrator routes you to the right specialist when needed, "
                "or to a **natural assistant** for greetings, **today's date/time**, and follow-up chat that remembers "
                "this thread. **Gmail CV shortlist:** say e.g. *Fetch last 40 emails with CVs, select 5 candidates for "
                "Python and email them* — drafts are built and you **approve** before send (orange button or type **approve and send** in chat). Attach PDFs/DOCX for "
                "uploaded-CV recruitment; there say **email them** or **draft only** as needed."
            )
        else:
            st.warning(
                "**Department-scoped orchestrator (RBAC).** Allowed specialists: "
                f"**{', '.join(_allow)}** — plus **general** chat. **Gmail CV fetch + shortlist** works from one prompt "
                "when your role includes it (e.g. HR Manager, Office Assistant). **Emails are never sent until you approve** "
                "in the orange box below or with **approve and send** in chat."
            )

        orch_up = st.file_uploader(
            "Attach files (optional, PDF / TXT / DOCX)",
            accept_multiple_files=True,
            type=["pdf", "txt", "docx"],
            key="orch_files",
        )
        orch_attachments = []
        if orch_up:
            for f in orch_up:
                txt = _extract_text_from_uploaded_file(f)
                if txt.strip():
                    orch_attachments.append({"name": f.name, "content": txt})

        for entry in st.session_state.orch_chat:
            if entry["role"] == "user":
                st.markdown(f'<div class="chat-wrap"><div class="chat-user">{entry["content"]}</div></div>', unsafe_allow_html=True)
            else:
                badges = " ".join([f'<span class="badge badge-blue">{a}</span>' for a in entry.get("agents",[])])
                ms = entry.get("elapsed_ms", 0)
                st.markdown(f'<div class="chat-wrap"><div class="chat-agent">{badges} <small style="color:#94a3b8">({ms} ms)</small><br><br>{entry["content"]}</div></div>', unsafe_allow_html=True)
                pa = entry.get("per_agent") or {}
                if pa:
                    with st.expander("Per-agent results", expanded=False):
                        labels = {
                            "general": "Assistant (chat)",
                            "hr_gmail": "Gmail CV shortlist",
                            "it_support": "IT Support",
                            "email": "Email",
                            "hr": "HR",
                            "recruitment": "Recruitment",
                            "finance": "Finance",
                            "documents": "Documents",
                        }
                        for ag, txt in pa.items():
                            st.markdown(f"**{labels.get(ag, ag)}**")
                            st.markdown(str(txt)[:12000] + ("…" if len(str(txt)) > 12000 else ""))

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
                            label=f"⬇ {(fe.get('format') or 'file').upper()}",
                            data=fe.get("data") or b"",
                            file_name=fe.get("filename") or "export.bin",
                            mime=fe.get("mime_type") or "application/octet-stream",
                            key=f"orch_fin_dl_{i}",
                        )
                        st.caption(fe.get("filename", ""))

        with st.form("orch_form", clear_on_submit=True):
            inp = st.text_area("Your message", placeholder="Describe any task — IT, email, HR, finance, documents...", height=90)
            c1, c2 = st.columns([4, 1])
            with c1:
                sub = st.form_submit_button("Send (route to specialists)", use_container_width=True)
            with c2:
                use_llm = st.checkbox("LLM intent", value=True)

        if sub and inp.strip():
            dedupe = (inp.strip(), tuple((a["name"], len(a.get("content", ""))) for a in orch_attachments))
            if st.session_state.orch_last_proc == dedupe:
                st.caption("Same request was just processed; change the message or attachments to send again.")
            else:
                orch_hist: list = []
                for e in st.session_state.orch_chat[-14:]:
                    if e.get("role") == "user":
                        orch_hist.append({"role": "user", "content": e.get("content", "")})
                    elif e.get("role") == "agent":
                        orch_hist.append({"role": "assistant", "content": e.get("content", "")})
                st.session_state.orch_chat.append({"role": "user", "content": inp.strip()})
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
                        st.session_state.orch_chat.append({
                            "role": "agent",
                            "content": result["final_answer"],
                            "agents": result["agents_used"],
                            "elapsed_ms": result["elapsed_ms"],
                            "per_agent": result.get("responses") or {},
                        })
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

        _pbid = st.session_state.get("pending_hr_gmail_batch_id")
        if _pbid and st.session_state.user_role in ("Admin", "HR Manager", "Assistant"):
            st.divider()
            st.markdown(
                '<div style="background:#fff7ed;border:1px solid #fb923c;border-radius:12px;padding:14px 16px;margin-top:8px">'
                "<b>Human-in-the-loop — Gmail shortlist:</b> drafts are saved; <b>no emails sent</b> until you approve "
                "(button here or type <b>approve and send</b> in chat). "
                f"Batch <code>{_pbid}</code></div>",
                unsafe_allow_html=True,
            )
            h1, h2 = st.columns(2)
            with h1:
                if st.button("Approve & send interview emails (Gmail SMTP)", type="primary", key="asst_hitl_send"):
                    with st.spinner("Sending..."):
                        try:
                            from tools.hr_gmail_shortlist import approve_and_send_shortlist_batch

                            sr = approve_and_send_shortlist_batch(_pbid)
                            if sr.get("ok"):
                                st.success(f"Sent **{sr.get('emails_sent', 0)}** / {sr.get('total', 0)}.")
                                st.session_state.pending_hr_gmail_batch_id = None
                                st.json(sr.get("details", []))
                                st.rerun()
                            else:
                                st.error(sr.get("error", "Send failed."))
                                if sr.get("details"):
                                    st.json(sr["details"])
                        except Exception as ex:
                            st.error(str(ex))
            with h2:
                if st.button("Dismiss pending batch", key="asst_hitl_clear"):
                    st.session_state.pending_hr_gmail_batch_id = None
                    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — RECRUITMENT AI (multi-agent orchestration, HITL before send)
# ══════════════════════════════════════════════════════════════════════════════
_ti = _tab_idx.get("Recruitment AI")
if _ti is not None:
    with tabs[_ti]:
        st.markdown(
            '<div class="sec-hdr sec-purple">Multi-Agent Recruitment Orchestrator '
            '<span class="badge badge-a2a">parallel</span> '
            '<span class="badge badge-yellow">HITL</span></div>',
            unsafe_allow_html=True,
        )
        st.info(
            "Upload a **Job Description** (file or text) and **multiple CVs**. "
            "Agents parse CVs in parallel, analyze the JD, match, shortlist, and draft interview emails. "
            "**No email is sent** until you click **Approve send**."
        )
        st.caption(
            "Use **Assistant** with CV attachments for the same pipeline; add **email them** / **send interview invitation** "
            "to send from the Assistant, or use **Approve send** here to review every draft first."
        )

        rec_company = st.text_input("Company name", value="Our Company", key="rec_company")
        rec_role = st.text_input("Role title (optional; inferred from JD if empty)", value="", key="rec_role")
        rec_interview = st.text_input(
            "Interview schedule text",
            value="Tomorrow at 3:00 PM",
            key="rec_interview",
            help="Shown verbatim in drafts, e.g. 'Monday 2:00 PM' or 'Tomorrow at 3:00 PM'.",
        )
        rec_meeting = st.text_input(
            "Meeting / logistics note",
            value="We will send a calendar invite or video link after you confirm.",
            key="rec_meeting",
        )
        c_top, c_thr = st.columns(2)
        with c_top:
            rec_top_n = st.number_input("Shortlist size (top N)", min_value=1, max_value=25, value=5, key="rec_top")
        with c_thr:
            rec_min_score = st.number_input("Minimum match score", min_value=0, max_value=100, value=52, key="rec_min")

        jd_file = st.file_uploader("Job description file (optional)", type=["pdf", "docx", "txt"], key="rec_jd_file")
        jd_text = st.text_area("Job description (paste if no JD file)", height=120, key="rec_jd_text")

        cv_files = st.file_uploader(
            "Candidate CVs (PDF / DOCX / TXT, multiple)",
            accept_multiple_files=True,
            type=["pdf", "docx", "txt"],
            key="rec_cvs",
        )

        run_rec = st.button("Run recruitment pipeline", type="primary", use_container_width=True, key="rec_run")

        if run_rec:
            parts_jd = []
            if jd_text.strip():
                parts_jd.append(jd_text.strip())
            if jd_file:
                try:
                    jd_file.seek(0)
                    tj = _extract_text_from_uploaded_file(jd_file)
                    if tj.strip():
                        parts_jd.append(tj.strip())
                except Exception:
                    pass
            jd_combined = "\n\n".join(parts_jd).strip()
            cvs_list = []
            if cv_files:
                for f in cv_files:
                    try:
                        f.seek(0)
                        txt = _extract_text_from_uploaded_file(f)
                        cvs_list.append({"name": f.name, "content": txt or "", "file_name": f.name})
                    except Exception:
                        cvs_list.append({"name": f.name, "content": "", "file_name": f.name})

            if not jd_combined:
                st.error("Provide a job description (text and/or JD file).")
            elif not cvs_list:
                st.error("Upload at least one CV.")
            else:
                with st.spinner("Running parallel agents (CV parse ∥ JD) → match → shortlist → draft)..."):
                    try:
                        from recruitment.pipeline import run_recruitment_pipeline

                        out = run_recruitment_pipeline(
                            job_description=jd_combined,
                            cvs=cvs_list,
                            user_name=st.session_state.user_name,
                            company=rec_company,
                            role_title_hint=rec_role,
                            interview_when=rec_interview,
                            meeting_details=rec_meeting,
                            top_n=int(rec_top_n),
                            min_match_score=int(rec_min_score),
                        )
                        st.session_state.recruitment_last = out
                        if out.get("ok"):
                            st.session_state.recruitment_wf_id = out.get("workflow_id")
                            st.session_state.recruitment_persist_ok = out.get("workflow_persisted", True)
                            st.success(out.get("approval_message", "Pipeline completed."))
                            if out.get("workflow_persisted") is False:
                                st.error(
                                    "Workflow was **not saved** to the database (check `database/` folder permissions). "
                                    "**Approve send** cannot load drafts — fix the DB issue and run the pipeline again."
                                )
                        else:
                            st.error(out.get("error", "Pipeline failed."))
                    except Exception as e:
                        st.error(str(e))

        last = st.session_state.get("recruitment_last") or {}
        if last.get("ok") and last.get("email_drafts"):
            st.markdown("---")
            st.markdown("#### Human-in-the-loop — review drafts")
            st.warning(last.get("human_prompt", "Review drafts before sending."))
            st.caption(f"Workflow ID: `{st.session_state.get('recruitment_wf_id')}`")

            for i, d in enumerate(last.get("email_drafts") or [], 1):
                with st.expander(f"{i}. {d.get('candidate_name')} — score {d.get('match_score')} — sendable: {d.get('sendable')}"):
                    st.text(f"To: {d.get('recipient') or '(no email in CV — cannot send)'}")
                    st.text(f"Subject: {d.get('subject', '')}")
                    st.text_area("Body", value=d.get("body") or "", height=220, key=f"rec_draft_{i}", disabled=True)

            if st.button("Approve send (Gmail SMTP)", type="primary", key="rec_approve"):
                wf = st.session_state.get("recruitment_wf_id")
                last = st.session_state.get("recruitment_last") or {}
                drafts = last.get("email_drafts") or []
                persist_ok = st.session_state.get("recruitment_persist_ok", True)

                if not wf:
                    st.error("No workflow id; run the pipeline again.")
                else:
                    with st.spinner("Sending approved emails..."):
                        try:
                            from recruitment.pipeline import approve_and_send_workflow, send_recruitment_email_drafts

                            send_r: dict = {}
                            used_fallback = False

                            if persist_ok:
                                send_r = approve_and_send_workflow(wf)
                                err = send_r.get("error") or ""
                                if (not send_r.get("ok")) and last.get("workflow_id") == wf and drafts:
                                    if err == "Workflow not found." or "No drafts with valid recipient" in err:
                                        send_r = send_recruitment_email_drafts(drafts)
                                        used_fallback = True
                            else:
                                if last.get("workflow_id") == wf and drafts:
                                    send_r = send_recruitment_email_drafts(drafts)
                                    used_fallback = True
                                else:
                                    send_r = {"ok": False, "error": "Nothing to send; re-run the pipeline."}

                            if used_fallback and (send_r.get("ok") or send_r.get("partial")):
                                st.info("Sent using **session drafts** (database copy was missing or had no recipients).")

                            if send_r.get("ok"):
                                if send_r.get("partial"):
                                    st.warning(send_r.get("error", "Some emails failed to send."))
                                else:
                                    st.success(
                                        f"Sent **{send_r['send_results'].get('emails_sent', 0)}** / "
                                        f"{send_r['send_results'].get('total', 0)} email(s)."
                                    )
                                st.json(send_r.get("send_results", {}))
                            else:
                                st.error(send_r.get("error", "Send failed."))
                                if send_r.get("send_results"):
                                    st.json(send_r.get("send_results", {}))
                                st.caption(
                                    "Tip: set `GMAIL_EMAIL` and `GMAIL_APP_PASSWORD` in Windows environment variables "
                                    "or set `GMAIL_APP_PASSWORD` in your `.env` file with a fresh Gmail App Password (16 letters, spaces optional)."
                                )
                        except Exception as e:
                            st.error(str(e))

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — IT SUPPORT
# ══════════════════════════════════════════════════════════════════════════════
_ti = _tab_idx.get("IT Support")
if _ti is not None:
    with tabs[_ti]:
        st.caption(
            "Tip: for most tasks, use **Assistant** — the orchestrator routes to IT (and other agents) automatically."
        )
        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="sec-hdr sec-blue">💻 IT Support Agent</div>', unsafe_allow_html=True)
            it_name = st.text_input("Your Name", value=st.session_state.user_name, key="it_name")
            it_prob = st.text_area("Describe Your IT Problem", placeholder="e.g. WiFi not connecting, laptop freezes, can't login...", height=160)
            pri_col, btn_col = st.columns([1,2])
            with pri_col:
                priority = st.selectbox("Priority", ["Normal","High","Urgent"], key="it_pri")
            with btn_col:
                it_btn = st.button("🔍 Get Solution", use_container_width=True, key="it_btn")

            if it_btn and it_prob.strip():
                with st.spinner("🔄 IT Agent analyzing..."):
                    try:
                        from graph.it_graph import it_graph
                        result = it_graph.invoke({"user_name":it_name,"it_problem":it_prob})
                        sol = result.get("it_solution","")
                        tid = result.get("ticket_id","")
                        if tid:
                            st.success(f"✅ Ticket created: **{tid}**")
                        if result.get("it_handled"):
                            st.markdown(f'<div class="resp-box">{sol}</div>', unsafe_allow_html=True)
                        else:
                            st.warning(sol)
                    except Exception as e:
                        st.error(f"Error: {e}")

        with c2:
            st.markdown('<div class="sec-hdr sec-orange">📬 Auto-Reply Monitor</div>', unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            with b1:
                if st.button("▶️ Start Monitor", use_container_width=True, disabled=is_running(), key="mon_on"):
                    start_monitor(); st.rerun()
            with b2:
                if st.button("⏹️ Stop", use_container_width=True, disabled=not is_running(), key="mon_off"):
                    stop_monitor(); st.rerun()

            status_html = '<div style="background:#dcfce7;border:1px solid #16a34a;padding:8px 14px;border-radius:8px;margin:8px 0">🟢 <b>Auto-reply ACTIVE</b></div>' if is_running() else '<div style="background:#fef9c3;border:1px solid #ca8a04;padding:8px 14px;border-radius:8px;margin:8px 0">🟡 <b>Auto-reply OFF</b></div>'
            st.markdown(status_html, unsafe_allow_html=True)

            if st.session_state.monitor_log:
                with st.expander("📋 Activity Log", expanded=True):
                    for log in reversed(st.session_state.monitor_log[-20:]):
                        st.caption(log)

            st.markdown('<div class="sec-hdr" style="margin-top:14px">🎫 Recent IT Tickets</div>', unsafe_allow_html=True)
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

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — EMAIL
# ══════════════════════════════════════════════════════════════════════════════
_ti = _tab_idx.get("Email")
if _ti is not None:
    with tabs[_ti]:
        st.caption(
            "Tip: use **Assistant** for email-related tasks routed with other domains; this tab is for drafts, inbox, and confirm-send flows."
        )
        st.markdown('<div class="sec-hdr sec-teal">📧 Email Coordinator <span class="badge badge-a2a">A2A</span></div>', unsafe_allow_html=True)

        for entry in st.session_state.coord_chat:
            if entry["role"] == "user":
                st.markdown(f'<div class="chat-wrap"><div class="chat-user">👤 {entry["content"]}</div></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-wrap"><div class="chat-agent">📧 {entry["content"]}</div></div>', unsafe_allow_html=True)

        if st.session_state.pending_email:
            p = st.session_state.pending_email
            st.warning(f"**📧 Ready to Send**\n\n**To:** {p.get('name','')} `{p.get('email','')}`\n**Subject:** {p.get('subject','')}\n\n{p.get('body','')[:300]}...")
            cy, cn = st.columns(2)
            with cy:
                if st.button("✅ Confirm & Send", use_container_width=True, key="send_yes"):
                    try:
                        from tools.gmail_send import send_email
                        from database.sqlite_db import log_email
                        send_email({"recipient":p["email"],"subject":p["subject"],"body":p["body"]})
                        log_email("sent", __import__("config").GMAIL_EMAIL, p["email"], p["subject"], p["body"])
                        st.session_state.coord_chat.append({"role":"agent","content":f"✅ Email sent to {p.get('name',p['email'])}!"})
                        st.session_state.pending_email = None; st.rerun()
                    except Exception as e:
                        st.error(f"Send failed: {e}")
            with cn:
                if st.button("❌ Cancel", use_container_width=True, key="send_no"):
                    st.session_state.pending_email = None; st.rerun()

        with st.form("coord_form", clear_on_submit=True):
            coord_inp = st.text_area("Message", placeholder="'Email Ahmed about 3pm meeting' or 'Draft reply to Hassan about project delay'", height=80)
            coord_sub = st.form_submit_button("📤 Send", use_container_width=True)

        if coord_sub and coord_inp.strip():
            st.session_state.coord_chat.append({"role":"user","content":coord_inp.strip()})
            with st.spinner("🔄 Processing..."):
                try:
                    import re
                    from agents.auto_reply_agent import generate_reply
                    from tools.email_search import find_email_by_name
                    m = re.search(r'(?:email|send|message|contact|write to|notify)\s+([A-Za-z]+)', coord_inp, re.IGNORECASE)
                    if m:
                        tname    = m.group(1)
                        contacts = find_email_by_name(tname)
                        if contacts:
                            c        = contacts[0]
                            reply    = generate_reply({"email_content":coord_inp,"sender_name":st.session_state.user_name})
                            st.session_state.pending_email = {"name":c["name"],"email":c["email"],"subject":f"Message from {st.session_state.user_name}","body":reply.get("body",coord_inp)}
                            st.session_state.coord_chat.append({"role":"agent","content":f"📧 Found **{c['name']}** ({c['email']}). Drafted — please review and confirm."})
                        else:
                            st.session_state.coord_chat.append({"role":"agent","content":f"🔍 Could not find **{tname}**'s email. Please provide their email directly."})
                    else:
                        reply = generate_reply({"email_content":coord_inp,"sender_name":st.session_state.user_name})
                        st.session_state.coord_chat.append({"role":"agent","content":reply.get("body","")})
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        st.markdown('<div class="sec-hdr sec-teal" style="font-size:13px">📥 Read Inbox</div>', unsafe_allow_html=True)
        if st.button("📬 Fetch Latest Emails", key="fetch_emails"):
            with st.spinner("Connecting to Gmail..."):
                try:
                    from tools.gmail_read import read_emails
                    result = read_emails({})
                    for em in result.get("emails", []):
                        from html import escape as _esc

                        fn = _esc(em.get("from_name", "") or "")
                        fe = _esc(em.get("from_email", "") or "")
                        subj = _esc(em.get("subject", "") or "")
                        body_snip = _esc((em.get("body") or "")[:200])
                        st.markdown(
                            f'<div class="hist-row">'
                            f"<b>From:</b> {fn} &lt;{fe}&gt;&nbsp;&nbsp;"
                            f"<b>Subject:</b> {subj}<br>"
                            f'<small style="color:#64748b">{body_snip}...</small>'
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                    if not result.get("emails"):
                        st.info(f"📭 {result.get('email_error','No emails found.')}")
                except Exception as e:
                    st.error(f"Error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — HR
# ══════════════════════════════════════════════════════════════════════════════
_ti = _tab_idx.get("HR")
if _ti is not None:
    with tabs[_ti]:
        st.caption("Tip: **Assistant** routes HR questions and CV-style tasks to the HR / recruitment specialists automatically.")
        if st.session_state.user_role in ("HR Manager", "Admin"):
            st.markdown(
                '<div class="sec-hdr sec-teal" style="margin-top:0">📬 Gmail CV shortlist (IMAP → parse → match → HITL send)</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div style="background:#ecfeff;border:1px solid #06b6d4;border-radius:12px;padding:12px 16px;margin-bottom:12px;font-size:13px">'
                "<b>Operational workflow (not Q&amp;A-only):</b> scans your <b>configured Gmail inbox</b> for recent "
                "messages with <b>PDF/DOCX CVs</b>, ranks them against your criteria with <b>explainable dimensions</b>, "
                "writes interview drafts, saves a <b>SQLite batch record</b>, and sends <b>only after you approve</b>."
                "</div>",
                unsafe_allow_html=True,
            )
            hr_nl = st.text_area(
                "One-shot prompt (same wording as Assistant)",
                placeholder="e.g. Fetch last 40 emails with CVs and select 5 candidates for Python developer and email them — interview tomorrow 8am",
                height=90,
                key="hr_gmail_nl",
            )
            if st.button("Run from prompt", use_container_width=True, key="hr_gmail_nl_run") and hr_nl.strip():
                with st.spinner("Parsing prompt + IMAP + ranking..."):
                    try:
                        from tools.hr_gmail_shortlist import run_gmail_shortlist_from_user_prompt

                        out = run_gmail_shortlist_from_user_prompt(
                            user_message=hr_nl.strip(),
                            user_name=st.session_state.user_name,
                            user_role=st.session_state.user_role,
                        )
                        st.session_state.hr_gmail_last = out
                        if out.get("ok"):
                            st.session_state.hr_gmail_batch_id = out.get("batch_id")
                            st.session_state.pending_hr_gmail_batch_id = out.get("batch_id")
                            st.success(
                                f"**{len(out.get('drafts') or [])}** candidate(s) — batch `{out.get('batch_id')}` "
                                "(pending approval below)."
                            )
                            st.rerun()
                        else:
                            st.error(out.get("error", "Could not parse or run."))
                    except Exception as e:
                        st.error(str(e))
            g1, g2, g3 = st.columns(3)
            with g1:
                gm_scan = st.number_input("Inbox messages to scan", min_value=10, max_value=100, value=50, key="hr_gmail_scan")
            with g2:
                gm_top = st.number_input("Top candidates to keep", min_value=1, max_value=25, value=5, key="hr_gmail_top")
            with g3:
                gm_company = st.text_input("Company name", value="Our Company", key="hr_gmail_co")
            gm_role = st.text_input(
                "Role / JD criteria",
                value="Python developer: Python, REST APIs, SQL, teamwork, 2+ years.",
                key="hr_gmail_role",
            )
            gm_when = st.text_input("Interview time (shown in email)", value="Tomorrow at 08:00 AM", key="hr_gmail_when")
            if st.button("🔍 Scan Gmail & build shortlist", type="primary", use_container_width=True, key="hr_gmail_run"):
                with st.spinner("IMAP fetch + CV parse + JD match (parallel) — may take 1–3 minutes..."):
                    try:
                        from tools.hr_gmail_shortlist import run_gmail_shortlist_pipeline

                        out = run_gmail_shortlist_pipeline(
                            job_criteria=gm_role,
                            interview_when=gm_when,
                            company=gm_company,
                            user_name=st.session_state.user_name,
                            user_role=st.session_state.user_role,
                            max_messages=int(gm_scan),
                            top_n=int(gm_top),
                        )
                        st.session_state.hr_gmail_last = out
                        if out.get("ok"):
                            st.session_state.hr_gmail_batch_id = out.get("batch_id")
                            st.success(
                                f"Shortlist ready — **{len(out.get('drafts') or [])}** candidate(s). "
                                f"Batch `{out.get('batch_id')}` saved (pending send)."
                            )
                        else:
                            st.error(out.get("error", "Failed."))
                    except Exception as e:
                        st.error(str(e))

            last_g = st.session_state.get("hr_gmail_last") or {}
            if last_g.get("ok") and last_g.get("drafts"):
                st.markdown("---")
                st.markdown("#### Explainable shortlist (review before send)")
                st.caption(f"Role inferred: **{last_g.get('role_title', '')}** · Parsed attachments: **{last_g.get('attachments_parsed', 0)}**")
                for i, d in enumerate(last_g.get("drafts") or [], 1):
                    dim = d.get("dimensions") or {}
                    dim_txt = ""
                    if isinstance(dim, dict) and dim:
                        dim_txt = " · ".join(f"{k.replace('_', ' ')}: **{v}**" for k, v in dim.items())
                    with st.expander(
                        f"#{i} {d.get('candidate_name')} — match **{d.get('match_score')}** — "
                        f"to: {d.get('recipient') or '⚠ no email'}",
                        expanded=(i == 1),
                    ):
                        st.markdown(f"**Rationale:** {d.get('rationale', '')}")
                        if dim_txt:
                            st.markdown(f"**Dimensions:** {dim_txt}")
                        if d.get("strengths"):
                            st.markdown("**Strengths:** " + "; ".join(str(x) for x in d["strengths"][:8]))
                        if d.get("weaknesses"):
                            st.markdown("**Risks / gaps:** " + "; ".join(str(x) for x in d["weaknesses"][:6]))
                        st.text(f"Subject: {d.get('subject', '')}")
                        st.text_area("Body preview", value=(d.get("body") or "")[:2500], height=180, key=f"hr_gmail_body_{i}", disabled=True)

                bid = st.session_state.get("hr_gmail_batch_id")
                if st.button("✅ Approve & send interview emails (Gmail SMTP)", type="primary", key="hr_gmail_send"):
                    if not bid:
                        st.error("No batch id — run scan again.")
                    else:
                        with st.spinner("Sending approved emails..."):
                            try:
                                from tools.hr_gmail_shortlist import approve_and_send_shortlist_batch

                                sr = approve_and_send_shortlist_batch(bid)
                                if sr.get("ok"):
                                    st.success(f"Sent **{sr.get('emails_sent', 0)}** / {sr.get('total', 0)} email(s).")
                                    st.json(sr.get("details", []))
                                else:
                                    st.error(sr.get("error", "Send failed."))
                                    if sr.get("details"):
                                        st.json(sr["details"])
                            except Exception as e:
                                st.error(str(e))
            st.markdown("---")

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

# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — FINANCE
# ══════════════════════════════════════════════════════════════════════════════
_ti = _tab_idx.get("Finance")
if _ti is not None:
    with tabs[_ti]:
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
                "Generate documents (PDF / Excel / …)",
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

                                df = pd.read_csv(_io.StringIO(data_src))
                                if df.shape[1] >= 3:
                                    amt_col = df.columns[2]
                                    cat_col = df.columns[3] if df.shape[1] > 3 else df.columns[1]
                                    chart_df = df.groupby(cat_col)[amt_col].sum().reset_index()
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
                    with st.expander(f"📄 {dfile.name}", expanded=(idx == 0)):
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
                                st.caption(f"**{ct}** — could not build (check columns and numeric values).")
                            else:
                                st.plotly_chart(fig, use_container_width=True)
                        if want_ai:
                            with st.spinner(f"AI summary for {dfile.name}…"):
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
                            merged = bdf.merge(adf, on="Category").set_index("Category")
                            st.bar_chart(merged)
                        except Exception:
                            pass
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif fin_action == "Generate documents (PDF / Excel / …)":
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
                placeholder="Paste CSV rows, budget lines, invoice text, or notes…",
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
                    with st.spinner("LLM structuring + parallel export (PDF / Excel / …)…"):
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

                            q = instr or (merged_data[:800] + " — finance document export")
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

# ══════════════════════════════════════════════════════════════════════════════
# TAB 8 — DOCUMENTS
# ══════════════════════════════════════════════════════════════════════════════
_ti = _tab_idx.get("Documents")
if _ti is not None:
    with tabs[_ti]:
        st.caption("Tip: **Assistant** can route document Q&A; use this tab for Drive load, embeddings, and batch tools.")
        st.markdown('<div class="sec-hdr sec-teal">📂 Documents Agent <span class="badge badge-mcp">MCP</span> <span class="badge badge-purple">ChromaDB</span></div>', unsafe_allow_html=True)
        docs_user = st.text_input("Your Name", value=st.session_state.user_name, key="docs_user")

        lc1, lc2 = st.columns(2)
        with lc1:
            if st.button("☁️ Load from Google Drive", key="load_drive", use_container_width=True):
                with st.spinner("📂 Loading and reading Drive files..."):
                    try:
                        from tools.mcp_drive_client import DriveClient
                        client = DriveClient()
                        docs   = client.load_documents(max_results=50)
                        if docs:
                            st.session_state.drive_documents = docs
                            # Embed into ChromaDB
                            from database.vector_db import embed_documents
                            with st.spinner("🧠 Embedding into ChromaDB..."):
                                res = embed_documents(docs, "documents")
                            st.success(f"✅ Loaded {len(docs)} docs · Embedded {res.get('embedded',0)} into ChromaDB")
                            # Save metadata to SQLite
                            try:
                                from database.sqlite_db import get_session, DocumentMeta
                                s = get_session()
                                for d in docs:
                                    s.add(DocumentMeta(file_name=d.get("file",""), content_len=len(d.get("content","")), source="drive", embedded=True))
                                s.commit(); s.close()
                            except Exception:
                                pass
                        else:
                            files = client.list_files(max_results=50)
                            if files:
                                st.session_state.drive_documents = [{"file":f.get("name",""), "id":f.get("id",""), "content":""} for f in files]
                                st.warning(f"⚠️ Listed {len(files)} files but could not read content.")
                            else:
                                st.warning("No files found in Google Drive.")
                    except Exception as e:
                        st.error(f"Drive error: {e}")

        with lc2:
            up_docs = st.file_uploader("📁 Upload Files", accept_multiple_files=True, type=["pdf","txt","docx"], key="doc_up")
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
                st.success(f"✅ {len(st.session_state.drive_documents)} documents ready & embedded")

        if st.session_state.drive_documents:
            names = " | ".join(d["file"] for d in st.session_state.drive_documents[:5])
            extra = f" | +{len(st.session_state.drive_documents)-5} more" if len(st.session_state.drive_documents)>5 else ""
            st.markdown(f"**{len(st.session_state.drive_documents)} documents** | {names}{extra}")
            if st.button("🗑️ Clear", key="clr_docs"): st.session_state.drive_documents=[]; st.rerun()

        st.divider()
        docs_action = st.selectbox("Document Action", [
            "💬 Q&A (RAG via ChromaDB)","🔍 Search","📝 Summarize",
            "🔎 Extract Data","⚖️ Compare Two Docs","📊 Batch Analyze","📋 List All"
        ], key="docs_action")

        if docs_action.startswith("💬"):
            for entry in st.session_state.docs_chat:
                if entry["role"]=="user":
                    st.markdown(f'<div class="chat-wrap"><div class="chat-user">👤 {entry["content"]}</div></div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="chat-wrap"><div class="chat-agent">📂 {entry["content"]}</div></div>', unsafe_allow_html=True)
            with st.form("docs_qa", clear_on_submit=True):
                dq  = st.text_area("Question", placeholder="Ask anything about your documents...", height=80)
                dsb = st.form_submit_button("💬 Ask (RAG)", use_container_width=True)
            if dsb and dq.strip():
                st.session_state.docs_chat.append({"role":"user","content":dq.strip()})
                with st.spinner("🧠 Searching ChromaDB..."):
                    try:
                        from agents.documents_agent import answer_question_from_documents
                        ans = answer_question_from_documents(dq.strip(), st.session_state.drive_documents, docs_user)
                        st.session_state.docs_chat.append({"role":"agent","content":ans})
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif docs_action.startswith("🔍"):
            sq = st.text_input("Search query", key="doc_sq")
            if st.button("🔍 Search", key="doc_srch", use_container_width=True) and sq.strip():
                with st.spinner("Searching..."):
                    try:
                        from agents.documents_agent import search_documents
                        ans = search_documents(sq, st.session_state.drive_documents, docs_user)
                        st.markdown(f'<div class="resp-box resp-teal">{ans}</div>', unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif docs_action.startswith("📝"):
            if st.session_state.drive_documents:
                sel = st.selectbox("Select Document", [d["file"] for d in st.session_state.drive_documents], key="sum_sel")
                if st.button("📝 Summarize", key="sum_btn", use_container_width=True):
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

        elif docs_action.startswith("🔎"):
            ext_type = st.selectbox("Extract Type", ["all","dates","amounts","parties","clauses","contacts"], key="ext_t")
            if st.session_state.drive_documents:
                sel = st.selectbox("Select Document", [d["file"] for d in st.session_state.drive_documents], key="ext_sel")
                if st.button("🔎 Extract", key="ext_btn", use_container_width=True):
                    doc = next((d for d in st.session_state.drive_documents if d["file"]==sel), None)
                    if doc:
                        with st.spinner("Extracting..."):
                            try:
                                from agents.documents_agent import extract_data_from_document
                                ans = extract_data_from_document(doc["content"], ext_type, doc["file"])
                                st.markdown(f'<div class="resp-box resp-teal">{ans}</div>', unsafe_allow_html=True)
                            except Exception as e:
                                st.error(f"Error: {e}")

        elif docs_action.startswith("⚖️"):
            if len(st.session_state.drive_documents) >= 2:
                names = [d["file"] for d in st.session_state.drive_documents]
                cc1, cc2 = st.columns(2)
                with cc1: d1n = st.selectbox("Document 1", names, key="cmp1")
                with cc2: d2n = st.selectbox("Document 2", names, index=1, key="cmp2")
                if st.button("⚖️ Compare", key="cmp_btn", use_container_width=True):
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

        elif docs_action.startswith("📊"):
            bat = st.selectbox("Analysis Type", ["overview","financial","contracts","policies","compliance"], key="bat_t")
            if st.button("📊 Batch Analyze", key="bat_btn", use_container_width=True):
                with st.spinner(f"Analyzing {len(st.session_state.drive_documents)} documents..."):
                    try:
                        from agents.documents_agent import batch_analyze_documents
                        ans = batch_analyze_documents(st.session_state.drive_documents, bat)
                        st.markdown(f'<div class="resp-box resp-teal">{ans}</div>', unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif docs_action.startswith("📋"):
            if st.button("📋 List All", key="lst_btn", use_container_width=True):
                from agents.documents_agent import list_documents_summary
                st.markdown(f'<div class="resp-box resp-teal">{list_documents_summary(st.session_state.drive_documents)}</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 9 — WHATSAPP
# ══════════════════════════════════════════════════════════════════════════════
_ti = _tab_idx.get("WhatsApp")
if _ti is not None:
    with tabs[_ti]:
        st.caption("Inbound/outbound WhatsApp already uses the **orchestrator** in code; this tab sends the merged agent reply to Twilio.")
        st.markdown('<div class="sec-hdr sec-wa">💬 WhatsApp Integration <span class="badge badge-wa">Twilio</span></div>', unsafe_allow_html=True)

        # Twilio status
        wc1, wc2 = st.columns([2,1])
        with wc1:
            st.info("How it works: type a task; the Orchestrator runs agents and can send the reply to WhatsApp and optionally email. For inbound WhatsApp, run `python whatsapp/webhook.py` and expose it with ngrok.")
        with wc2:
            if st.button("🔌 Test Twilio Connection", use_container_width=True, key="test_twilio"):
                with st.spinner("Testing..."):
                    try:
                        from whatsapp.bot import test_connection
                        res = test_connection()
                        if res.get("success"):
                            st.success(f"✅ Connected: {res.get('account','')}")
                        else:
                            st.error(f"❌ {res.get('error','Failed')}")
                    except Exception as e:
                        st.error(f"Error: {e}")

        st.divider()

        # WhatsApp chat UI
        st.markdown('<div class="sec-hdr sec-wa" style="font-size:13px">📱 Send via WhatsApp</div>', unsafe_allow_html=True)

        wa_num = st.text_input("WhatsApp Number", value="+923462792937", placeholder="+923XXXXXXXXX", key="wa_num")
        wa_email = st.text_input("Also send to Email (optional)", placeholder="ahmed@example.com", key="wa_email")

        # Chat display
        for entry in st.session_state.wa_chat:
            if entry["role"] == "user":
                st.markdown(f'<div class="chat-wrap"><div class="wa-bubble-out">👤 {entry["content"]}</div></div>', unsafe_allow_html=True)
            else:
                agents_b = " ".join([f'<span class="badge badge-green">{a}</span>' for a in entry.get("agents",[])])
                wa_stat  = entry.get("wa_status","")
                em_stat  = entry.get("email_status","")
                stat_row = ""
                if wa_stat: stat_row += f'<br><small>📱 WhatsApp: {wa_stat}</small>'
                if em_stat: stat_row += f'<small> · 📧 Email: {em_stat}</small>'
                st.markdown(f'<div class="chat-wrap"><div class="wa-bubble-in">{agents_b}<br><br>{entry["content"]}{stat_row}</div></div>', unsafe_allow_html=True)

        with st.form("wa_form", clear_on_submit=True):
            wa_inp = st.text_area("Your message / task",
                placeholder="e.g. 'My laptop won't start, please resolve this issue and send to Ahmed'\nor 'Analyze our IT expenses and notify finance team'",
                height=100)
            wc_a, wc_b = st.columns([4,1])
            with wc_a: wa_sub = st.form_submit_button("📤 Send via Orchestrator + WhatsApp", use_container_width=True)
            with wc_b: also_email = st.checkbox("+ Email", value=bool(wa_email), key="wa_also_email")

        if wa_sub and wa_inp.strip():
            st.session_state.wa_chat.append({"role":"user","content":wa_inp.strip()})
            with st.spinner("🔄 Orchestrator processing + sending WhatsApp..."):
                try:
                    from whatsapp.bot import send_agent_response_to_whatsapp
                    result = send_agent_response_to_whatsapp(
                        user_input      = wa_inp.strip(),
                        recipient_number= wa_num,
                        also_email      = also_email and bool(wa_email),
                        email_address   = wa_email,
                        user_name       = st.session_state.user_name,
                    )
                    wa_r = result.get("whatsapp", {})
                    em_r = result.get("email", "")

                    wa_status = f"✅ Sent (SID: {wa_r.get('sid','')[:12]})" if wa_r and wa_r.get("success") else f"❌ {wa_r.get('error','Failed') if wa_r else 'Not sent'}"
                    em_status = f"✅ {em_r}" if em_r and "✅" in str(em_r) else (f"❌ {em_r}" if em_r else "")

                    st.session_state.wa_chat.append({
                        "role":         "agent",
                        "content":      result.get("agent_response",""),
                        "agents":       result.get("agents_used",[]),
                        "wa_status":    wa_status,
                        "email_status": em_status,
                    })

                    try:
                        from database.sqlite_db import add_notification
                        add_notification("WhatsApp message sent", f"To: {wa_num}", "success", "WhatsApp Agent")
                    except Exception:
                        pass
                    st.rerun()
                except Exception as e:
                    st.error(f"WhatsApp error: {e}")

        st.divider()

        # WhatsApp logs
        st.markdown('<div class="sec-hdr sec-wa" style="font-size:13px">WhatsApp logs</div>', unsafe_allow_html=True)
        try:
            from database.sqlite_db import get_session, WhatsAppLog
            s    = get_session()
            wlogs = s.query(WhatsAppLog).order_by(WhatsAppLog.timestamp.desc()).limit(10).all()
            s.close()
            if wlogs:
                for wl in wlogs:
                    dir_lbl = "OUT" if wl.direction == "outbound" else "IN"
                    badge = "green" if wl.status == "sent" else "red"
                    msg_preview = (wl.message or "")[:100]
                    ts = wl.timestamp.strftime("%Y-%m-%d %H:%M")
                    st.markdown(
                        f'<div class="hist-row">'
                        f'<b>{dir_lbl}</b> <b>{wl.direction.upper()}</b> &nbsp;'
                        f'<b>To:</b> {wl.to_number} &nbsp;'
                        f'<span class="badge badge-{badge}">{wl.status}</span><br>'
                        f'<small style="color:#64748b">{ts} | {wl.agents_used}</small><br>'
                        f"{msg_preview}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("No WhatsApp messages yet.")
        except Exception:
            st.caption("WhatsApp logs unavailable.")

        # Webhook instructions
        with st.expander("Setup incoming WhatsApp (webhook)"):
            st.markdown(
                "**To receive WhatsApp messages and auto-reply:**\n\n"
                "**Step 1** - Install ngrok from https://ngrok.com/download\n\n"
                "**Step 2** - In a terminal run: `python whatsapp/webhook.py`\n\n"
                "**Step 3** - In another terminal run: `ngrok http 5000` and copy the HTTPS URL.\n\n"
                "**Step 4** - Open Twilio WhatsApp sandbox settings in the Twilio console.\n\n"
                "**Step 5** - Set the webhook URL to `https://YOUR-NGROK-HOST/whatsapp`\n\n"
                "**Step 6** - From WhatsApp send `join <your-sandbox-word>` to the sandbox number.\n\n"
                "Inbound messages will then be processed by your agents."
            )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 10 — HISTORY
# ══════════════════════════════════════════════════════════════════════════════
_ti = _tab_idx.get("History")
if _ti is not None:
    with tabs[_ti]:
        st.markdown('<div class="sec-hdr">📋 Task History</div>', unsafe_allow_html=True)

        hist_filter = st.selectbox("Filter by source", ["All","ui","whatsapp","api"], key="hist_filter")
        try:
            from database.sqlite_db import get_task_history
            history = get_task_history(limit=50)
            if hist_filter != "All":
                history = [h for h in history if h.get("source") == hist_filter]

            if history:
                st.caption(f"Showing {len(history)} tasks")
                for h in history:
                    src_badge = {"ui":"badge-blue","whatsapp":"badge-wa","api":"badge-purple"}.get(h.get("source","ui"),"badge-blue")
                    with st.expander(f"#{h['id']} | {h['time']} | {h.get('user','')} | {h.get('agents','')}", expanded=False):
                        resp = h.get("response", "") or ""
                        tail = "..." if len(resp) > 500 else ""
                        body = (
                            f'<div class="hist-row">'
                            f'<span class="badge {src_badge}">{h.get("source", "ui").upper()}</span> '
                            f'<span class="badge badge-green">{h.get("role", "")}</span> '
                            f'<span style="font-size:12px;color:#64748b"> {h.get("elapsed", 0)}ms</span><br><br>'
                            f'<b>Input:</b> {h.get("input", "")}<br><br>'
                            f'<b>Agents:</b> {h.get("agents", "")}<br><br>'
                            f'<b>Response:</b><br>{resp[:500]}{tail}'
                            f"</div>"
                        )
                        st.markdown(body, unsafe_allow_html=True)
            else:
                st.info("No task history yet. Use the **Assistant** tab to send tasks.")
        except Exception as e:
            st.error(f"History error: {e}")

