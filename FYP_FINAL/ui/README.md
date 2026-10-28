# Workspace presentation

The UI stays on Streamlit. Navigation permissions, integrations and business
action handlers retain their existing behavior. Persistent browser authentication
is documented in [auth/README.md](../auth/README.md).

- `workspace.css`: authenticated palette, tokens, native widget styles, responsive shell.
- `theme.py`: shared page headers, local icons, Assistant empty state, suggestions,
  data-backed dashboard overview, and styling for existing Plotly figures.
- `auth.css` and `auth_pages.py`: independent authentication presentation.
- `icons/`: locally vendored Lucide 0.468.0 SVGs and upstream license.
- `monochrome.css`: centralized adaptive brand tokens (historical filename).
- `appearance.py`, `theme_switcher.js` and `theme_switcher.css`: isolated Sun/Moon
  control that selects the native Streamlit theme and persists the preference.

The default is dark mode (#090B12); light mode uses #F8FAFF and white cards.
Brand colors are Electric Blue #1265FF, Cyan #22C7FF and Deep Purple #5125C8.
Readable accent text uses lighter blue in dark mode and darker blue in light mode.
The main sign-in action uses a restrained blue/purple gradient; surfaces stay solid.
`branding.py` supplies transparent original-color and light-wordmark logo variants.
Native Streamlit theme selection also updates charts, tables, menus and dialogs.
Theme initialization never hides the page; component SVGs have explicit dimensions.

The authenticated stylesheet is injected **after** the auth gate, so login styling
is kept separate. Suggestions prefill the native composer; they never submit tasks.
Dashboard charts and activity rows use the existing statistics and task history.
Agent dots identify registered agents and do not claim live provider availability.
MCP and monitoring indicators keep using the existing service state functions.

Native theme configuration is mirrored in the repository-root and FYP_FINAL
`.streamlit/config.toml` files so root/cloud and local-directory launches agree.
Keep those two small configurations in sync when changing the native palette.
The launcher respects configuration instead of forcing the old light theme.
Streamlit 1.66.1 is the minimum tested UI runtime.

## Checks

From the repository root:

```powershell
python FYP_FINAL/scripts/test_auth_pages.py
python FYP_FINAL/scripts/test_workspace_theme.py
python FYP_FINAL/scripts/test_persistent_auth.py
python FYP_FINAL/scripts/test_auth_session.py
```

The UI was also rendered with an isolated SQLite QA database and disabled external
integrations. Verification covered all eight modules, all 20 HR/Finance/Documents
action views, empty/populated states, five role-specific navigation sets, attachment
preview, suggestion prefilling, native drawer/collapse behavior, CSV tables and
bar/pie generation with AI summaries disabled, and widths from 320 to 1920px.
WCAG A/AA axe checks passed on the eight populated desktop screens and the mobile
screens for all eight modules. This does not replace an independent accessibility
audit or live acceptance of external AI, email, Drive, or MCP integrations.
