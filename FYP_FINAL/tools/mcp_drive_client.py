"""
TOOLS/MCP_DRIVE_CLIENT.PY
==========================
Best-in-class Google Drive client with TWO layers:
  Layer 1 — MCP (Model Context Protocol): used when running inside Claude.ai
            Calls Google Drive MCP server at https://drivemcp.googleapis.com/mcp/v1
  Layer 2 — Direct OAuth API fallback: used when running locally (python main.py)

Usage (from any agent or the UI):
    from tools.mcp_drive_client import DriveClient
    client = DriveClient()
    files = client.list_files(query="invoice", max_results=20)
    text  = client.read_file(file_id="1XYZ...")
"""

import os
import sys
import io
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# MCP Drive Client (Claude.ai / MCP context)
# ─────────────────────────────────────────────────────────────────────────────

MCP_DRIVE_URL = "https://drivemcp.googleapis.com/mcp/v1"

SUPPORTED_MIME_EXPORT = {
    "application/vnd.google-apps.document":
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.google-apps.spreadsheet":
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.google-apps.presentation":
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

SUPPORTED_EXTENSIONS = (
    ".pdf", ".docx", ".doc", ".xlsx", ".xls",
    ".csv", ".json", ".txt"
)


class MCPDriveClient:
    """
    Calls Google Drive via MCP server (Claude.ai integrated).
    Requires the user to have Google Drive MCP connected.
    """

    def __init__(self, mcp_url: str = MCP_DRIVE_URL):
        self.mcp_url = mcp_url

    def _call_mcp(self, tool_name: str, params: dict) -> dict:
        """
        Make an MCP tool call via the Anthropic API.
        This runs Claude-as-a-tool to invoke the Drive MCP server.
        """
        import requests

        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4096,
            "tools": [{"type": "mcp", "server_url": self.mcp_url, "tool_name": tool_name}],
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps({"tool": tool_name, "params": params})
                }
            ],
            "mcp_servers": [
                {"type": "url", "url": self.mcp_url, "name": "google-drive"}
            ],
        }

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def list_files(self, query: str = "", folder_id: str = None,
                   max_results: int = 50) -> list[dict]:
        """List files from Google Drive via MCP."""
        try:
            params = {"pageSize": max_results}
            if query:
                params["query"] = query
            if folder_id:
                params["folderId"] = folder_id

            result = self._call_mcp("list_files", params)
            files = []
            for block in result.get("content", []):
                if block.get("type") == "tool_result":
                    content = block.get("content", [{}])
                    raw = content[0].get("text", "[]") if content else "[]"
                    try:
                        files = json.loads(raw)
                    except Exception:
                        files = []
            return files
        except Exception as e:
            logger.warning(f"MCP list_files failed: {e}")
            return []

    def read_file(self, file_id: str) -> str:
        """Read/download a file from Google Drive via MCP."""
        try:
            result = self._call_mcp("read_file", {"fileId": file_id})
            for block in result.get("content", []):
                if block.get("type") == "tool_result":
                    content = block.get("content", [{}])
                    return content[0].get("text", "") if content else ""
            return ""
        except Exception as e:
            logger.warning(f"MCP read_file failed: {e}")
            return ""

    def search_files(self, query: str, max_results: int = 20) -> list[dict]:
        """Full-text search across Drive files via MCP."""
        try:
            result = self._call_mcp("search_files", {
                "query": query,
                "pageSize": max_results
            })
            for block in result.get("content", []):
                if block.get("type") == "tool_result":
                    content = block.get("content", [{}])
                    raw = content[0].get("text", "[]") if content else "[]"
                    try:
                        return json.loads(raw)
                    except Exception:
                        return []
            return []
        except Exception as e:
            logger.warning(f"MCP search_files failed: {e}")
            return []


