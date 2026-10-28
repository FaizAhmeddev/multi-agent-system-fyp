"""Presentation helpers for the authenticated Streamlit workspace.

No service calls or permission decisions belong here. Lucide SVGs are vendored
locally (0.468.0, ISC license in icons/LICENSE), so icons work offline.
"""
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import quote

import streamlit as st

_ROOT = Path(__file__).parent
MODULES = {
    "Assistant": ("sparkles", "Your AI copilot", "One conversation. Every department. Bring your next task to life."),
    "Dashboard": ("layout-dashboard", "Automation overview", "A live view of your agents, activity, and connected workspace."),
    "IT Support": ("headset", "IT support", "Resolve issues faster with intelligent troubleshooting and support workflows."),
    "Email": ("mail", "Email workspace", "Keep conversations moving. Read, draft, and coordinate in one place."),
    "HR": ("users", "People & hiring", "From the first application to the first day. Make people operations flow."),
    "Finance": ("chart-no-axes-combined", "Finance workspace", "Turn financial data into clear answers, reports, and decisions."),
    "Documents": ("files", "Document intelligence", "Find the right information. Connect, search, and understand your documents."),
    "History": ("history", "Workspace activity", "Conversations, executions, and audit trails, all in one place."),
}


@lru_cache(maxsize=20)
def icon(name: str) -> str:
    svg = (_ROOT / "icons" / f"{name}.svg").read_text(encoding="utf-8")
    return svg.replace("<svg", '<svg aria-hidden="true" focusable="false"', 1)


def inject_workspace_theme() -> None:
    css = (_ROOT / "workspace.css").read_text(encoding="utf-8")
    for module, (name, _, _) in MODULES.items():
        svg = icon(name).replace('stroke="currentColor"', 'stroke="#000"')
        css += f'[class*="st-key-nav_{module.split()[0]}"] button::before {{ background-color:var(--muted); mask: url("data:image/svg+xml,{quote(svg)}") center/contain no-repeat; }}\n'
    for i, name in enumerate(("workflow", "mail", "users", "headset", "files"), 1):
        svg = icon(name).replace('stroke="currentColor"', 'stroke="#000"')
        css += f'.st-key-dashboard_metrics [data-testid="stColumn"]:nth-child({i}) [data-testid="stMetric"]::after {{ content:""; position:absolute; top:20px; right:16px; width:18px; height:18px; background-color:var(--muted); mask:url("data:image/svg+xml,{quote(svg)}") center/contain no-repeat; }}\n'
    attachment_svg = icon("paperclip").replace('stroke="currentColor"', 'stroke="#000"')
    css += f'.st-key-assistant_attachments summary::before {{ content:""; width:16px; height:16px; margin-right:8px; background-color:var(--muted); mask:url("data:image/svg+xml,{quote(attachment_svg)}") center/contain no-repeat; }}\n'
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def page_header(module: str, role: str, *, mcp: str, monitor: str) -> None:
    name, title, description = MODULES.get(module, MODULES["Assistant"])
    st.markdown(
        f'<div class="workspace-breadcrumb">WORKSPACE <span>/</span> {escape(module)}</div>'
        f'<div class="workspace-page-header"><div class="workspace-heading">'
        f'<div class="workspace-page-icon">{icon(name)}</div><div><h1>{title}</h1>'
        f'<p>{description}</p></div></div><div class="workspace-context">'
        f'<span class="role-chip">{icon("shield-check")}{escape(role)}</span>'
        f'<div class="workspace-services">{mcp} {monitor}</div></div></div>',
        unsafe_allow_html=True,
    )


def assistant_empty_state(name: str) -> None:
    first_name = (name or "there").split()[0]
    st.markdown(
        f'<div class="copilot-empty"><div class="copilot-emblem">{icon("sparkles")}</div>'
        '<div class="copilot-eyebrow">YOUR WORKDAY, SIMPLIFIED</div>'
        f'<h2>What can we take off your plate, {escape(first_name)}?</h2>'
        '<p>Start with an idea. Your assistant finds the right agents<br class="desktop-break">'
        ' and brings the work together.</p></div>', unsafe_allow_html=True,
    )


def configuration_notice(message: str) -> None:
    """Keep the missing-key warning visible, with full setup guidance on demand."""
    st.markdown(
        '<details class="configuration-notice"><summary><span class="notice-dot"></span>'
        '<span>AI features need an OpenAI API key</span><span class="notice-action">Setup details</span></summary>'
        f'<p>{escape(message).replace(chr(10), "<br>")}</p></details>',
        unsafe_allow_html=True,
    )


