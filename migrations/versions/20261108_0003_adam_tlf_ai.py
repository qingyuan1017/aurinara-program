"""add ADaM and TLF proposal provenance and portfolio inputs

Revision ID: 20261108_0003
Revises: 20261107_0002
Create Date: 2026-11-08 00:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261108_0003"
down_revision: str | Sequence[str] | None = "20261107_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ADAM_TABLES = (
    "adam_specification_revisions",
    "adam_derivation_plan_revisions",
    "adam_define_revisions",
    "adam_adrg_revisions",
)


def _add_provenance(table: str) -> None:
    op.add_column(table, sa.Column("originating_proposal_id", sa.Uuid(), nullable=True))
    op.add_column(table, sa.Column("originating_decision_id", sa.Uuid(), nullable=True))
    op.create_index(
        f"ix_{table}_originating_proposal_id",
        table,
        ["originating_proposal_id"],
        unique=False,
    )
    op.create_index(
        f"ix_{table}_originating_decision_id",
        table,
        ["originating_decision_id"],
        unique=False,
    )
    op.create_foreign_key(
        f"fk_{table}_originating_proposal_id",
        table,
        "authoring_proposals",
        ["originating_proposal_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        f"fk_{table}_originating_decision_id",
        table,
        "proposal_review_decisions",
        ["originating_decision_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def _drop_provenance(table: str) -> None:
    op.drop_constraint(f"fk_{table}_originating_decision_id", table, type_="foreignkey")
    op.drop_constraint(f"fk_{table}_originating_proposal_id", table, type_="foreignkey")
    op.drop_index(f"ix_{table}_originating_decision_id", table_name=table)
    op.drop_index(f"ix_{table}_originating_proposal_id", table_name=table)
    op.drop_column(table, "originating_decision_id")
    op.drop_column(table, "originating_proposal_id")


def upgrade() -> None:
    for table in ADAM_TABLES:
        _add_provenance(table)
    _add_provenance("tlf_authoring_revisions")
    op.alter_column(
        "tlf_authoring_revisions",
        "content_type",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_table(
        "tlf_input_selections",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["aggregate_id"], ["tlf_workbenches.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("aggregate_id"),
    )
    op.create_index(
        "ix_tlf_input_selections_study_id",
        "tlf_input_selections",
        ["study_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tlf_input_selections_study_id", table_name="tlf_input_selections")
    op.drop_table("tlf_input_selections")
    op.alter_column(
        "tlf_authoring_revisions",
        "content_type",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    _drop_provenance("tlf_authoring_revisions")
    for table in reversed(ADAM_TABLES):
        _drop_provenance(table)
