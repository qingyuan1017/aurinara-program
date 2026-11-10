"""record live CDISC Specification source provenance

Revision ID: 20261108_0004
Revises: 20261108_0003
Create Date: 2026-11-08 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261108_0004"
down_revision: str | Sequence[str] | None = "20261108_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sdtm_specification_revisions",
        sa.Column(
            "standard_source",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sdtm_specification_revisions", "standard_source")
