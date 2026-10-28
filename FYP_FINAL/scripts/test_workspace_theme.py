"""Offline presentation regressions; no authentication, DB or integrations used."""
from pathlib import Path
import sys
import unittest

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def preview(body):
    return AppTest.from_string(
        'import sys\nimport streamlit as st\nsys.path.insert(0, ' + repr(str(ROOT)) + ')\n'
        'from ui.theme import *\n' + body
    ).run()


class WorkspaceThemeTests(unittest.TestCase):
    def test_department_suggestions_follow_allowed_agents(self):
        app = preview('suggested_prompts(["finance"])\nst.chat_input("Message", key="workspace_composer")')
        self.assertFalse(app.exception)
        self.assertEqual([b.label for b in app.button], ["Explore capabilities  ↗", "Review my expenses  ↗"])

    def test_suggestion_prefills_without_submitting(self):
        app = preview('suggested_prompts(["finance"])\nmessage=st.chat_input("Message", key="workspace_composer")\nif message: st.error("Unexpected submission")')
        app.button(key="suggest_Review my expenses").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)

    def test_user_names_and_statistics_are_escaped(self):
        app = preview('assistant_empty_state("<script>alert(1)</script>")\nactivity_overview({"agent_usage":{"<script>":2},"recent_tasks":[{"input":"<img onerror=alert(1)>","agents":"<unsafe>","time":"12:00"}]})')
        self.assertFalse(app.exception)
        html = '\n'.join(m.value for m in app.markdown)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img onerror', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('2 recorded calls', html)

    def test_empty_overview_does_not_invent_activity(self):
        app = preview('activity_overview({})')
        self.assertFalse(app.exception)
        html = '\n'.join(m.value for m in app.markdown)
        self.assertIn('No agent activity yet.', html)
        self.assertIn('Your next task starts something.', html)
        self.assertNotIn('workload-track', html)

    def test_chart_theme_preserves_data(self):
        import plotly.graph_objects as go
        from ui.theme import style_figure
        fig = go.Figure(go.Bar(x=['HR', 'IT'], y=[2, 4]))
        before = (tuple(fig.data[0].x), tuple(fig.data[0].y))
        style_figure(fig)
        self.assertEqual((tuple(fig.data[0].x), tuple(fig.data[0].y)), before)
        self.assertEqual(fig.data[0].marker.color, "#1265ff")
        self.assertEqual(fig.layout.paper_bgcolor, 'rgba(0,0,0,0)')

    def test_local_icons_and_all_module_headers(self):
        from ui.theme import MODULES, icon
        self.assertEqual(len(MODULES), 8)
        for name, _, _ in MODULES.values():
            self.assertIn('aria-hidden="true"', icon(name))
        app = preview('page_header("Assistant", "<Admin>", mcp="", monitor="")')
        self.assertIn('&lt;Admin&gt;', app.markdown[0].value)
        self.assertFalse(app.exception)


if __name__ == '__main__':
    unittest.main()
