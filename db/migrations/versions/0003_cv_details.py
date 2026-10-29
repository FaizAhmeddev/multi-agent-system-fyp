"""cv_records.details (rubric, review reasons, flags) and candidates.source_ref

Revision ID: 0003_cv_details
Revises: 0002_queue_tasks
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_cv_details"
down_revision = "0002_queue_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cv_records") as b:
        b.add_column(sa.Column("details", sa.JSON(), nullable=False, server_default="{}"))
    with op.batch_alter_table("candidates") as b:
        b.add_column(sa.Column("source_ref", sa.String(200), nullable=False, server_default=""))
        b.create_index("ix_candidates_source_ref", ["source_ref"])


def downgrade() -> None:
    with op.batch_alter_table("candidates") as b:
        b.drop_index("ix_candidates_source_ref")
        b.drop_column("source_ref")
    with op.batch_alter_table("cv_records") as b:
        b.drop_column("details")
