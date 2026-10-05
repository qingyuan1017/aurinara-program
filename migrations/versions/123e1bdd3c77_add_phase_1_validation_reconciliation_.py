"""add phase 1 validation reconciliation and integration

Revision ID: 123e1bdd3c77
Revises: 20261004_0001
Create Date: 2026-10-04 21:08:55.567239
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "123e1bdd3c77"
down_revision: str | Sequence[str] | None = "20261004_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add immutable validation/reconciliation and integration records."""
    op.create_table(
        "integrations",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("integration_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("external_subject", sa.String(length=255), nullable=True),
        sa.Column("allowed_modules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_integrations_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
        sa.UniqueConstraint("study_id", "integration_code", name=op.f("uq_integrations_study_id")),
    )
    op.create_index(op.f("ix_integrations_study_id"), "integrations", ["study_id"], unique=False)
    op.create_table(
        "reconciliation_runs",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("reconciliation_type", sa.String(length=64), nullable=False),
        sa.Column("reconciliation_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("info_count", sa.Integer(), nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report_artifact_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_reconciliation_runs_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reconciliation_runs")),
    )
    op.create_index(
        op.f("ix_reconciliation_runs_study_id"), "reconciliation_runs", ["study_id"], unique=False
    )
    op.create_table(
        "validation_runs",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("module_key", sa.String(length=32), nullable=False),
        sa.Column("owner_type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("validator_name", sa.String(length=128), nullable=False),
        sa.Column("validator_version", sa.String(length=32), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("info_count", sa.Integer(), nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report_artifact_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_validation_runs_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_validation_runs")),
    )
    op.create_index(
        op.f("ix_validation_runs_study_id"), "validation_runs", ["study_id"], unique=False
    )
    op.create_table(
        "external_identifiers",
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("external_entity_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("target_module", sa.String(length=32), nullable=False),
        sa.Column("target_entity_type", sa.String(length=64), nullable=False),
        sa.Column("target_entity_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            name=op.f("fk_external_identifiers_integration_id_integrations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_identifiers")),
        sa.UniqueConstraint(
            "integration_id",
            "external_entity_type",
            "external_id",
            name=op.f("uq_external_identifiers_integration_id"),
        ),
    )
    op.create_index(
        op.f("ix_external_identifiers_integration_id"),
        "external_identifiers",
        ["integration_id"],
        unique=False,
    )
    op.create_table(
        "integration_secret_versions",
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("encrypted_secret", sa.LargeBinary(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            name=op.f("fk_integration_secret_versions_integration_id_integrations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_secret_versions")),
        sa.UniqueConstraint(
            "integration_id", "version", name=op.f("uq_integration_secret_versions_integration_id")
        ),
    )
    op.create_index(
        op.f("ix_integration_secret_versions_integration_id"),
        "integration_secret_versions",
        ["integration_id"],
        unique=False,
    )
    op.create_table(
        "integration_subscriptions",
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("callback_url", sa.String(length=2048), nullable=False),
        sa.Column("event_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            name=op.f("fk_integration_subscriptions_integration_id_integrations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_subscriptions")),
    )
    op.create_index(
        op.f("ix_integration_subscriptions_integration_id"),
        "integration_subscriptions",
        ["integration_id"],
        unique=False,
    )
    op.create_table(
        "integration_delivery_attempts",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_revision", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("destination_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_excerpt", sa.String(length=65536), nullable=True),
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["outbox_events.id"],
            name=op.f("fk_integration_delivery_attempts_event_id_outbox_events"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["integration_subscriptions.id"],
            name=op.f("fk_integration_delivery_attempts_subscription_id_integration_subscriptions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_delivery_attempts")),
        sa.UniqueConstraint(
            "event_id",
            "subscription_id",
            "subscription_revision",
            "attempt_number",
            name=op.f("uq_integration_delivery_attempts_event_id"),
        ),
    )
    op.create_index(
        op.f("ix_integration_delivery_attempts_event_id"),
        "integration_delivery_attempts",
        ["event_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove integration and evidence records in dependency order."""
    op.drop_index(
        op.f("ix_integration_delivery_attempts_event_id"),
        table_name="integration_delivery_attempts",
    )
    op.drop_table("integration_delivery_attempts")
    op.drop_index(
        op.f("ix_integration_subscriptions_integration_id"), table_name="integration_subscriptions"
    )
    op.drop_table("integration_subscriptions")
    op.drop_index(
        op.f("ix_integration_secret_versions_integration_id"),
        table_name="integration_secret_versions",
    )
    op.drop_table("integration_secret_versions")
    op.drop_index(op.f("ix_external_identifiers_integration_id"), table_name="external_identifiers")
    op.drop_table("external_identifiers")
    op.drop_index(op.f("ix_validation_runs_study_id"), table_name="validation_runs")
    op.drop_table("validation_runs")
    op.drop_index(op.f("ix_reconciliation_runs_study_id"), table_name="reconciliation_runs")
    op.drop_table("reconciliation_runs")
    op.drop_index(op.f("ix_integrations_study_id"), table_name="integrations")
    op.drop_table("integrations")
