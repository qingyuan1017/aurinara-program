"""Phase 3 persisted aCRF annotations and typed targets.

Revision ID: 20261006_0006
Revises: 20261006_0005
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261006_0006"
down_revision: str | None = "20261006_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sdtm_acrf_annotations",
        sa.Column("sdtm_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("source_pdf_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("region", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("annotation_text", sa.String(length=4000), nullable=True),
        sa.Column("links", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("question", sa.String(length=4000), nullable=True),
        sa.Column("resolution", sa.String(length=4000), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("page_number >= 1", name="ck_sdtm_acrf_page_positive"),
        sa.CheckConstraint("status IN ('open', 'resolved', 'deleted')", name="ck_sdtm_acrf_status"),
        sa.ForeignKeyConstraint(["sdtm_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_pdf_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sdtm_acrf_annotations_sdtm_id", "sdtm_acrf_annotations", ["sdtm_id"])
    op.create_index("ix_sdtm_acrf_annotations_study_id", "sdtm_acrf_annotations", ["study_id"])
    op.create_index(
        "ix_sdtm_acrf_annotations_source_pdf_artifact_id",
        "sdtm_acrf_annotations",
        ["source_pdf_artifact_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sdtm_acrf_annotations_source_pdf_artifact_id",
        table_name="sdtm_acrf_annotations",
    )
    op.drop_index("ix_sdtm_acrf_annotations_study_id", table_name="sdtm_acrf_annotations")
    op.drop_index("ix_sdtm_acrf_annotations_sdtm_id", table_name="sdtm_acrf_annotations")
    op.drop_table("sdtm_acrf_annotations")
