"""Add platform-owned sponsor to canonical study projections.

Revision ID: 20261012_0016
Revises: 20261010_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261012_0016"
down_revision: str | Sequence[str] | None = "20261010_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("studies", sa.Column("sponsor", sa.String(255)))


def downgrade() -> None:
    op.drop_column("studies", "sponsor")
