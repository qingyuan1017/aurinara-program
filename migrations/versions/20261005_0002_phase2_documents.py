"""implement Phase 2 Documents persistence

Revision ID: 20261005_0002
Revises: b8912d69532e
Create Date: 2026-10-05 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261005_0002"
down_revision: str | Sequence[str] | None = "b8912d69532e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add immutable document content, USDM, and Protocol evidence records."""

    op.add_column(
        "documents",
        sa.Column(
            "content_schema_version",
            sa.String(length=32),
            server_default="1.0.0",
            nullable=False,
        ),
    )
    op.alter_column("documents", "content_schema_version", server_default=None)
    op.add_column("documents", sa.Column("source_pdf_file_id", sa.Uuid(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "related_document_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("documents", "related_document_ids", server_default=None)
    op.create_foreign_key(
        op.f("fk_documents_source_pdf_file_id_source_files"),
        "documents",
        "source_files",
        ["source_pdf_file_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "document_contents",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_contents_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_document_contents_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_contents")),
        sa.UniqueConstraint(
            "document_id", "revision", name=op.f("uq_document_contents_document_id")
        ),
    )
    op.create_index(
        op.f("ix_document_contents_document_id"),
        "document_contents",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_contents_study_id"),
        "document_contents",
        ["study_id"],
        unique=False,
    )

    op.create_table(
        "protocol_usdm_documents",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("usdm_version", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_protocol_usdm_documents_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_protocol_usdm_documents_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_protocol_usdm_documents")),
        sa.UniqueConstraint(
            "document_id", "revision", name=op.f("uq_protocol_usdm_documents_document_id")
        ),
    )
    op.create_index(
        op.f("ix_protocol_usdm_documents_document_id"),
        "protocol_usdm_documents",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_protocol_usdm_documents_study_id"),
        "protocol_usdm_documents",
        ["study_id"],
        unique=False,
    )

    op.create_table(
        "protocol_evidence",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("source_pdf_file_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("region", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("excerpt", sa.String(length=4000), nullable=True),
        sa.Column(
            "linked_usdm_entity_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("question", sa.String(length=4000), nullable=True),
        sa.Column("resolution", sa.String(length=4000), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_protocol_evidence_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_pdf_file_id"],
            ["source_files.id"],
            name=op.f("fk_protocol_evidence_source_pdf_file_id_source_files"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_protocol_evidence_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_protocol_evidence")),
    )
    op.create_index(
        op.f("ix_protocol_evidence_document_id"),
        "protocol_evidence",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_protocol_evidence_study_id"),
        "protocol_evidence",
        ["study_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove Phase 2 Documents persistence."""

    op.drop_index(op.f("ix_protocol_evidence_study_id"), table_name="protocol_evidence")
    op.drop_index(op.f("ix_protocol_evidence_document_id"), table_name="protocol_evidence")
    op.drop_table("protocol_evidence")
    op.drop_index(op.f("ix_protocol_usdm_documents_study_id"), table_name="protocol_usdm_documents")
    op.drop_index(
        op.f("ix_protocol_usdm_documents_document_id"), table_name="protocol_usdm_documents"
    )
    op.drop_table("protocol_usdm_documents")
    op.drop_index(op.f("ix_document_contents_study_id"), table_name="document_contents")
    op.drop_index(op.f("ix_document_contents_document_id"), table_name="document_contents")
    op.drop_table("document_contents")
    op.drop_constraint(
        op.f("fk_documents_source_pdf_file_id_source_files"), "documents", type_="foreignkey"
    )
    op.drop_column("documents", "related_document_ids")
    op.drop_column("documents", "source_pdf_file_id")
    op.drop_column("documents", "content_schema_version")
