"""Phase 4 ADaM exact inputs and versioned authoring records.

Revision ID: 20261008_0009
Revises: 20261007_0008
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261008_0009"
down_revision: str | None = "20261007_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "adam_input_selections",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["adam_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("aggregate_id"),
    )
    op.create_index("ix_adam_input_selections_study_id", "adam_input_selections", ["study_id"])
    op.create_table(
        "adam_specification_revisions",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["adam_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "aggregate_id", "revision", name="uq_adam_specification_aggregate_revision"
        ),
    )
    op.create_index(
        "ix_adam_specification_revisions_aggregate_id",
        "adam_specification_revisions",
        ["aggregate_id"],
    )
    op.create_index(
        "ix_adam_specification_revisions_study_id",
        "adam_specification_revisions",
        ["study_id"],
    )
    op.create_table(
        "adam_derivation_plan_revisions",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("specification_revision", sa.Integer(), nullable=False),
        sa.Column("input_selection_revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["adam_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("aggregate_id", "revision", name="uq_adam_plan_aggregate_revision"),
    )
    op.create_index(
        "ix_adam_derivation_plan_revisions_aggregate_id",
        "adam_derivation_plan_revisions",
        ["aggregate_id"],
    )
    op.create_index(
        "ix_adam_derivation_plan_revisions_study_id",
        "adam_derivation_plan_revisions",
        ["study_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_adam_derivation_plan_revisions_study_id",
        table_name="adam_derivation_plan_revisions",
    )
    op.drop_index(
        "ix_adam_derivation_plan_revisions_aggregate_id",
        table_name="adam_derivation_plan_revisions",
    )
    op.drop_table("adam_derivation_plan_revisions")
    op.drop_index(
        "ix_adam_specification_revisions_study_id",
        table_name="adam_specification_revisions",
    )
    op.drop_index(
        "ix_adam_specification_revisions_aggregate_id",
        table_name="adam_specification_revisions",
    )
    op.drop_table("adam_specification_revisions")
    op.drop_index("ix_adam_input_selections_study_id", table_name="adam_input_selections")
    op.drop_table("adam_input_selections")
