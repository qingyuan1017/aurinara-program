"""Phase 3 immutable execution-run contracts.

Revision ID: 20261006_0005
Revises: 20261006_0004
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261006_0005"
down_revision: str | None = "20261006_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_runs",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("module_key", sa.String(length=32), nullable=False),
        sa.Column("owner_type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("program_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("input_artifact_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation_run_id", sa.Uuid(), nullable=False),
        sa.Column("input_selection_revision", sa.Integer(), nullable=False),
        sa.Column("source_specification_revision", sa.Integer(), nullable=False),
        sa.Column("source_plan_type", sa.String(length=64), nullable=False),
        sa.Column("source_plan_revision", sa.Integer(), nullable=False),
        sa.Column("compiler_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("output_artifact_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stderr", sa.Text(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["program_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_execution_runs_study_id", "execution_runs", ["study_id"])
    op.create_index("ix_execution_runs_module_key", "execution_runs", ["module_key"])
    op.create_index("ix_execution_runs_owner_id", "execution_runs", ["owner_id"])
    op.create_index(
        "ix_execution_runs_program_artifact_id", "execution_runs", ["program_artifact_id"]
    )
    op.create_index("ix_execution_runs_validation_run_id", "execution_runs", ["validation_run_id"])
    op.create_index("ix_execution_runs_status", "execution_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_execution_runs_status", table_name="execution_runs")
    op.drop_index("ix_execution_runs_validation_run_id", table_name="execution_runs")
    op.drop_index("ix_execution_runs_program_artifact_id", table_name="execution_runs")
    op.drop_index("ix_execution_runs_owner_id", table_name="execution_runs")
    op.drop_index("ix_execution_runs_module_key", table_name="execution_runs")
    op.drop_index("ix_execution_runs_study_id", table_name="execution_runs")
    op.drop_table("execution_runs")
