"""add durable AI proposal and human review evidence

Revision ID: 20261107_0002
Revises: 20261105_0001
Create Date: 2026-11-07 22:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261107_0002"
down_revision: str | Sequence[str] | None = "20261105_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_generation_runs",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("module_key", sa.String(length=32), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_type", sa.String(length=96), nullable=False),
        sa.Column("proposal_schema_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("context_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("instruction_version", sa.String(length=64), nullable=False),
        sa.Column("target", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("guidance", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column(
            "generation_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("response_checksum", sa.String(length=64), nullable=True),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_ai_generation_runs_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_generation_runs")),
    )
    op.create_index(
        "ix_ai_generation_runs_owner",
        "ai_generation_runs",
        ["module_key", "aggregate_id", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_ai_generation_runs_study_id"), "ai_generation_runs", ["study_id"])

    op.create_table(
        "authoring_proposals",
        sa.Column("generation_run_id", sa.Uuid(), nullable=False),
        sa.Column("supersedes_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("module_key", sa.String(length=32), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_type", sa.String(length=96), nullable=False),
        sa.Column("proposal_schema_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("context_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("instruction_version", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unresolved_items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_limitations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation_issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["generation_run_id"],
            ["ai_generation_runs.id"],
            name=op.f("fk_authoring_proposals_generation_run_id_ai_generation_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_authoring_proposals_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_proposal_id"],
            ["authoring_proposals.id"],
            name=op.f(
                "fk_authoring_proposals_supersedes_proposal_id_authoring_proposals"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_authoring_proposals")),
        sa.UniqueConstraint(
            "generation_run_id", name="uq_authoring_proposals_generation_run"
        ),
    )
    op.create_index(
        "ix_authoring_proposals_owner",
        "authoring_proposals",
        ["module_key", "aggregate_id", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_authoring_proposals_study_id"), "authoring_proposals", ["study_id"])
    op.create_index(
        op.f("ix_authoring_proposals_supersedes_proposal_id"),
        "authoring_proposals",
        ["supersedes_proposal_id"],
    )

    op.create_table(
        "proposal_review_decisions",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reviewer", sa.String(length=255), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "resulting_revision_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["authoring_proposals.id"],
            name=op.f("fk_proposal_review_decisions_proposal_id_authoring_proposals"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_proposal_review_decisions_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_review_decisions")),
        sa.UniqueConstraint("proposal_id", name="uq_proposal_review_decisions_proposal"),
    )
    op.create_index(
        op.f("ix_proposal_review_decisions_proposal_id"),
        "proposal_review_decisions",
        ["proposal_id"],
    )
    op.create_index(
        op.f("ix_proposal_review_decisions_study_id"),
        "proposal_review_decisions",
        ["study_id"],
    )
    provenance_tables = (
        "sdtm_specification_revisions",
        "sdtm_domain_mapping_revisions",
        "sdtm_variable_mapping_revisions",
        "sdtm_code_revisions",
        "sdtm_define_revisions",
        "sdtm_csdrg_revisions",
    )
    for table_name in provenance_tables:
        op.add_column(table_name, sa.Column("originating_proposal_id", sa.Uuid(), nullable=True))
        op.add_column(table_name, sa.Column("originating_decision_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table_name}_originating_proposal_id_authoring_proposals"),
            table_name,
            "authoring_proposals",
            ["originating_proposal_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_foreign_key(
            op.f(
                f"fk_{table_name}_originating_decision_id_proposal_review_decisions"
            ),
            table_name,
            "proposal_review_decisions",
            ["originating_decision_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(
            f"ix_{table_name}_originating_proposal_id",
            table_name,
            ["originating_proposal_id"],
        )
        op.create_index(
            f"ix_{table_name}_originating_decision_id",
            table_name,
            ["originating_decision_id"],
        )


def downgrade() -> None:
    provenance_tables = (
        "sdtm_specification_revisions",
        "sdtm_domain_mapping_revisions",
        "sdtm_variable_mapping_revisions",
        "sdtm_code_revisions",
        "sdtm_define_revisions",
        "sdtm_csdrg_revisions",
    )
    for table_name in provenance_tables:
        op.drop_index(
            f"ix_{table_name}_originating_decision_id", table_name=table_name
        )
        op.drop_index(
            f"ix_{table_name}_originating_proposal_id", table_name=table_name
        )
        op.drop_constraint(
            op.f(
                f"fk_{table_name}_originating_decision_id_proposal_review_decisions"
            ),
            table_name,
            type_="foreignkey",
        )
        op.drop_constraint(
            op.f(f"fk_{table_name}_originating_proposal_id_authoring_proposals"),
            table_name,
            type_="foreignkey",
        )
        op.drop_column(table_name, "originating_decision_id")
        op.drop_column(table_name, "originating_proposal_id")
    op.drop_index(
        op.f("ix_proposal_review_decisions_study_id"),
        table_name="proposal_review_decisions",
    )
    op.drop_index(
        op.f("ix_proposal_review_decisions_proposal_id"),
        table_name="proposal_review_decisions",
    )
    op.drop_table("proposal_review_decisions")
    op.drop_index(
        op.f("ix_authoring_proposals_supersedes_proposal_id"),
        table_name="authoring_proposals",
    )
    op.drop_index(op.f("ix_authoring_proposals_study_id"), table_name="authoring_proposals")
    op.drop_index("ix_authoring_proposals_owner", table_name="authoring_proposals")
    op.drop_table("authoring_proposals")
    op.drop_index(op.f("ix_ai_generation_runs_study_id"), table_name="ai_generation_runs")
    op.drop_index("ix_ai_generation_runs_owner", table_name="ai_generation_runs")
    op.drop_table("ai_generation_runs")
