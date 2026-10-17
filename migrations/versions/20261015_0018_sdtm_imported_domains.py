"""Add immutable imported SDTM domains and explicit domain source selection.

Revision ID: 20261015_0018
Revises: 20261015_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0018"
down_revision: str | Sequence[str] | None = "20261015_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sdtm_imported_domain_revisions",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("domain_code", sa.String(8), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("specification_revision", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("validation_run_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("alignment_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("extracted_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["validation_run_id"], ["validation_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_sdtm_imported_domain_revisions"),
        sa.UniqueConstraint("artifact_id", name="uq_sdtm_imported_domain_revisions_artifact_id"),
        sa.UniqueConstraint(
            "aggregate_id",
            "domain_code",
            "revision",
            name="uq_sdtm_imported_domain_aggregate_domain_revision",
        ),
        sa.UniqueConstraint(
            "validation_run_id",
            name="uq_sdtm_imported_domain_revisions_validation_run_id",
        ),
    )
    op.create_index(
        "ix_sdtm_imported_domain_aggregate_domain",
        "sdtm_imported_domain_revisions",
        ["aggregate_id", "domain_code"],
    )
    op.create_index(
        op.f("ix_sdtm_imported_domain_revisions_aggregate_id"),
        "sdtm_imported_domain_revisions",
        ["aggregate_id"],
    )
    op.create_index(
        op.f("ix_sdtm_imported_domain_revisions_source_file_id"),
        "sdtm_imported_domain_revisions",
        ["source_file_id"],
    )
    op.create_index(
        op.f("ix_sdtm_imported_domain_revisions_study_id"),
        "sdtm_imported_domain_revisions",
        ["study_id"],
    )
    op.create_table(
        "sdtm_domain_source_selections",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("domain_code", sa.String(8), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_sdtm_domain_source_selections"),
        sa.UniqueConstraint(
            "aggregate_id", "domain_code", name="uq_sdtm_domain_source_aggregate_domain"
        ),
    )
    op.create_index(
        op.f("ix_sdtm_domain_source_selections_aggregate_id"),
        "sdtm_domain_source_selections",
        ["aggregate_id"],
    )
    op.create_index(
        op.f("ix_sdtm_domain_source_selections_study_id"),
        "sdtm_domain_source_selections",
        ["study_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_sdtm_domain_source_selections_study_id"),
        table_name="sdtm_domain_source_selections",
    )
    op.drop_index(
        op.f("ix_sdtm_domain_source_selections_aggregate_id"),
        table_name="sdtm_domain_source_selections",
    )
    op.drop_table("sdtm_domain_source_selections")
    op.drop_index(
        op.f("ix_sdtm_imported_domain_revisions_study_id"),
        table_name="sdtm_imported_domain_revisions",
    )
    op.drop_index(
        op.f("ix_sdtm_imported_domain_revisions_source_file_id"),
        table_name="sdtm_imported_domain_revisions",
    )
    op.drop_index(
        op.f("ix_sdtm_imported_domain_revisions_aggregate_id"),
        table_name="sdtm_imported_domain_revisions",
    )
    op.drop_index(
        "ix_sdtm_imported_domain_aggregate_domain",
        table_name="sdtm_imported_domain_revisions",
    )
    op.drop_table("sdtm_imported_domain_revisions")
