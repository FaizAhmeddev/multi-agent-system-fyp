from langgraph.graph import StateGraph, END
from state.it_state import ITState
from agents.it_support_agent import solve_it_problem

builder = StateGraph(ITState)
builder.add_node("it_support", solve_it_problem)
builder.set_entry_point("it_support")
builder.add_edge("it_support", END)
it_graph = builder.compile()
