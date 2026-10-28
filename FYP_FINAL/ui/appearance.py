"""Shared color system and the native Streamlit appearance switcher."""
from pathlib import Path
import streamlit as st
import streamlit.components.v2 as components

_ROOT = Path(__file__).parent
_switcher = components.component(
    "office_appearance", isolate_styles=True,
    html='''<div class="oa-theme-switcher"><button id="oa-theme-toggle" type="button" role="switch" aria-checked="false" aria-label="Switch to Light mode">
<svg width="16" height="16" data-icon="moon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M20.5 13a8.5 8.5 0 0 1-9.5-9.5A8.5 8.5 0 1 0 20.5 13Z"/></svg><span class="theme-label">Dark</span>
<svg width="16" height="16" data-icon="sun" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></svg>
</button></div>''',
    css=(_ROOT / "theme_switcher.css").read_text(encoding="utf-8"),
    js=(_ROOT / "theme_switcher.js").read_text(encoding="utf-8"),
)


def init_appearance() -> None:
    """Run before either auth or workspace content. Native theme persists locally."""
    css = (_ROOT / "monochrome.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    _switcher(key="office_appearance", height=0)
