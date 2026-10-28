"""
Characterization test harness for the legacy FYP_FINAL code (Phase 0).

These tests pin CURRENT behavior before refactoring. Some of them assert behavior
that is insecure or wrong on purpose (marked `legacy_bug`); later phases will flip
those assertions deliberately, never silently.

Rules:
- No network. No real LLM. No real Gmail/Drive.
- Third-party packages that are not installed (langchain_openai, langgraph,
  streamlit, sqlalchemy) are replaced by small stubs so the pure-Python logic can
  still be exercised. When the real packages ARE installed, the real ones are used,
  except database.sqlite_db which is always isolated to a temp SQLite file.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LEGACY = os.path.join(ROOT, "FYP_FINAL")
if LEGACY not in sys.path:
    sys.path.insert(0, LEGACY)

# Never let a developer's real .env leak into tests.
os.environ["OPENAI_API_KEY"] = ""
os.environ["GMAIL_EMAIL"] = ""
os.environ["GMAIL_APP_PASSWORD"] = ""
os.environ.setdefault("FYP_HOSTED", "false")
# Legacy code writes to FYP_FINAL/database/fyp_data.db by default; point it at a temp file.
import tempfile as _tempfile
_LEGACY_TMP = _tempfile.mkdtemp(prefix="fyp_legacy_")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_LEGACY_TMP, "legacy.db").replace("\\", "/")

STUBBED: list[str] = []


def _missing(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is None
    except (ImportError, ValueError):
        return True


class _FakeLLMResponse:
    def __init__(self, content: str):
        self.content = content


class FakeChatOpenAI:
    """Stand-in for langchain_openai.ChatOpenAI. Never calls the network."""

    canned: list[str] = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    def invoke(self, prompt, *args, **kwargs):
        if FakeChatOpenAI.canned:
            return _FakeLLMResponse(FakeChatOpenAI.canned.pop(0))
        raise RuntimeError("FakeChatOpenAI: no canned response (network disabled in tests)")


if _missing("langchain_openai"):
    m = types.ModuleType("langchain_openai")
    m.ChatOpenAI = FakeChatOpenAI
    sys.modules["langchain_openai"] = m
    STUBBED.append("langchain_openai")

if _missing("langgraph"):
    lg = types.ModuleType("langgraph")
    lgg = types.ModuleType("langgraph.graph")

    class _Compiled:
        def __init__(self, nodes, entry):
            self._nodes, self._entry = nodes, entry

        def invoke(self, state):
            # Linear graphs only (that is all the legacy code builds).
            return self._nodes[self._entry](state)

    class StateGraph:
        def __init__(self, _state_type):
            self._nodes, self._entry = {}, None

        def add_node(self, name, fn):
            self._nodes[name] = fn

        def set_entry_point(self, name):
            self._entry = name

        def add_edge(self, *_a):
            pass

        def compile(self):
            return _Compiled(self._nodes, self._entry)

    lgg.StateGraph, lgg.END = StateGraph, "__end__"
    lg.graph = lgg
    sys.modules["langgraph"], sys.modules["langgraph.graph"] = lg, lgg
    STUBBED.append("langgraph")

if _missing("sqlalchemy"):
    # database.sqlite_db cannot import without SQLAlchemy; replace it with a
    # recorder so callers that log to the DB still run.
    db_pkg = types.ModuleType("database")
    db_pkg.__path__ = [os.path.join(LEGACY, "database")]
    sdb = types.ModuleType("database.sqlite_db")
    sdb.CALLS = []

    def _sdb_getattr(name):
        if name.startswith("_") or name.startswith("pytest"):
            raise AttributeError(name)

        def _recorder(*a, **k):
            sdb.CALLS.append((name, a, k))
            return None

        return _recorder

    sdb.__getattr__ = _sdb_getattr
    sys.modules["database"], sys.modules["database.sqlite_db"] = db_pkg, sdb
    STUBBED.append("sqlalchemy (database.sqlite_db recorder)")


def pytest_report_header(config):
    return "characterization stubs: " + (", ".join(STUBBED) if STUBBED else "none (real deps)")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "legacy_bug: pins current WRONG/insecure behavior; flip intentionally in a later phase"
    )


@pytest.fixture
def fake_llm():
    FakeChatOpenAI.canned = []
    yield FakeChatOpenAI
    FakeChatOpenAI.canned = []
