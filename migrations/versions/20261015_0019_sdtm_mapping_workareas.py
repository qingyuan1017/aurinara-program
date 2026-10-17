"""Replace SDTM graph plans with mappings, code workareas, and output selection.

Revision ID: 20261015_0019
Revises: 20261015_0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0019"
down_revision: str | Sequence[str] | None = "20261015_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _revision_table(name: str, variable: bool = False) -> None:
    columns: list[sa.Column[object]] = [
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("domain_code", sa.String(8), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("specification_revision", sa.Integer(), nullable=False),
    ]
    columns.append(
        sa.Column(
            "domain_mapping_revision" if variable else "input_selection_revision",
            sa.Integer(),
            nullable=False,
        )
    )
    columns.extend(
        [
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("alignment_reasons", postgresql.JSONB(astext_type=sa.Text())),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint(["aggregate_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id", name=f"pk_{name}"),
            sa.UniqueConstraint(
                "aggregate_id",
                "domain_code",
                "revision",
                name=(
                    "uq_sdtm_variable_mapping_revision"
                    if variable
                    else "uq_sdtm_domain_mapping_revision"
                ),
            ),
        ]
    )
    op.create_table(name, *columns)
    op.create_index(f"ix_{name}_aggregate_id", name, ["aggregate_id"])
    op.create_index(f"ix_{name}_study_id", name, ["study_id"])
    op.create_index(
        "ix_sdtm_variable_mapping_head" if variable else "ix_sdtm_domain_mapping_head",
        name,
        ["aggregate_id", "domain_code"],
    )


def upgrade() -> None:
    _revision_table("sdtm_domain_mapping_revisions")
    _revision_table("sdtm_variable_mapping_revisions", variable=True)
    op.create_table(
        "sdtm_code_workareas",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("domain_code", sa.String(8), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_sdtm_code_workareas"),
        sa.UniqueConstraint("aggregate_id", "name", name="uq_sdtm_code_workarea_name"),
    )
    op.create_index("ix_sdtm_code_workareas_aggregate_id", "sdtm_code_workareas", ["aggregate_id"])
    op.create_index("ix_sdtm_code_workareas_study_id", "sdtm_code_workareas", ["study_id"])
    op.create_index(
        "ix_sdtm_code_workarea_domain", "sdtm_code_workareas", ["aggregate_id", "domain_code"]
    )
    op.create_table(
        "sdtm_code_revisions",
        sa.Column("workarea_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("specification_revision", sa.Integer(), nullable=False),
        sa.Column("domain_mapping_revision", sa.Integer(), nullable=False),
        sa.Column("variable_mapping_revision", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workarea_id"], ["sdtm_code_workareas.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_sdtm_code_revisions"),
        sa.UniqueConstraint("workarea_id", "revision", name="uq_sdtm_code_revision"),
    )
    op.create_index("ix_sdtm_code_revisions_workarea_id", "sdtm_code_revisions", ["workarea_id"])
    op.create_index("ix_sdtm_code_revisions_aggregate_id", "sdtm_code_revisions", ["aggregate_id"])
    op.create_index("ix_sdtm_code_revisions_study_id", "sdtm_code_revisions", ["study_id"])
    op.create_table(
        "sdtm_output_selections",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("specification_revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_sdtm_output_selections"),
        sa.UniqueConstraint("aggregate_id", name="uq_sdtm_output_selections_aggregate_id"),
    )
    op.create_index("ix_sdtm_output_selections_study_id", "sdtm_output_selections", ["study_id"])

    # Historical evidence is retained but cannot be selected after graph retirement.
    op.execute(
        "UPDATE artifacts SET status = 'stale' "
        "WHERE module_key = 'sdtm' AND source_plan_type = 'sdtm_derivation_plan'"
    )
    op.execute(
        "UPDATE sdtm_acrf_annotations SET status = 'deleted', revision = revision + 1 "
        "WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(links) link "
        "WHERE link->>'target_type' = 'derivation_plan_node')"
    )
    op.execute(
        "DELETE FROM sdtm_domain_source_selections WHERE source_type = 'derived_plan'"
    )
    op.drop_table("sdtm_derivation_plan_revisions")


def downgrade() -> None:
    op.create_table(
        "sdtm_derivation_plan_revisions",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("domain_code", sa.String(8), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("specification_revision", sa.Integer(), nullable=False),
        sa.Column("input_selection_revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("upstream_plan_pins", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("alignment_reasons", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_id"], ["sdtm_workbenches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_sdtm_derivation_plan_revisions"),
        sa.UniqueConstraint(
            "aggregate_id", "domain_code", "revision", name="uq_sdtm_plan_aggregate_domain_revision"
        ),
    )
    op.create_index(
        "ix_sdtm_plan_aggregate_domain",
        "sdtm_derivation_plan_revisions",
        ["aggregate_id", "domain_code"],
    )
    op.create_index(
        "ix_sdtm_derivation_plan_revisions_aggregate_id",
        "sdtm_derivation_plan_revisions",
        ["aggregate_id"],
    )
    op.create_index(
        "ix_sdtm_derivation_plan_revisions_study_id", "sdtm_derivation_plan_revisions", ["study_id"]
    )
    op.drop_table("sdtm_output_selections")
    op.drop_table("sdtm_code_revisions")
    op.drop_table("sdtm_code_workareas")
    op.drop_table("sdtm_variable_mapping_revisions")
    op.drop_table("sdtm_domain_mapping_revisions")
