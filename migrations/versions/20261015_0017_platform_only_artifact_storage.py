"""Allow immutable artifact metadata to use Platform-only storage.

Revision ID: 20261015_0017
Revises: 20261012_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0017"
down_revision: str | Sequence[str] | None = "20261012_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("artifacts", "object_key", existing_type=sa.String(255), nullable=True)
    op.create_check_constraint(
        "ck_artifacts_storage_locator",
        "artifacts",
        "object_key IS NOT NULL OR platform_object_id IS NOT NULL",
    )
    op.alter_column("source_files", "object_key", existing_type=sa.String(255), nullable=True)
    op.create_check_constraint(
        "ck_source_files_storage_locator",
        "source_files",
        "object_key IS NOT NULL OR platform_object_id IS NOT NULL",
    )


def downgrade() -> None:
    # A downgrade is deliberately blocked while Platform-only rows exist.
    connection = op.get_bind()
    for table in ("artifacts", "source_files"):
        missing = connection.scalar(
            sa.text(f"SELECT count(*) FROM {table} WHERE object_key IS NULL")
        )
        if missing:
            raise RuntimeError(
                f"Cannot downgrade while {table} contains Platform-only storage rows"
            )
    op.drop_constraint("ck_source_files_storage_locator", "source_files", type_="check")
    op.alter_column("source_files", "object_key", existing_type=sa.String(255), nullable=False)
    op.drop_constraint("ck_artifacts_storage_locator", "artifacts", type_="check")
    op.alter_column("artifacts", "object_key", existing_type=sa.String(255), nullable=False)
