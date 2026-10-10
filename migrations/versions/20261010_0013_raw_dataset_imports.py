"""Add the raw_dataset_imports operation table for bulk dataset import.

Revision ID: 20261010_0013
Revises: 20261009_0013
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261010_0013"
down_revision: str | Sequence[str] | None = "20261009_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "raw_dataset_imports",
        sa.Column("raw_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("entries", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("files_inspected", sa.Integer(), nullable=False),
        sa.Column("result_dataset_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["raw_id"],
            ["raw_workbenches.id"],
            name=op.f("fk_raw_dataset_imports_raw_id_raw_workbenches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_raw_dataset_imports_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_dataset_imports")),
    )
    op.create_index(
        op.f("ix_raw_dataset_imports_raw_id"), "raw_dataset_imports", ["raw_id"], unique=False
    )
    op.create_index(
        op.f("ix_raw_dataset_imports_study_id"), "raw_dataset_imports", ["study_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_raw_dataset_imports_study_id"), table_name="raw_dataset_imports")
    op.drop_index(op.f("ix_raw_dataset_imports_raw_id"), table_name="raw_dataset_imports")
    op.drop_table("raw_dataset_imports")
