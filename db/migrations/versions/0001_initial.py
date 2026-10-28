"""initial core schema: users, roles, auth tokens, audit, approvals, tool calls, agents, HR, documents

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from agentsmind.db.base import UTCDateTime
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _ts():
    return [
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    ]


def _fk(col, table, ondelete, own_table):
    return sa.ForeignKeyConstraint([col], [f"{table}.id"], ondelete=ondelete,
                                   name=f"fk_{own_table}_{col}_{table}")


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.create_table(
        "users",
        *_ts(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", UTCDateTime(), nullable=True),
        sa.Column("last_login_at", UTCDateTime(), nullable=True),
        sa.Column("password_changed_at", UTCDateTime(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        _fk("user_id", "users", "CASCADE", "user_roles"),
        _fk("role_id", "roles", "CASCADE", "user_roles"),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("family_id", sa.String(36), nullable=False),
        sa.Column("issued_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.Column("replaced_by_id", sa.Integer(), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=False),
        _fk("user_id", "users", "CASCADE", "refresh_tokens"),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("used_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        _fk("user_id", "users", "CASCADE", "password_reset_tokens"),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])

    op.create_table(
        "outbound_emails",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("to_address", sa.String(254), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_outbound_emails"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", UTCDateTime(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_email", sa.String(254), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        _fk("actor_user_id", "users", "SET NULL", "audit_logs"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_logs_at", "audit_logs", ["at"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    op.create_table(
        "conversations",
        *_ts(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        _fk("user_id", "users", "CASCADE", "conversations"),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        _fk("conversation_id", "conversations", "CASCADE", "messages"),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=False),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        _fk("conversation_id", "conversations", "SET NULL", "agent_runs"),
        _fk("user_id", "users", "SET NULL", "agent_runs"),
        sa.PrimaryKeyConstraint("id", name="pk_agent_runs"),
    )
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])

    op.create_table(
        "approvals",
        *_ts(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_run_id", sa.Integer(), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("tool", sa.String(80), nullable=False),
        sa.Column("risk", sa.String(16), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("decided_at", UTCDateTime(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        _fk("agent_run_id", "agent_runs", "SET NULL", "approvals"),
        _fk("requested_by_user_id", "users", "CASCADE", "approvals"),
        _fk("decided_by_user_id", "users", "SET NULL", "approvals"),
        sa.PrimaryKeyConstraint("id", name="pk_approvals"),
        sa.UniqueConstraint("idempotency_key", name="uq_approvals_idempotency_key"),
    )
    op.create_index("ix_approvals_requested_by_user_id", "approvals", ["requested_by_user_id"])
    op.create_index("ix_approvals_status", "approvals", ["status"])

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", UTCDateTime(), nullable=False),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("tool", sa.String(80), nullable=False),
        sa.Column("server", sa.String(40), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("approval_id", sa.Integer(), nullable=True),
        sa.Column("inputs_redacted", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        _fk("user_id", "users", "SET NULL", "tool_calls"),
        _fk("approval_id", "approvals", "SET NULL", "tool_calls"),
        sa.PrimaryKeyConstraint("id", name="pk_tool_calls"),
    )
    op.create_index("ix_tool_calls_at", "tool_calls", ["at"])
    op.create_index("ix_tool_calls_tool", "tool_calls", ["tool"])
    op.create_index("ix_tool_calls_user_id", "tool_calls", ["user_id"])

    op.create_table(
        "documents",
        *_ts(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("text_excerpt", sa.Text(), nullable=False),
        _fk("owner_user_id", "users", "SET NULL", "documents"),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_index("ix_documents_sha256", "documents", ["sha256"])

    op.create_table(
        "candidates",
        *_ts(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("job_title", sa.String(200), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_candidates"),
    )
    op.create_index("ix_candidates_stage", "candidates", ["stage"])

    op.create_table(
        "cv_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("job_description", sa.Text(), nullable=False),
        sa.Column("rubric_score", sa.Integer(), nullable=True),
        sa.Column("keyword_score", sa.Integer(), nullable=True),
        sa.Column("matched_skills", sa.JSON(), nullable=False),
        sa.Column("missing_skills", sa.JSON(), nullable=False),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        _fk("candidate_id", "candidates", "CASCADE", "cv_records"),
        _fk("document_id", "documents", "SET NULL", "cv_records"),
        sa.PrimaryKeyConstraint("id", name="pk_cv_records"),
        sa.UniqueConstraint("candidate_id", "document_id", name="uq_cv_records_candidate_id"),
    )
    op.create_index("ix_cv_records_candidate_id", "cv_records", ["candidate_id"])


def downgrade() -> None:
    for table in ("cv_records", "candidates", "documents", "tool_calls", "approvals", "agent_runs",
                  "messages", "conversations", "audit_logs", "outbound_emails",
                  "password_reset_tokens", "refresh_tokens", "user_roles", "users", "roles"):
        op.drop_table(table)
