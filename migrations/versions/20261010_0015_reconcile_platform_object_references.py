"""Reconcile platform object references and package artifact constraints.

Revision ID: 20261010_0015
Revises: 20261010_0014

Some development databases were stamped through ``20261010_0014`` before
the opaque object-reference columns were introduced. A separate reconciliation
revision keeps the ordered migration history valid for both those databases and
clean installs. It also restores the artifact foreign keys owned by the Phase 5
submission-package migration when an existing database is missing them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261010_0015"
down_revision: str | Sequence[str] | None = "20261010_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _unique_constraint_name(table_name: str, column_name: str) -> str | None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints(table_name):
        if constraint.get("column_names") == [column_name]:
            name = constraint.get("name")
            return str(name) if name is not None else None
    return None


def _has_foreign_key(
    table_name: str,
    column_name: str,
    referred_table: str,
    referred_column: str,
) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        foreign_key.get("constrained_columns") == [column_name]
        and foreign_key.get("referred_table") == referred_table
        and foreign_key.get("referred_columns") == [referred_column]
        for foreign_key in inspector.get_foreign_keys(table_name)
    )


def upgrade() -> None:
    if not _has_column("artifacts", "platform_reference_id"):
        op.add_column("artifacts", sa.Column("platform_reference_id", sa.Uuid()))
    if _unique_constraint_name("artifacts", "platform_reference_id") is None:
        op.create_unique_constraint(
            "uq_artifacts_platform_reference_id",
            "artifacts",
            ["platform_reference_id"],
        )

    if not _has_column("source_files", "platform_reference_id"):
        op.add_column("source_files", sa.Column("platform_reference_id", sa.Uuid()))
    if _unique_constraint_name("source_files", "platform_reference_id") is None:
        op.create_unique_constraint(
            "uq_source_files_platform_reference_id",
            "source_files",
            ["platform_reference_id"],
        )

    if not _has_foreign_key("submission_packages", "zip_artifact_id", "artifacts", "id"):
        op.create_foreign_key(
            "fk_submission_packages_zip_artifact_id_artifacts",
            "submission_packages",
            "artifacts",
            ["zip_artifact_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    if not _has_foreign_key("submission_packages", "report_artifact_id", "artifacts", "id"):
        op.create_foreign_key(
            "fk_submission_packages_report_artifact_id_artifacts",
            "submission_packages",
            "artifacts",
            ["report_artifact_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    source_constraint = _unique_constraint_name("source_files", "platform_reference_id")
    if source_constraint is not None:
        op.drop_constraint(source_constraint, "source_files", type_="unique")
    if _has_column("source_files", "platform_reference_id"):
        op.drop_column("source_files", "platform_reference_id")

    artifact_constraint = _unique_constraint_name("artifacts", "platform_reference_id")
    if artifact_constraint is not None:
        op.drop_constraint(artifact_constraint, "artifacts", type_="unique")
    if _has_column("artifacts", "platform_reference_id"):
        op.drop_column("artifacts", "platform_reference_id")

    # The package foreign keys belong to the earlier Phase 5 migration and must
    # remain present when downgrading to 20261010_0014.
