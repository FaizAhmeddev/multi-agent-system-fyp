"""
MAIN.PY — Entry Point — FYP v7.0
Run from this folder:  python main.py
"""
import os
import subprocess
import sys
import threading
import time
import webbrowser

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)


def _configure_windows_console() -> None:
    """Avoid UnicodeEncodeError on Windows cmd/PowerShell (cp1252)."""
    if sys.platform != "win32":
        return
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)


def _ensure_env_file() -> bool:
    """Create .env from .env.example if missing (user must still add keys)."""
    env_path = os.path.join(_ROOT, ".env")
    example = os.path.join(_ROOT, ".env.example")
    if os.path.isfile(env_path):
        return True
    if not os.path.isfile(example):
        return False
    try:
        with open(example, "r", encoding="utf-8") as src:
            data = src.read()
        with open(env_path, "w", encoding="utf-8") as dst:
            dst.write(data)
        _log("  [i] Created .env from .env.example — add your API keys, then restart.")
        return True
    except Exception as e:
        _log(f"  [!] Could not create .env: {e}")
        return False


def _load_secrets() -> bool:
    try:
        from config import load_local_env
        return load_local_env()
    except Exception as e:
        _log(f"  [!] .env load error: {e}")
        return False


def open_browser():
    time.sleep(3)
    webbrowser.open("http://localhost:8501")


def run():
    _configure_windows_console()
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    _ensure_env_file()
    has_env = _load_secrets()

    import logging

    for _lg in (
        "transformers",
        "transformers.models",
        "huggingface_hub",
        "chromadb",
        "sentence_transformers",
        "torch",
    ):
        logging.getLogger(_lg).setLevel(logging.CRITICAL)

    import warnings

    try:
        from langchain_core._api.deprecation import LangChainPendingDeprecationWarning
    except Exception:
        LangChainPendingDeprecationWarning = None  # type: ignore
    if LangChainPendingDeprecationWarning is not None:
        warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)
    warnings.filterwarnings("ignore", message=".*allowed_objects.*")

    _log("=" * 65)
    _log("  Office Automation Agents Pro - FYP v7.0")
    _log("  Agents: Assistant | IT | Email | HR | Recruitment | Finance | Documents | WhatsApp")
    _log("  Stack:  LangGraph | OpenAI | MCP | A2A | ChromaDB | SQLite")
    _log("=" * 65)

    if has_env:
        _log("  [ok] Loaded FYP_FINAL/.env")
    else:
        _log("  [!] No secrets in .env yet — copy .env.example -> .env and fill GMAIL_* / OPENAI_API_KEY")

    try:
        from database.sqlite_db import init_db
        init_db()
        _log("  [ok] SQLite DB initialized")
    except Exception as e:
        _log(f"  [!] DB init: {e}")

    try:
        from data_loader.loader import check_datasets_loaded, load_all_datasets
        if not check_datasets_loaded():
            _log("  [..] Loading datasets into ChromaDB (first run)...")
            load_all_datasets()
        else:
            _log("  [ok] ChromaDB datasets already loaded")
    except Exception as e:
        _log(f"  [!] Dataset loader: {e}")

    _log("")
    _log("  Starting UI at http://localhost:8501")
    _log("  Press Ctrl+C to stop.")
    _log("")

    threading.Thread(target=open_browser, daemon=True).start()

    ui = os.path.join(_ROOT, "ui", "app.py")
    child_env = os.environ.copy()
    child_env.setdefault("TOKENIZERS_PARALLELISM", "false")
    child_env.setdefault("PYTHONWARNINGS", "ignore::DeprecationWarning")
    child_env.setdefault("PYTHONUTF8", "1")

    port = os.environ.get("FYP_PORT", "8501")
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        ui,
        "--server.port",
        str(port),
        "--server.headless",
        "false",
        "--browser.gatherUsageStats",
        "false",
        "--theme.base",
        "light",
    ]
    _log(f"  Streamlit port: {port}")
    rc = subprocess.run(cmd, env=child_env, cwd=_ROOT).returncode
    if rc != 0 and str(port) == "8501":
        _log("  [!] Port 8501 busy — close other Streamlit windows or run: set FYP_PORT=8502 && python main.py")


def _launched_as_streamlit_script() -> bool:
    return bool(os.environ.get("STREAMLIT_SERVER_PORT"))


if __name__ == "__main__":
    _configure_windows_console()
    if _launched_as_streamlit_script():
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        _ensure_env_file()
        _load_secrets()
        import importlib.util

        _ui = os.path.join(_ROOT, "ui", "app.py")
        _spec = importlib.util.spec_from_file_location("_fyp_streamlit_ui", _ui)
        if _spec is None or _spec.loader is None:
            raise RuntimeError(f"Cannot load UI spec: {_ui}")
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
    else:
        run()
