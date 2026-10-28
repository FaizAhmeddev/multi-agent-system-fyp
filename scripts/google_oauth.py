"""One-time Google sign-in for Calendar, Gmail and Drive (shared consent, narrow scopes).

    1. In Google Cloud Console create an OAuth client of type "Desktop app", enable the
       Google Calendar API, Gmail API and Google Drive API, and download the client JSON.
    2. Save it as secrets/google_oauth_client.json (gitignored).
    3. Run:  .venv\\Scripts\\python scripts\\google_oauth.py
       A browser opens; approve access. The token is stored encrypted in data/google_token.enc.
    4. Restart calendar-mcp and workspace-mcp. They switch from sandbox to Google mode.

To go back to sandbox mode delete data/google_token.enc or set CALENDAR_MODE=sandbox /
WORKSPACE_MODE=sandbox.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp_servers.common import load_env  # noqa: E402

load_env()
from mcp_servers.google_common import run_consent_flow  # noqa: E402

if __name__ == "__main__":
    run_consent_flow()
