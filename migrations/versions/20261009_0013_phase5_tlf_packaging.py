"""Add Phase 5 TLF authoring and submission package records.

Revision ID: 20261009_0013
Revises: 20261009_0012
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261009_0013"
down_revision: str | None = "20261009_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tlf_authoring_revisions",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["tlf_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "aggregate_id", "content_type", "revision", name="uq_tlf_content_revision"
        ),
    )
    op.create_index(
        op.f("ix_tlf_authoring_revisions_aggregate_id"),
        "tlf_authoring_revisions",
        ["aggregate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tlf_authoring_revisions_study_id"),
        "tlf_authoring_revisions",
        ["study_id"],
        unique=False,
    )
    op.create_table(
        "submission_packages",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("module_selections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "reconciliation_run_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("zip_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("report_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["report_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["zip_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_submission_packages_study_id"),
        "submission_packages",
        ["study_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_submission_packages_study_id"), table_name="submission_packages")
    op.drop_table("submission_packages")
    op.drop_index(op.f("ix_tlf_authoring_revisions_study_id"), table_name="tlf_authoring_revisions")
    op.drop_index(
        op.f("ix_tlf_authoring_revisions_aggregate_id"), table_name="tlf_authoring_revisions"
    )
    op.drop_table("tlf_authoring_revisions")
