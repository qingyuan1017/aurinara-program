"""Phase 3 versioned SDTM cSDRG authoring.

Revision ID: 20261007_0008
Revises: 20261006_0007
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261007_0008"
down_revision: str | None = "20261006_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sdtm_csdrg_revisions",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("specification_revision", sa.Integer(), nullable=False),
        sa.Column("define_revision", sa.Integer(), nullable=False),
        sa.Column("reconciliation_run_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reconciliation_run_id"], ["reconciliation_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("aggregate_id", "revision", name="uq_sdtm_csdrg_aggregate_revision"),
    )
    op.create_index(
        "ix_sdtm_csdrg_revisions_aggregate_id", "sdtm_csdrg_revisions", ["aggregate_id"]
    )
    op.create_index("ix_sdtm_csdrg_revisions_study_id", "sdtm_csdrg_revisions", ["study_id"])
    op.create_index(
        "ix_sdtm_csdrg_revisions_reconciliation_run_id",
        "sdtm_csdrg_revisions",
        ["reconciliation_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sdtm_csdrg_revisions_reconciliation_run_id", table_name="sdtm_csdrg_revisions"
    )
    op.drop_index("ix_sdtm_csdrg_revisions_study_id", table_name="sdtm_csdrg_revisions")
    op.drop_index("ix_sdtm_csdrg_revisions_aggregate_id", table_name="sdtm_csdrg_revisions")
    op.drop_table("sdtm_csdrg_revisions")
