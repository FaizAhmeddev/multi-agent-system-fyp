"""Run the UI and protected cookie routes through Streamlit's public ASGI API.

    python -m ui.server --port 8501
    uvicorn ui.server:app --host 127.0.0.1 --port 8501
"""
from pathlib import Path
import os
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
from auth.http_routes import auth_routes


def create_app(script_path=None):
    return st.App(script_path or _ROOT / "ui" / "app.py", routes=auth_routes(st.get_option("server.baseUrlPath") or ""))


app = create_app()


def main():
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.getenv("FYP_PORT", "8501")))
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, access_log=False,
                proxy_headers=True, forwarded_allow_ips=os.getenv("FYP_TRUSTED_PROXIES", "127.0.0.1"))


if __name__ == "__main__":
    main()
