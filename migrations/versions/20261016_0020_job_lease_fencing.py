"""Add durable job lease fencing.

Revision ID: 20261016_0020
Revises: 20261015_0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261016_0020"
down_revision: str | Sequence[str] | None = "20261015_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("claim_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_jobs_lease_token", "jobs", ["lease_token"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_jobs_lease_token", table_name="jobs")
    op.drop_column("jobs", "claim_generation")
    op.drop_column("jobs", "lease_token")
