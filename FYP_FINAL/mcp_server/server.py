"""
MCP_SERVER/SERVER.PY
====================
Model Context Protocol (MCP) Server

Exposes tools that agents can call:
  - drive_list_files      → list Google Drive files
  - drive_read_file       → read a specific file
  - drive_search          → search Drive by query
  - gmail_read_inbox      → read Gmail inbox
  - gmail_send_email      → send an email
  - agent_status          → list registered agent IDs from config
  - queue_stats           → message queue statistics

This is a simplified MCP implementation using HTTP.
In production, this would be a full MCP-compliant server.
"""

import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Tools registry
_TOOLS = {}


def mcp_tool(name: str, description: str, input_schema: dict):
    """Decorator to register a function as an MCP tool."""
    def decorator(fn):
        _TOOLS[name] = {
            "name":        name,
            "description": description,
            "inputSchema": input_schema,
            "handler":     fn,
        }
        return fn
    return decorator


# ── Tool Implementations ─────────────────────────────────────────────────────

@mcp_tool(
    name="drive_list_files",
    description="List files in Google Drive, optionally filtered by folder or type",
    input_schema={
        "type": "object",
        "properties": {
            "folder": {"type": "string", "description": "Folder name (optional)"},
            "file_type": {"type": "string", "description": "pdf, docx, etc (optional)"},
            "max_results": {"type": "integer", "default": 20}
        }
    }
)
def drive_list_files(params: dict) -> dict:
    try:
        from tools.mcp_drive_client import DriveClient
        client = DriveClient()
        folder_name = params.get("folder") or ""
        files = client.list_files(query=folder_name, max_results=params.get("max_results", 20))
        return {"success": True, "files": files, "count": len(files)}
    except Exception as e:
        return {"success": False, "error": str(e), "files": []}


@mcp_tool(
    name="drive_read_file",
    description="Read the content of a specific file from Google Drive by file ID or name",
    input_schema={
        "type": "object",
        "properties": {
            "file_id":   {"type": "string"},
            "file_name": {"type": "string"},
        }
    }
)
def drive_read_file(params: dict) -> dict:
    try:
        from tools.mcp_drive_client import DriveClient
        client = DriveClient()
        content = client.read_file(
            file_id=params.get("file_id"),
            file_name=params.get("file_name"),
        )
        return {"success": True, "content": content}
    except Exception as e:
        return {"success": False, "error": str(e), "content": ""}


@mcp_tool(
    name="drive_search",
    description="Search Google Drive documents by keyword or phrase",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "default": 10}
        },
        "required": ["query"]
    }
)
def drive_search(params: dict) -> dict:
    try:
        from tools.mcp_drive_client import DriveClient
        client = DriveClient()
        results = client.search_files(query=params["query"], max_results=params.get("max_results", 10))
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e), "results": []}


@mcp_tool(
    name="gmail_read_inbox",
    description="Read recent emails from Gmail inbox",
    input_schema={
        "type": "object",
        "properties": {
            "max_emails": {"type": "integer", "default": 5},
            "unread_only": {"type": "boolean", "default": False}
        }
    }
)
def gmail_read_inbox(params: dict) -> dict:
    try:
        from tools.gmail_read import read_emails
        state = {}
        result = read_emails(state)
        return {"success": True, "emails": result.get("emails", [])}
    except Exception as e:
        return {"success": False, "error": str(e), "emails": []}


@mcp_tool(
    name="gmail_send_email",
    description="Send an email via Gmail",
    input_schema={
        "type": "object",
        "properties": {
            "recipient": {"type": "string"},
            "subject":   {"type": "string"},
            "body":      {"type": "string"},
        },
        "required": ["recipient", "subject", "body"]
    }
)
def gmail_send_email(params: dict) -> dict:
    try:
        from tools.gmail_send import send_email
        send_email(params)
        return {"success": True, "message": f"Email sent to {params['recipient']}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp_tool(
    name="queue_stats",
    description="Get message queue statistics for all agents",
    input_schema={"type": "object", "properties": {}}
)
def queue_stats(params: dict) -> dict:
    from message_queue import message_queue
    return {
        "success": True,
        "stats":   message_queue.get_stats(),
        "history": message_queue.get_history(limit=20),
    }


@mcp_tool(
    name="agent_status",
    description="List registered agent IDs and roles from application config",
    input_schema={"type": "object", "properties": {}},
)
def agent_status(params: dict) -> dict:
    try:
        from config import AGENT_IDS
        return {"success": True, "agents": dict(AGENT_IDS), "count": len(AGENT_IDS)}
    except Exception as e:
        return {"success": False, "error": str(e), "agents": {}}


# ── HTTP Handler ─────────────────────────────────────────────────────────────

class MCPHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/tools":
            tools_list = [
                {"name": t["name"], "description": t["description"],
                 "inputSchema": t["inputSchema"]}
                for t in _TOOLS.values()
            ]
            self._send_json({"tools": tools_list})
        elif parsed.path == "/health":
            self._send_json({"status": "ok", "tools_count": len(_TOOLS)})
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            req = json.loads(body)
        except Exception:
            self._send_json({"error": "Invalid JSON"}, 400)
            return

        parsed = urlparse(self.path)
        if parsed.path == "/call":
            tool_name = req.get("name")
            params    = req.get("params", {})
            if tool_name not in _TOOLS:
                self._send_json({"error": f"Tool '{tool_name}' not found"}, 404)
                return
            try:
                result = _TOOLS[tool_name]["handler"](params)
                self._send_json({"result": result})
            except Exception as e:
                self._send_json({"result": {"success": False, "error": str(e)}})
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


# ── Server Lifecycle ─────────────────────────────────────────────────────────

_server_thread: threading.Thread = None
_httpd: HTTPServer = None


def start_mcp_server(host: str | None = None, port: int | None = None):
    global _server_thread, _httpd
    if _server_thread and _server_thread.is_alive():
        return  # already running

    bind_host, bind_port = host, port
    if bind_host is None or bind_port is None:
        try:
            from config import MCP_SERVER_HOST, MCP_SERVER_PORT
            if bind_host is None:
                bind_host = MCP_SERVER_HOST
            if bind_port is None:
                bind_port = MCP_SERVER_PORT
        except Exception:
            if bind_host is None:
                bind_host = "localhost"
            if bind_port is None:
                bind_port = 8765

    def _run():
        global _httpd
        try:
            _httpd = HTTPServer((bind_host, bind_port), MCPHandler)
            _httpd.serve_forever()
        except Exception:
            pass

    _server_thread = threading.Thread(target=_run, daemon=True)
    _server_thread.start()
    time.sleep(0.5)  # brief warm-up


def stop_mcp_server():
    global _httpd
    if _httpd:
        _httpd.shutdown()


def is_mcp_running() -> bool:
    return _server_thread is not None and _server_thread.is_alive()


def call_mcp_tool(tool_name: str, params: dict) -> dict:
    """
    Call an MCP tool directly (in-process, no HTTP).
    Used by agents internally.
    """
    if tool_name not in _TOOLS:
        return {"success": False, "error": f"Tool '{tool_name}' not found"}
    try:
        return _TOOLS[tool_name]["handler"](params)
    except Exception as e:
        return {"success": False, "error": str(e)}
