# 🏢 Office Automation Agents Pro — FYP Final v6.0

**Multi-Agent System** · LangGraph · OpenAI · MCP · A2A Protocol · Message Queue

---

## 🚀 Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Opens at **http://localhost:8501**

---

## 🏗️ Architecture

```
USER REQUEST
    │
    ▼
┌─────────────────────────────────────────────────────┐
│           ORCHESTRATOR (Intent Detection)            │
│   LLM-powered intent → publish tasks via A2A/MQ      │
└──────────────────────┬──────────────────────────────┘
                       │  Message Queue (A2A Protocol)
      ┌────────┬───────┼────────┬──────────┐
      ▼        ▼       ▼        ▼          ▼
   IT Agent  Email   HR Agent  Finance  Documents
   Agent     Agent            Agent    Agent
      │        │       │        │          │
      └────────┴───────┴────────┴──────────┘
                       │  MCP Tools
                       ▼
            ┌─────────────────────────┐
            │    MCP SERVER (:8765)   │
            │  Google Drive │ Gmail   │
            └─────────────────────────┘
```

---

## 🤖 Agents

| Agent | What it does |
|---|---|
| 🤖 **Orchestrator** | Intent detection → A2A routing to sub-agents |
| 💻 **IT Support** | Diagnoses & solves IT problems step-by-step |
| 📬 **Auto-Reply** | Monitors inbox and auto-replies using AI |
| 📧 **Email Coordinator** | Natural language → find contact → draft → send |
| 🧑‍💼 **HR Agent** | CV screening, interview questions, onboarding, policy Q&A, JD drafting |
| 💰 **Finance Agent** | Q&A, expense analysis, invoice summary, reports, budget vs actual |
| 📂 **Documents Agent** | Search, summarize, Q&A, extract, compare, batch analyze Drive docs |

---

## 📡 A2A Protocol

Each agent communicates through the **Message Queue**:

1. **Orchestrator** publishes a `task` message to the queue
2. **Sub-agents** consume their tasks and process them
3. **Sub-agents** publish `result` messages back to the queue
4. **Orchestrator** collects results and merges the final response

Message types: `task` · `result` · `status` · `broadcast`

---

## 🔌 MCP Server

The MCP (Model Context Protocol) HTTP server exposes tools (default `localhost:8765`; override with `MCP_SERVER_PORT` in `.env`):

| Tool | Description |
|---|---|
| `drive_list_files` | List Google Drive files |
| `drive_read_file` | Read a specific Drive file |
| `drive_search` | Search Drive by keyword |
| `gmail_read_inbox` | Read Gmail inbox |
| `gmail_send_email` | Send email via Gmail |
| `queue_stats` | Message queue statistics |
| `agent_status` | Registered agent IDs from config |

---

## ⚙️ Configuration

1. Copy `FYP_FINAL/.env.example` to `FYP_FINAL/.env`.
2. Set at least `OPENAI_API_KEY` and any integrations you use (Gmail, Twilio, etc.).

```env
OPENAI_API_KEY=sk-...
GMAIL_EMAIL=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

Do **not** commit `.env`. Demo login passwords default to `admin123` / `hr123` / … unless you set `FYP_PASSWORD_*` in `.env` (see `.env.example`).

For Google Drive (local OAuth):
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Enable **Google Drive API**
3. Create OAuth credentials → Download as `credentials.json`
4. Place `credentials.json` in the project root

---

## 📁 Project Structure

```
FYP_FINAL/
├── main.py                          # Entry point
├── config.py                        # Loads settings from .env
├── .env.example                     # Template for secrets (copy to .env)
├── requirements.txt
├── finance_drive_reader.py
│
├── Orchestrator/
│   └── orchestrator_brain.py        # A2A routing + intent detection
│
├── message_queue/
│   └── queue.py                     # In-memory pub/sub message queue
│
├── mcp_server/
│   └── server.py                    # MCP HTTP server + tools
│
├── agents/
│   ├── it_support_agent.py
│   ├── auto_reply_agent.py
│   ├── hr_agent.py
│   ├── finance_agent.py
│   └── documents_agent.py
│
├── graph/
│   ├── it_graph.py                  # LangGraph state machines
│   ├── hr_graph.py
│   ├── finance_graph.py
│   ├── documents_graph.py
│   └── email_graph.py
│
├── state/
│   ├── it_state.py                  # TypedDict state definitions
│   ├── hr_state.py
│   ├── finance_state.py
│   ├── documents_state.py
│   └── email_state.py
│
├── tools/
│   ├── gmail_send.py
│   ├── gmail_read.py
│   ├── email_search.py
│   ├── gmail_auto_reply_monitor.py
│   ├── cv_parser.py
│   ├── mcp_drive_client.py
│   └── email_memory_db.py
│
├── utils/
│   └── file_parser.py
│
└── ui/
    └── app.py                       # Streamlit UI (7 tabs)
```

---

## 🖥️ UI Tabs

1. **🏠 Dashboard** — System status, agent health, message queue live feed, MCP tools, architecture diagram
2. **🤖 Orchestrator** — Chat with the orchestrator — it routes to the right agents automatically
3. **💻 IT Support** — Describe an IT problem, get a step-by-step solution
4. **📧 Email** — Coordinate emails + auto-reply monitor
5. **🧑‍💼 HR Operations** — CV screening, interview questions, onboarding, JD drafting
6. **💰 Finance** — Q&A, expense analysis, invoices, reports, budget comparison
7. **📂 Documents** — Load Google Drive docs, then search/Q&A/summarize/extract/compare

---

## 🐛 Changes from V23 → V6.0 (FYP Final)

| What | Change |
|---|---|
| Orchestrator | Fully rebuilt with LLM-powered intent detection + A2A dispatch |
| Message Queue | New `message_queue/queue.py` — proper pub/sub A2A protocol |
| MCP Server | New `mcp_server/server.py` — HTTP MCP tool server on :8765 |
| Dashboard tab | New system overview with live queue feed + architecture diagram |
| Orchestrator tab | New chat UI with agent badge display + elapsed time |
| All agents | Fixed lazy imports (no module-level side effects) |
| HR Agent | Added `draft_job_description` function |
| UI | Complete rewrite — 7 tabs, professional styling, badges, metrics |
