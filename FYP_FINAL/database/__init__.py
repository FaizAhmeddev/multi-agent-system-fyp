from .sqlite_db import (
    init_db, get_session, log_task, log_agent, log_email,
    log_candidate, log_it_ticket, log_finance, log_whatsapp,
    add_notification, get_dashboard_stats, get_task_history,
    get_notifications, mark_notifications_read,
    log_login_event, get_login_history,
    authenticate_user, touch_user_session, deactivate_user_session,
    get_or_create_conversation, append_conversation_message,
    load_conversation_ui_messages, load_conversation_openai_history,
)
from .vector_db import (
    embed_documents, semantic_search, rag_answer,
    collection_stats, clear_collection, is_available,
)

__all__ = [
    "init_db", "get_session",
    "log_task", "log_agent", "log_email", "log_candidate",
    "log_it_ticket", "log_finance", "log_whatsapp",
    "add_notification", "get_dashboard_stats", "get_task_history",
    "get_notifications", "mark_notifications_read",
    "log_login_event", "get_login_history",
    "authenticate_user", "touch_user_session", "deactivate_user_session",
    "get_or_create_conversation", "append_conversation_message",
    "load_conversation_ui_messages", "load_conversation_openai_history",
    "embed_documents", "semantic_search", "rag_answer",
    "collection_stats", "clear_collection", "is_available",
]
