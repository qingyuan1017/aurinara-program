"""Add canonical platform study projection metadata.

Revision ID: 20261010_0014
Revises: 20261010_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261010_0014"
down_revision: str | Sequence[str] | None = "20261010_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "studies",
        sa.Column("platform_managed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("studies", sa.Column("platform_revision", sa.BigInteger()))
    op.add_column("studies", sa.Column("platform_registry_status", sa.String(16)))
    op.create_table(
        "platform_projection_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_platform_projection_events_aggregate_id",
        "platform_projection_events",
        ["aggregate_id"],
    )
    op.add_column("artifacts", sa.Column("platform_object_id", sa.Uuid()))
    op.create_index("ix_artifacts_platform_object_id", "artifacts", ["platform_object_id"])
    op.add_column("source_files", sa.Column("platform_object_id", sa.Uuid()))
    op.create_index("ix_source_files_platform_object_id", "source_files", ["platform_object_id"])


def downgrade() -> None:
    op.drop_index("ix_source_files_platform_object_id", table_name="source_files")
    op.drop_column("source_files", "platform_object_id")
    op.drop_index("ix_artifacts_platform_object_id", table_name="artifacts")
    op.drop_column("artifacts", "platform_object_id")
    op.drop_index(
        "ix_platform_projection_events_aggregate_id",
        table_name="platform_projection_events",
    )
    op.drop_table("platform_projection_events")
    op.drop_column("studies", "platform_revision")
    op.drop_column("studies", "platform_registry_status")
    op.drop_column("studies", "platform_managed")
