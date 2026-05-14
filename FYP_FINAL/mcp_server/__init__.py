try:
    from .server import start_mcp_server, stop_mcp_server, is_mcp_running, call_mcp_tool
    __all__ = ["start_mcp_server", "stop_mcp_server", "is_mcp_running", "call_mcp_tool"]
except Exception:
    def start_mcp_server(*a, **kw): pass
    def stop_mcp_server(): pass
    def is_mcp_running(): return False
    def call_mcp_tool(name, params): return {"success": False, "error": "MCP unavailable"}
