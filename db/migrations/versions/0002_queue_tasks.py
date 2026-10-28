"""persistent queue (queue_tasks) and agent_runs.action/meta/task_id

Revision ID: 0002_queue_tasks
Revises: 0001_initial
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

from agentsmind.db.base import UTCDateTime

revision = "0002_queue_tasks"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "queue_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("queue", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", UTCDateTime(), nullable=False),
        sa.Column("leased_until", UTCDateTime(), nullable=True),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_queue_tasks_created_by_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_queue_tasks"),
        sa.UniqueConstraint("idempotency_key", name="uq_queue_tasks_idempotency_key"),
    )
    op.create_index("ix_queue_tasks_queue", "queue_tasks", ["queue"])
    op.create_index("ix_queue_tasks_status", "queue_tasks", ["status"])
    op.create_index("ix_queue_tasks_available_at", "queue_tasks", ["available_at"])

    with op.batch_alter_table("agent_runs") as b:
        b.add_column(sa.Column("action", sa.String(60), nullable=False, server_default=""))
        b.add_column(sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"))
        b.add_column(sa.Column("task_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as b:
        b.drop_column("task_id")
        b.drop_column("meta")
        b.drop_column("action")
    op.drop_table("queue_tasks")
