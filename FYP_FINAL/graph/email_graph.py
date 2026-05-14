from langgraph.graph import StateGraph, END
from state.email_state import EmailState
from agents.auto_reply_agent import generate_reply
from tools.gmail_read import read_emails
from tools.gmail_send import send_email

builder = StateGraph(EmailState)
builder.add_node("read",  read_emails)
builder.add_node("reply", generate_reply)
builder.add_node("send",  send_email)
builder.set_entry_point("read")
builder.add_edge("read",  "reply")
builder.add_edge("reply", "send")
email_graph = builder.compile()
