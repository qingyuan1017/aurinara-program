"""Phase 3 SDTM exact inputs and versioned authoring records.

Revision ID: 20261006_0004
Revises: 20261006_0003
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261006_0004"
down_revision: str | None = "20261006_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sdtm_input_selections",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("aggregate_id"),
    )
    op.create_index("ix_sdtm_input_selections_study_id", "sdtm_input_selections", ["study_id"])
    op.create_table(
        "sdtm_specification_revisions",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "aggregate_id", "revision", name="uq_sdtm_specification_aggregate_revision"
        ),
    )
    op.create_index(
        "ix_sdtm_specification_revisions_aggregate_id",
        "sdtm_specification_revisions",
        ["aggregate_id"],
    )
    op.create_index(
        "ix_sdtm_specification_revisions_study_id",
        "sdtm_specification_revisions",
        ["study_id"],
    )
    op.create_table(
        "sdtm_derivation_plan_revisions",
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
        sa.ForeignKeyConstraint(["aggregate_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("aggregate_id", "revision", name="uq_sdtm_plan_aggregate_revision"),
    )
    op.create_index(
        "ix_sdtm_derivation_plan_revisions_aggregate_id",
        "sdtm_derivation_plan_revisions",
        ["aggregate_id"],
    )
    op.create_index(
        "ix_sdtm_derivation_plan_revisions_study_id",
        "sdtm_derivation_plan_revisions",
        ["study_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sdtm_derivation_plan_revisions_study_id",
        table_name="sdtm_derivation_plan_revisions",
    )
    op.drop_index(
        "ix_sdtm_derivation_plan_revisions_aggregate_id",
        table_name="sdtm_derivation_plan_revisions",
    )
    op.drop_table("sdtm_derivation_plan_revisions")
    op.drop_index(
        "ix_sdtm_specification_revisions_study_id",
        table_name="sdtm_specification_revisions",
    )
    op.drop_index(
        "ix_sdtm_specification_revisions_aggregate_id",
        table_name="sdtm_specification_revisions",
    )
    op.drop_table("sdtm_specification_revisions")
    op.drop_index("ix_sdtm_input_selections_study_id", table_name="sdtm_input_selections")
    op.drop_table("sdtm_input_selections")
