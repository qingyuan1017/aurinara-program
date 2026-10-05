"""add reference import batches

Revision ID: 371681e538cc
Revises: 77f76116ee1c
Create Date: 2026-10-04 21:57:49.077846
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "371681e538cc"
down_revision: str | Sequence[str] | None = "77f76116ee1c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add immutable evidence for idempotent atomic Reference imports."""
    op.create_table(
        "reference_import_batches",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("reference_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_reference_import_batches_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reference_import_batches")),
    )
    op.create_index(
        op.f("ix_reference_import_batches_study_id"),
        "reference_import_batches",
        ["study_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove Reference import evidence."""
    op.drop_index(
        op.f("ix_reference_import_batches_study_id"), table_name="reference_import_batches"
    )
    op.drop_table("reference_import_batches")
