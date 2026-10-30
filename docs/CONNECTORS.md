# Connectors: plug in any MCP server

AgentsMind can use **any** Model Context Protocol (MCP) server (Slack, WhatsApp, GitHub, Notion, a job
board, your own tool) without code changes. The built-in servers (finance-mcp, it-mcp, calendar-mcp,
workspace-mcp) stay as they are; connectors are added next to them.

## Add one

Settings > **Connectors (MCP)** (administrators) > pick a template or **Add connector**:

| Field | Meaning |
|---|---|
| Short name | id, lowercase (`slack`); its tools are called `slack.<tool>` |
| How it runs | **stdio**: a program on this computer (`npx`, `uvx`, `python ...`) or **http**: a Streamable HTTP URL |
| Environment / Headers | `NAME=value`; write secrets as `${NAME}` |
| Secret values | `NAME=value`, written to `.env` only, never to `connectors.json` |
| Words | words that send a request to it (`slack, channel`) |
| Who may use it | roles; admin always may |
| Tools to hide | tool names that are never registered |

**Save and connect** starts the server, lists its tools (`tools/list`) and shows them with their kind.
The same file can be edited by hand: `data/connectors.json` (templates: `config/connector_templates.json`).
Node.js (for `npx`) or uv (for `uvx`) must be installed for stdio servers that use them.

## What happens to a request

1. "Post *payroll is done* in the #hr channel on Slack" contains a connector word, so the
   **Connected apps** agent takes it.
2. The model sees the connector's tools (names, descriptions, JSON input schemas) and chooses one tool
   and its arguments at a time; arguments are checked against the schema (JSON Schema) and sent back to
   the model if wrong.
3. **Read** tools (MCP `readOnlyHint`, or names starting with `get_`, `list_`, `search_`, ...) run
   at once; results are untrusted data and are checked for prompt injection. Up to 4 steps.
4. **Every other tool needs approval**: the request becomes an approval card and runs only after a person
   approves it (destructive tools must be confirmed by typing the tool name).
5. Every call goes through the tool gateway (role check, per-agent allow-list, audit log), exactly like the
   built-in tools.

Sessions stay open (a stdio server is started once, not per request) and are reopened when a server
stops. Changing a connector reconnects it.

## Overrides (in connectors.json)

- `read_tools` / `write_tools`: force a tool's kind when a server's annotations are missing or wrong
- `blocked_tools`: never expose these tools
- `guess_read_by_name`: `false` to treat every tool without `readOnlyHint` as needing approval
- `timeout_seconds`: per call (default 60)
