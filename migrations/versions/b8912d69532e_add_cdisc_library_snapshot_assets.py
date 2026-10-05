"""add CDISC Library snapshot assets

Revision ID: b8912d69532e
Revises: 9c2c36d25e4a
Create Date: 2026-10-04 23:58:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8912d69532e"
down_revision: str | Sequence[str] | None = "9c2c36d25e4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store every raw CDISC Library representation as a checked provider asset."""

    op.add_column(
        "standard_assets", sa.Column("canonical_href", sa.String(length=2000), nullable=True)
    )
    op.add_column("standard_assets", sa.Column("title", sa.String(length=1000), nullable=True))
    op.add_column(
        "standard_assets", sa.Column("resource_type", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "standard_assets",
        sa.Column(
            "content_schema_version",
            sa.String(length=32),
            server_default="1.0.0",
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_standard_assets_version_canonical_href",
        "standard_assets",
        ["version_id", "canonical_href"],
    )
    op.create_table(
        "terminology_assets",
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("asset_path", sa.String(length=512), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("canonical_href", sa.String(length=2000), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=True),
        sa.Column("resource_type", sa.String(length=255), nullable=True),
        sa.Column(
            "content_schema_version",
            sa.String(length=32),
            server_default="1.0.0",
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["terminology_releases.id"],
            name=op.f("fk_terminology_assets_release_id_terminology_releases"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminology_assets")),
        sa.UniqueConstraint(
            "release_id", "canonical_href", name=op.f("uq_terminology_assets_release_id")
        ),
    )
    op.create_index(
        op.f("ix_terminology_assets_release_id"),
        "terminology_assets",
        ["release_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove raw CDISC Library snapshot asset persistence."""

    op.drop_index(op.f("ix_terminology_assets_release_id"), table_name="terminology_assets")
    op.drop_table("terminology_assets")
    op.drop_constraint(
        "uq_standard_assets_version_canonical_href", "standard_assets", type_="unique"
    )
    op.drop_column("standard_assets", "content_schema_version")
    op.drop_column("standard_assets", "resource_type")
    op.drop_column("standard_assets", "title")
    op.drop_column("standard_assets", "canonical_href")