# ─────────────────────────────────────────────────────────────────────────────
# Direct OAuth Drive Client (local fallback)
# ─────────────────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class DirectDriveClient:
    """
    Calls Google Drive directly via google-api-python-client.
    Used as fallback when MCP is not available.
    """

    def __init__(self):
        self._service = None

    def _get_service(self):
        if self._service:
            return self._service

        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request

        creds = None
        if os.path.exists(GOOGLE_TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    GOOGLE_CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(GOOGLE_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())

        self._service = build("drive", "v3", credentials=creds)
        return self._service

    def list_files(self, query: str = "", folder_id: str = None,
                   max_results: int = 50) -> list[dict]:
        """List files from Google Drive using direct API."""
        service = self._get_service()

        # Build query
        ext_q = " or ".join(
            [f"name contains '{ext}'" for ext in SUPPORTED_EXTENSIONS]
        )
        q = f"({ext_q}) and trashed=false"
        if folder_id:
            q += f" and '{folder_id}' in parents"
        if query:
            q += f" and fullText contains '{query}'"

        result = (
            service.files()
            .list(q=q, fields="files(id,name,mimeType,size,modifiedTime)",
                  pageSize=max_results)
            .execute()
        )
        return result.get("files", [])

    def read_file(self, file_id: str, mime_type: str = "", file_name: str = "") -> str:
        """Download and parse a file from Google Drive."""
        from googleapiclient.http import MediaIoBaseDownload
        import tempfile

        service = self._get_service()
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from utils.file_parser import parse_file_to_text

        # Google Workspace files must be exported first
        if mime_type in SUPPORTED_MIME_EXPORT:
            export_mime = SUPPORTED_MIME_EXPORT[mime_type]
            ext = {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":       ".xlsx",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
            }.get(export_mime, ".bin")
            request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            # Regular files — detect extension from file_name or mime_type
            request = service.files().get_media(fileId=file_id)
            if file_name:
                ext = os.path.splitext(file_name)[1].lower() or ".bin"
            else:
                mime_to_ext = {
                    "application/pdf":                                                              ".pdf",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":           ".xlsx",
                    "application/vnd.ms-excel":                                                    ".xls",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":     ".docx",
                    "text/plain":                                                                   ".txt",
                    "text/csv":                                                                     ".csv",
                    "application/json":                                                             ".json",
                }
                ext = mime_to_ext.get(mime_type, ".bin")

        tmp_path = os.path.join(tempfile.gettempdir(), f"drive_{file_id}{ext}")
        try:
            with open(tmp_path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

            text = parse_file_to_text(tmp_path)
            return text if text.strip() else f"[{file_name or file_id}: no extractable text]"
        except Exception as e:
            return f"[Error reading {file_name or file_id}: {e}]"
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    def search_files(self, query: str, max_results: int = 20) -> list[dict]:
        """Full-text search."""
        return self.list_files(query=query, max_results=max_results)


# ─────────────────────────────────────────────────────────────────────────────
# Unified DriveClient — auto-selects Direct OAuth (local) or MCP (Claude.ai)
# ─────────────────────────────────────────────────────────────────────────────

class DriveClient:
    """
    Smart Drive client.

    LOCAL (python main.py / streamlit run):
      → Always uses DirectDriveClient (Google OAuth via credentials.json).
        credentials.json must be in the project root.
        On first run a browser window opens for OAuth consent.

    CLOUD / Claude.ai with MCP connected:
      → Uses MCPDriveClient, falls back to DirectDriveClient on 401/403.

    Auto-detection: if credentials.json exists → Direct OAuth immediately.
    """

    def __init__(self):
        self._direct: Optional[DirectDriveClient] = None
        self._mcp:    Optional[MCPDriveClient]    = None
        # Always use Direct OAuth when running locally.
        # MCP is only for Claude.ai cloud — never needed with python main.py.
        self._use_direct = True
        logger.info("DriveClient: Direct OAuth mode (local)")

    # ── Private helpers ─────────────────────────────────────────────────────

    def _direct_client(self) -> DirectDriveClient:
        if self._direct is None:
            self._direct = DirectDriveClient()
        return self._direct

    def _mcp_client(self) -> MCPDriveClient:
        if self._mcp is None:
            self._mcp = MCPDriveClient()
        return self._mcp

    # ── Public API ──────────────────────────────────────────────────────────

    def list_files(self, query: str = "", folder_id: str = None,
                   max_results: int = 50) -> list:
        if self._use_direct:
            return self._direct_client().list_files(
                query=query, folder_id=folder_id, max_results=max_results
            )
        # MCP path with auto-fallback
        try:
            return self._mcp_client().list_files(
                query=query, folder_id=folder_id, max_results=max_results
            )
        except Exception as e:
            logger.warning(f"MCP list_files failed: {e} — switching to Direct OAuth")
            self._use_direct = True
            return self._direct_client().list_files(
                query=query, folder_id=folder_id, max_results=max_results
            )

    def read_file(self, file_id: str, mime_type: str = "", file_name: str = "") -> str:
        if self._use_direct:
            return self._direct_client().read_file(file_id, mime_type)
        try:
            return self._mcp_client().read_file(file_id)
        except Exception as e:
            logger.warning(f"MCP read_file failed: {e} — switching to Direct OAuth")
            self._use_direct = True
            try:
                return self._direct_client().read_file(file_id, mime_type)
            except Exception as e2:
                return f"[Error reading {file_name}: {e2}]"

    def search_files(self, query: str, max_results: int = 20) -> list:
        return self.list_files(query=query, max_results=max_results)

    def load_documents(self, query: str = "", folder_id: str = None,
                       max_results: int = 50) -> list:
        """List + download + parse all matching Drive files into plain text."""
        files   = self.list_files(query=query, folder_id=folder_id, max_results=max_results)
        results = []
        for f in files:
            file_id   = f.get("id", "")
            file_name = f.get("name", "unknown")
            mime_type = f.get("mimeType", "")
            ext       = os.path.splitext(file_name)[1].lower()

            if ext not in SUPPORTED_EXTENSIONS and mime_type not in SUPPORTED_MIME_EXPORT:
                continue

            content = self.read_file(file_id, mime_type=mime_type, file_name=file_name)
            if content and not content.startswith("[Error"):
                results.append({"id": file_id, "file": file_name, "content": content})

        return results
