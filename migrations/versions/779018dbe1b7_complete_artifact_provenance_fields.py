"""complete artifact provenance fields

Revision ID: 779018dbe1b7
Revises: 371681e538cc
Create Date: 2026-10-04 22:49:23.538442
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "779018dbe1b7"
down_revision: str | Sequence[str] | None = "371681e538cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add version-neutral compilation and source provenance to artifacts."""
    op.add_column("artifacts", sa.Column("input_selection_revision", sa.Integer(), nullable=True))
    op.add_column(
        "artifacts", sa.Column("source_specification_revision", sa.Integer(), nullable=True)
    )
    op.add_column(
        "artifacts",
        sa.Column("source_specification_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column("artifacts", sa.Column("source_plan_type", sa.String(length=64), nullable=True))
    op.add_column("artifacts", sa.Column("source_plan_revision", sa.Integer(), nullable=True))
    op.add_column(
        "artifacts", sa.Column("compiler_fingerprint", sa.String(length=64), nullable=True)
    )
    op.create_index(
        op.f("ix_artifacts_source_plan_type"), "artifacts", ["source_plan_type"], unique=False
    )


def downgrade() -> None:
    """Remove compilation and source provenance fields."""
    op.drop_index(op.f("ix_artifacts_source_plan_type"), table_name="artifacts")
    op.drop_column("artifacts", "compiler_fingerprint")
    op.drop_column("artifacts", "source_plan_revision")
    op.drop_column("artifacts", "source_plan_type")
    op.drop_column("artifacts", "source_specification_fingerprint")
    op.drop_column("artifacts", "source_specification_revision")
    op.drop_column("artifacts", "input_selection_revision")
