"""
FINANCE_DRIVE_READER.PY
========================
Reads financial documents from Google Drive via DirectDriveClient.
"""
import os, sys
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

def read_finance_documents_from_drive(folder_name: str = None, max_files: int = 20) -> list:
    try:
        from tools.mcp_drive_client import DriveClient
        client = DriveClient()
        docs   = client.load_documents(query=folder_name or "", max_results=max_files)
        return docs
    except Exception as e:
        return [{"file": "Error", "content": f"Could not load Drive: {e}"}]

def get_finance_context_from_drive(folder_name: str = None) -> str:
    docs = read_finance_documents_from_drive(folder_name)
    if not docs:
        return ""
    return "\n\n---\n\n".join(f"[{d['file']}]\n{d['content'][:1500]}" for d in docs)

if __name__ == "__main__":
    docs = read_finance_documents_from_drive()
    print(f"Loaded {len(docs)} documents")
    for d in docs:
        print(f"  - {d['file']} ({len(d['content'])} chars)")
