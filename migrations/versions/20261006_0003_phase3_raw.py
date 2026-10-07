"""Phase 3 Raw workbench metadata and immutable file bindings.

Revision ID: 20261006_0003
Revises: 20261005_0002
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261006_0003"
down_revision: str | None = "20261005_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "raw_datasets",
        sa.Column("raw_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=True),
        sa.Column("current_source_file_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["raw_id"], ["raw_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["current_source_file_id"], ["source_files.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_id", "code", name="uq_raw_datasets_raw_code"),
    )
    op.create_index("ix_raw_datasets_raw_id", "raw_datasets", ["raw_id"])
    op.create_index("ix_raw_datasets_study_id", "raw_datasets", ["study_id"])
    op.create_table(
        "raw_dataset_file_bindings",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_revision", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["raw_datasets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_id", "dataset_revision", name="uq_raw_dataset_binding_revision"
        ),
    )
    op.create_index(
        "ix_raw_dataset_file_bindings_dataset_id", "raw_dataset_file_bindings", ["dataset_id"]
    )
    op.create_index(
        "ix_raw_dataset_file_bindings_study_id", "raw_dataset_file_bindings", ["study_id"]
    )
    op.create_table(
        "raw_variables",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("physical_type", sa.String(length=32), nullable=True),
        sa.Column("length", sa.Integer(), nullable=True),
        sa.Column("precision", sa.Integer(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=True),
        sa.Column("description", sa.String(length=4000), nullable=True),
        sa.Column("terminology_binding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["raw_datasets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "name", name="uq_raw_variables_dataset_name"),
        sa.UniqueConstraint("dataset_id", "ordinal", name="uq_raw_variables_dataset_ordinal"),
    )
    op.create_index("ix_raw_variables_dataset_id", "raw_variables", ["dataset_id"])
    op.create_index("ix_raw_variables_study_id", "raw_variables", ["study_id"])


def downgrade() -> None:
    op.drop_index("ix_raw_variables_study_id", table_name="raw_variables")
    op.drop_index("ix_raw_variables_dataset_id", table_name="raw_variables")
    op.drop_table("raw_variables")
    op.drop_index("ix_raw_dataset_file_bindings_study_id", table_name="raw_dataset_file_bindings")
    op.drop_index("ix_raw_dataset_file_bindings_dataset_id", table_name="raw_dataset_file_bindings")
    op.drop_table("raw_dataset_file_bindings")
    op.drop_index("ix_raw_datasets_study_id", table_name="raw_datasets")
    op.drop_index("ix_raw_datasets_raw_id", table_name="raw_datasets")
    op.drop_table("raw_datasets")
