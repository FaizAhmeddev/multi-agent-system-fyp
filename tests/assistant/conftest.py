"""Assistant unit tests: agents and orchestrator with a fake context (no DB, no network).

If langgraph is not installed (the cloud workspace), a minimal stand-in with the same
StateGraph API is used; on the laptop gate the real langgraph 1.1.0 runs these tests.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "backend", ROOT, Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    import langgraph.graph  # noqa: F401
except ImportError:
    START, END = "__start__", "__end__"

    class _Compiled:
        def __init__(self, g):
            self.g = g

        def invoke(self, state):
            state = dict(state)
            node = self.g.edges[START]
            for _ in range(100):
                if node == END:
                    return state
                state.update(self.g.nodes[node](state) or {})
                if node in self.g.cond:
                    fn, mapping = self.g.cond[node]
                    node = mapping[fn(state)]
                else:
                    node = self.g.edges[node]
            raise RuntimeError("graph did not finish")

    class StateGraph:
        def __init__(self, schema):
            self.schema = schema
            self.nodes, self.edges, self.cond = {}, {}, {}

        def add_node(self, name, fn):
            if name in getattr(self.schema, "__annotations__", {}):
                raise ValueError(f"'{name}' is already being used as a state key")
            self.nodes[name] = fn

        def add_edge(self, a, b):
            self.edges[a] = b

        def add_conditional_edges(self, source, path, path_map):
            self.cond[source] = (path, path_map)

        def compile(self):
            return _Compiled(self)

    lg = types.ModuleType("langgraph")
    lgg = types.ModuleType("langgraph.graph")
    lgg.StateGraph, lgg.START, lgg.END = StateGraph, START, END
    lg.graph = lgg
    sys.modules["langgraph"], sys.modules["langgraph.graph"] = lg, lgg
