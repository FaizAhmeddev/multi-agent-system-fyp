"""HR ecosystem: employees, checklists, letters, attendance, leave, separations, payroll, sheets, jobs

Revision ID: 0004_hr_ecosystem
Revises: 0003_cv_details
Create Date: 2026-10-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_hr_ecosystem"
down_revision = "0003_cv_details"
branch_labels = None
depends_on = None


def _ts():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def _fk_user(table: str, col: str):
    return sa.ForeignKeyConstraint([col], ["users.id"], name=f"fk_{table}_{col}_users", ondelete="SET NULL")


def upgrade() -> None:
    with op.batch_alter_table("candidates") as b:
        b.add_column(sa.Column("phone", sa.String(40), nullable=False, server_default=""))
        b.add_column(sa.Column("location", sa.String(100), nullable=False, server_default=""))
        b.add_column(sa.Column("source", sa.String(20), nullable=False, server_default=""))

    op.create_table(
        "hr_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_hr_settings"),
    )
    op.create_table(
        "hr_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("department", sa.String(100), nullable=False),
        sa.Column("location", sa.String(100), nullable=False),
        sa.Column("employment_type", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        *_ts(),
        _fk_user("hr_jobs", "created_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_hr_jobs"),
    )
    op.create_index("ix_hr_jobs_title", "hr_jobs", ["title"])

    op.create_table(
        "hr_employees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("phone", sa.String(40), nullable=False),
        sa.Column("job_title", sa.String(200), nullable=False),
        sa.Column("department", sa.String(100), nullable=False),
        sa.Column("manager", sa.String(200), nullable=False),
        sa.Column("location", sa.String(100), nullable=False),
        sa.Column("employment_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("offer_date", sa.Date(), nullable=True),
        sa.Column("joining_date", sa.Date(), nullable=True),
        sa.Column("probation_end", sa.Date(), nullable=True),
        sa.Column("last_working_day", sa.Date(), nullable=True),
        sa.Column("monthly_salary", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("allowances", sa.JSON(), nullable=False),
        sa.Column("bank_account_on_file", sa.Boolean(), nullable=False),
        sa.Column("finance_person_id", sa.String(40), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        *_ts(),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], name="fk_hr_employees_candidate_id_candidates",
                                ondelete="SET NULL"),
        _fk_user("hr_employees", "created_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_hr_employees"),
        sa.UniqueConstraint("code", name="uq_hr_employees_code"),
    )
    for c in ("full_name", "email", "department", "status", "joining_date"):
        op.create_index(f"ix_hr_employees_{c}", "hr_employees", [c])

    op.create_table(
        "hr_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("process", sa.String(20), nullable=False),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("owner", sa.String(40), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("automated", sa.Boolean(), nullable=False),
        sa.Column("tool", sa.String(80), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False),
        *_ts(),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], name="fk_hr_tasks_employee_id_hr_employees",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_hr_tasks"),
    )
    for c in ("employee_id", "process", "status"):
        op.create_index(f"ix_hr_tasks_{c}", "hr_tasks", [c])

    op.create_table(
        "hr_letters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("recipient_name", sa.String(200), nullable=False),
        sa.Column("recipient_email", sa.String(254), nullable=False),
        sa.Column("docx_path", sa.String(500), nullable=False),
        sa.Column("pdf_path", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("drive_file_id", sa.String(200), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], name="fk_hr_letters_employee_id_hr_employees",
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], name="fk_hr_letters_candidate_id_candidates",
                                ondelete="SET NULL"),
        _fk_user("hr_letters", "created_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_hr_letters"),
    )
    op.create_index("ix_hr_letters_employee_id", "hr_letters", ["employee_id"])
    op.create_index("ix_hr_letters_kind", "hr_letters", ["kind"])

    op.create_table(
        "hr_attendance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("check_in", sa.String(5), nullable=False),
        sa.Column("check_out", sa.String(5), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("note", sa.String(300), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], name="fk_hr_attendance_employee_id_hr_employees",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_hr_attendance"),
        sa.UniqueConstraint("employee_id", "day", name="uq_hr_attendance_employee_id"),
    )
    op.create_index("ix_hr_attendance_employee_id", "hr_attendance", ["employee_id"])
    op.create_index("ix_hr_attendance_day", "hr_attendance", ["day"])

    op.create_table(
        "hr_leave_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("leave_type", sa.String(20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("days", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"],
                                name="fk_hr_leave_requests_employee_id_hr_employees", ondelete="CASCADE"),
        _fk_user("hr_leave_requests", "decided_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_hr_leave_requests"),
    )
    for c in ("employee_id", "start_date", "status"):
        op.create_index(f"ix_hr_leave_requests_{c}", "hr_leave_requests", [c])

    op.create_table(
        "hr_separations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("notice_date", sa.Date(), nullable=True),
        sa.Column("last_working_day", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("settlement", sa.JSON(), nullable=False),
        *_ts(),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], name="fk_hr_separations_employee_id_hr_employees",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_hr_separations"),
    )
    op.create_index("ix_hr_separations_employee_id", "hr_separations", ["employee_id"])
    op.create_index("ix_hr_separations_last_working_day", "hr_separations", ["last_working_day"])

    op.create_table(
        "hr_payroll_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("totals", sa.JSON(), nullable=False),
        sa.Column("lines", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        *_ts(),
        _fk_user("hr_payroll_runs", "created_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_hr_payroll_runs"),
        sa.UniqueConstraint("month", name="uq_hr_payroll_runs_month"),
    )

    op.create_table(
        "hr_sheets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("location", sa.String(500), nullable=False),
        sa.Column("tab", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("auto_record", sa.Boolean(), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_hr_sheets"),
    )
    op.create_index("ix_hr_sheets_purpose", "hr_sheets", ["purpose"])


def downgrade() -> None:
    for t in ("hr_sheets", "hr_payroll_runs", "hr_separations", "hr_leave_requests", "hr_attendance", "hr_letters",
              "hr_tasks", "hr_employees", "hr_jobs", "hr_settings"):
        op.drop_table(t)
    with op.batch_alter_table("candidates") as b:
        b.drop_column("source")
        b.drop_column("location")
        b.drop_column("phone")