def _prefill_composer(prompt: str) -> None:
    st.session_state["workspace_composer"] = prompt


def suggested_prompts(allowed: list[str] | None) -> None:
    choices = [("Explore capabilities", "What can you help me with?", "sparkles")]
    options = [
        ("Understand a document", "Help me find and summarize a document", "files", "documents"),
        ("Draft an email", "Help me draft a professional email", "mail", "email"),
        ("Review my expenses", "Help me analyze my expenses", "chart-no-axes-combined", "finance"),
        ("Plan an onboarding", "Help me build an onboarding checklist", "users", "hr"),
        ("Troubleshoot an issue", "Help me troubleshoot an IT issue", "headset", "it_support"),
    ]
    for title, prompt, name, agent in options:
        if allowed is None or agent in allowed:
            choices.append((title, prompt, name))
        if len(choices) == 3:
            break
    with st.container(key="copilot_suggestions"):
        for col, (title, prompt, _) in zip(st.columns(len(choices)), choices):
            with col:
                st.button(f"{title}  ↗", key=f"suggest_{title}", use_container_width=True,
                          on_click=_prefill_composer, args=(prompt,),
                          help="Adds a suggested task to the composer. Review it before sending.")


def style_figure(figure) -> None:
    """Style an existing chart without changing its traces, data or calculations."""
    # Transparent surfaces and unset text colors let Streamlit's native theme
    # update charts instantly, without submitting forms or rerunning AI work.
    palette = ["#1265ff", "#22c7ff", "#8257e5", "#5125c8", "#5595ff"]
    figure.update_layout(
        template=None, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", size=14, color=None), colorway=palette,
        margin=dict(l=28, r=28, t=56, b=36),
    )
    for index, trace in enumerate(figure.data):
        if trace.type == "pie":
            trace.marker.colors = palette
        elif hasattr(trace, "marker"):
            color = trace.marker.color
            if color is None or isinstance(color, str):
                trace.marker.color = palette[index % len(palette)]
            else:
                trace.marker.colorscale = [[0, "#5125c8"], [0.5, "#1265ff"], [1, "#22c7ff"]]
        if hasattr(trace, "line") and trace.line.color:
            trace.line.color = palette[index % len(palette)]


def activity_overview(stats: dict) -> None:
    """Dashboard visualizations use the same persisted statistics as existing KPIs."""
    with st.container(key="activity_overview"):
        left, right = st.columns([1, 1.2], gap="large")
        with left:
            st.markdown('<div class="sec-hdr">Agent workload <span class="badge">Recorded activity</span></div>', unsafe_allow_html=True)
            usage = stats.get("agent_usage") or {}
            if usage:
                largest = max(usage.values()) or 1
                for name, count in sorted(usage.items(), key=lambda row: row[1], reverse=True):
                    width = max(0, min(100, float(count) / largest * 100))
                    st.markdown(
                        f'<div class="workload-row"><div><span>{escape(str(name))}</span><b>{int(count)}</b></div>'
                        f'<div class="workload-track" role="img" aria-label="{escape(str(name))}: {int(count)} recorded calls">'
                        f'<span style="width:{width}%"></span></div></div>', unsafe_allow_html=True,
                    )
            else:
                st.markdown('<div class="workspace-empty-card">No agent activity yet.<span>Completed work will appear here as you use your workspace.</span></div>', unsafe_allow_html=True)
        with right:
            st.markdown('<div class="sec-hdr">Recent automations <span class="badge badge-teal">Task history</span></div>', unsafe_allow_html=True)
            recent = stats.get("recent_tasks") or []
            if recent:
                for task in recent[:5]:
                    title = str(task.get("input") or task.get("user_input") or "Automation task")
                    agent = str(task.get("agents") or "Assistant")
                    timestamp = str(task.get("time") or "")
                    st.markdown(
                        f'<div class="activity-row"><div class="activity-icon">{icon("workflow")}</div>'
                        f'<div><strong>{escape(title[:140])}</strong><span>{escape(agent)} · {escape(timestamp)}</span></div></div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.markdown('<div class="workspace-empty-card">Your next task starts something.<span>Ask the Assistant to get started. Recent executions will appear here.</span></div>', unsafe_allow_html=True)
