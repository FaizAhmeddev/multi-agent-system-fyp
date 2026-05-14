"""
MAIN.PY — Entry Point — FYP v7.0
"""
import subprocess, sys, os, webbrowser, time, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def open_browser():
    time.sleep(3)
    webbrowser.open("http://localhost:8501")

def run():
    # Reduce tokenizer fork warnings; set before Chroma / embedding imports (via data_loader).
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
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

    print("=" * 65)
    print("  Office Automation Agents Pro — FYP v7.0")
    print("  Agents: Unified Assistant → IT · Email · HR · Recruitment · Finance · Documents · WhatsApp")
    print("  Stack:  LangGraph · OpenAI · MCP · A2A · ChromaDB · SQLite")
    print("=" * 65)

    # Init DB
    try:
        from database.sqlite_db import init_db
        init_db()
        print("  ✅ SQLite DB initialized")
    except Exception as e:
        print(f"  ⚠️  DB init: {e}")

    # Auto-load datasets if ChromaDB empty
    try:
        from data_loader.loader import check_datasets_loaded, load_all_datasets
        if not check_datasets_loaded():
            print("  📊 Loading datasets into ChromaDB (first run)...")
            load_all_datasets()
        else:
            print("  ✅ ChromaDB datasets already loaded")
    except Exception as e:
        print(f"  ⚠️  Dataset loader: {e}")

    print("\n  🚀 Starting UI at http://localhost:8501\n")
    threading.Thread(target=open_browser, daemon=True).start()

    ui = os.path.join(os.path.dirname(__file__), "ui", "app.py")
    child_env = os.environ.copy()
    child_env.setdefault("TOKENIZERS_PARALLELISM", "false")
    child_env.setdefault("PYTHONWARNINGS", "ignore::DeprecationWarning")
    subprocess.run(
        [
            sys.executable, "-m", "streamlit", "run", ui,
            "--server.port", "8501",
            "--server.headless", "false",
            "--browser.gatherUsageStats", "false",
            "--theme.base", "light",
        ],
        env=child_env,
    )

def _launched_as_streamlit_script() -> bool:
    """
    True when this file is executed via `streamlit run .../main.py` (e.g. Streamlit Cloud).

    In that case we must NOT spawn a nested `streamlit run` subprocess — it blocks this
    process forever and the browser shows perpetual "Running".
    """
    return bool(os.environ.get("STREAMLIT_SERVER_PORT"))


if __name__ == "__main__":
    if _launched_as_streamlit_script():
        # Same interpreter / event loop as Streamlit — load the real UI module.
        _root = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, _root)
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        import importlib.util

        _ui = os.path.join(_root, "ui", "app.py")
        _spec = importlib.util.spec_from_file_location("_fyp_streamlit_ui", _ui)
        if _spec is None or _spec.loader is None:
            raise RuntimeError(f"Cannot load UI spec: {_ui}")
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
    else:
        run()
