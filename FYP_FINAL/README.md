# Legacy prototype (reference only)

This folder is the original FYP prototype that AgentsMind replaces. It is kept so the
characterization tests in `tests/characterization/` can pin, and then deliberately flip,
its behaviour (see the `legacy_bug` ledger in `CHANGELOG.md`).

- The Streamlit UI (`ui/`, `main.py`, `run.bat`, `run.ps1`, `.streamlit/`) was removed in
  Phase 4. The AgentsMind web app in `frontend/` replaces it.
- Its prompts were ported to `backend/agentsmind/agents/ported.py`; its agents, queue, MCP
  server and tools are superseded by `backend/agentsmind/`, `mcp_servers/` and
  `external_systems/`.
- Do not run it in production. Its database file and logs are untracked (see the root
  `.gitignore`).

Start AgentsMind instead: see the root `README.md`.
