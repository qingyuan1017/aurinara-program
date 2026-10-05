"""finish phase 1 operations and terminology

Revision ID: 77f76116ee1c
Revises: 24fae62c2c87
Create Date: 2026-10-04 21:56:38.784381
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "77f76116ee1c"
down_revision: str | Sequence[str] | None = "24fae62c2c87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the remaining Phase 1 operation and terminology persistence."""
    op.create_table(
        "artifact_builds",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("module_key", sa.String(length=32), nullable=False),
        sa.Column("owner_type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result_artifact_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_artifact_builds_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_builds")),
    )
    op.create_index(
        op.f("ix_artifact_builds_owner_id"), "artifact_builds", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_artifact_builds_study_id"), "artifact_builds", ["study_id"], unique=False
    )
    op.create_table(
        "terminology_extension_terms",
        sa.Column("extension_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("submission_value", sa.String(length=255), nullable=False),
        sa.Column("decode", sa.String(length=1000), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["extension_id"],
            ["terminology_extensions.id"],
            name=op.f("fk_terminology_extension_terms_extension_id_terminology_extensions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminology_extension_terms")),
        sa.UniqueConstraint(
            "extension_id", "code", name="uq_terminology_extension_terms_extension_code"
        ),
        sa.UniqueConstraint(
            "extension_id",
            "submission_value",
            name="uq_terminology_extension_terms_extension_submission_value",
        ),
    )
    op.create_index(
        op.f("ix_terminology_extension_terms_extension_id"),
        "terminology_extension_terms",
        ["extension_id"],
        unique=False,
    )
    op.add_column(
        "external_identifiers",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.alter_column("external_identifiers", "revision", server_default=None)
    op.add_column(
        "validation_runs",
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "validation_runs",
        sa.Column("created_by", sa.String(length=255), server_default="system", nullable=False),
    )
    op.alter_column("validation_runs", "created_by", server_default=None)


def downgrade() -> None:
    """Remove the remaining Phase 1 operation and terminology persistence."""
    op.drop_column("validation_runs", "created_by")
    op.drop_column("validation_runs", "failure")
    op.drop_column("external_identifiers", "revision")
    op.drop_index(
        op.f("ix_terminology_extension_terms_extension_id"),
        table_name="terminology_extension_terms",
    )
    op.drop_table("terminology_extension_terms")
    op.drop_index(op.f("ix_artifact_builds_study_id"), table_name="artifact_builds")
    op.drop_index(op.f("ix_artifact_builds_owner_id"), table_name="artifact_builds")
    op.drop_table("artifact_builds")
