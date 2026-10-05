"""complete phase 1 shared services

Revision ID: 24fae62c2c87
Revises: 123e1bdd3c77
Create Date: 2026-10-04 21:50:06.567111
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "24fae62c2c87"
down_revision: str | Sequence[str] | None = "123e1bdd3c77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create provider, dependency, reference, review, rule, and traceability tables."""
    op.create_table(
        "standard_products",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_standard_products")),
        sa.UniqueConstraint("code", name=op.f("uq_standard_products_code")),
    )
    op.create_table(
        "template_families",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_template_families")),
        sa.UniqueConstraint("code", name=op.f("uq_template_families_code")),
    )
    op.create_table(
        "terminology_releases",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("asset_path", sa.String(length=512), nullable=False),
        sa.Column("applicable_modules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminology_releases")),
    )
    op.create_table(
        "validation_rules",
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("module_key", sa.String(length=32), nullable=False),
        sa.Column("applicability", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parameter_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("default_severity", sa.String(length=16), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_validation_rules")),
    )
    op.create_index(
        op.f("ix_validation_rules_rule_id"), "validation_rules", ["rule_id"], unique=False
    )
    op.create_table(
        "adam_workbenches",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_adam_workbenches_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_adam_workbenches")),
        sa.UniqueConstraint("study_id", "code", name=op.f("uq_adam_workbenches_study_id")),
    )
    op.create_index(
        op.f("ix_adam_workbenches_study_id"), "adam_workbenches", ["study_id"], unique=False
    )
    op.create_table(
        "documents",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_documents_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("study_id", "code", name=op.f("uq_documents_study_id")),
    )
    op.create_index(op.f("ix_documents_study_id"), "documents", ["study_id"], unique=False)
    op.create_table(
        "idempotency_records",
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("route", sa.String(length=255), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_idempotency_records_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_records")),
        sa.UniqueConstraint(
            "subject", "route", "study_id", "key", name=op.f("uq_idempotency_records_subject")
        ),
    )
    op.create_table(
        "raw_workbenches",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_raw_workbenches_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_workbenches")),
        sa.UniqueConstraint("study_id", "code", name=op.f("uq_raw_workbenches_study_id")),
    )
    op.create_index(
        op.f("ix_raw_workbenches_study_id"), "raw_workbenches", ["study_id"], unique=False
    )
    op.create_table(
        "reference_records",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("reference_type", sa.String(length=32), nullable=False),
        sa.Column("natural_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_reference_records_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reference_records")),
        sa.UniqueConstraint(
            "study_id", "reference_type", "natural_key", name=op.f("uq_reference_records_study_id")
        ),
    )
    op.create_index(
        op.f("ix_reference_records_study_id"), "reference_records", ["study_id"], unique=False
    )
    op.create_table(
        "review_items",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("target_module", sa.String(length=32), nullable=False),
        sa.Column("target_entity_type", sa.String(length=64), nullable=False),
        sa.Column("target_entity_id", sa.Uuid(), nullable=False),
        sa.Column("field_path", sa.String(length=512), nullable=True),
        sa.Column("question", sa.String(length=4000), nullable=False),
        sa.Column("assignee", sa.String(length=255), nullable=True),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("disposition", sa.String(length=64), nullable=True),
        sa.Column("resolution", sa.String(length=4000), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_review_items_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_items")),
    )
    op.create_index(op.f("ix_review_items_study_id"), "review_items", ["study_id"], unique=False)
    op.create_table(
        "sdtm_workbenches",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_sdtm_workbenches_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sdtm_workbenches")),
        sa.UniqueConstraint("study_id", "code", name=op.f("uq_sdtm_workbenches_study_id")),
    )
    op.create_index(
        op.f("ix_sdtm_workbenches_study_id"), "sdtm_workbenches", ["study_id"], unique=False
    )
    op.create_table(
        "standard_versions",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("asset_path", sa.String(length=512), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("applicable_modules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("purposes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("compatibility", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["standard_products.id"],
            name=op.f("fk_standard_versions_product_id_standard_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_standard_versions")),
        sa.UniqueConstraint("product_id", "version", name=op.f("uq_standard_versions_product_id")),
    )
    op.create_index(
        op.f("ix_standard_versions_product_id"), "standard_versions", ["product_id"], unique=False
    )
    op.create_table(
        "template_versions",
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("asset_path", sa.String(length=512), nullable=False),
        sa.Column("applicable_modules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "content_schema_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("renderer_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("blank_structure", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["template_families.id"],
            name=op.f("fk_template_versions_family_id_template_families"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_template_versions")),
        sa.UniqueConstraint("family_id", "version", name=op.f("uq_template_versions_family_id")),
    )
    op.create_index(
        op.f("ix_template_versions_family_id"), "template_versions", ["family_id"], unique=False
    )
    op.create_table(
        "terminology_codelists",
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["terminology_releases.id"],
            name=op.f("fk_terminology_codelists_release_id_terminology_releases"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminology_codelists")),
        sa.UniqueConstraint("release_id", "code", name=op.f("uq_terminology_codelists_release_id")),
    )
    op.create_index(
        op.f("ix_terminology_codelists_release_id"),
        "terminology_codelists",
        ["release_id"],
        unique=False,
    )
    op.create_table(
        "terminology_extensions",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_release_id", sa.Uuid(), nullable=False),
        sa.Column("codelist_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["base_release_id"],
            ["terminology_releases.id"],
            name=op.f("fk_terminology_extensions_base_release_id_terminology_releases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_terminology_extensions_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminology_extensions")),
        sa.UniqueConstraint("study_id", "code", name=op.f("uq_terminology_extensions_study_id")),
    )
    op.create_index(
        op.f("ix_terminology_extensions_study_id"),
        "terminology_extensions",
        ["study_id"],
        unique=False,
    )
    op.create_table(
        "tlf_workbenches",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_tlf_workbenches_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tlf_workbenches")),
        sa.UniqueConstraint("study_id", "code", name=op.f("uq_tlf_workbenches_study_id")),
    )
    op.create_index(
        op.f("ix_tlf_workbenches_study_id"), "tlf_workbenches", ["study_id"], unique=False
    )
    op.create_table(
        "trace_links",
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("source_module", sa.String(length=32), nullable=False),
        sa.Column("source_entity_type", sa.String(length=64), nullable=False),
        sa.Column("source_entity_id", sa.Uuid(), nullable=False),
        sa.Column("target_module", sa.String(length=32), nullable=False),
        sa.Column("target_entity_type", sa.String(length=64), nullable=False),
        sa.Column("target_entity_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_trace_links_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trace_links")),
        sa.UniqueConstraint(
            "study_id",
            "relationship_type",
            "source_module",
            "source_entity_type",
            "source_entity_id",
            "target_module",
            "target_entity_type",
            "target_entity_id",
            name=op.f("uq_trace_links_study_id"),
        ),
    )
    op.create_index(op.f("ix_trace_links_study_id"), "trace_links", ["study_id"], unique=False)
    op.create_table(
        "validation_rule_packs",
        sa.Column("study_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("selections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_validation_rule_packs_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_validation_rule_packs")),
        sa.UniqueConstraint("study_id", "code", name=op.f("uq_validation_rule_packs_study_id")),
    )
    op.create_index(
        op.f("ix_validation_rule_packs_study_id"),
        "validation_rule_packs",
        ["study_id"],
        unique=False,
    )
    op.create_table(
        "adam_dependency_selections",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["aggregate_id"],
            ["adam_workbenches.id"],
            name=op.f("fk_adam_dependency_selections_aggregate_id_adam_workbenches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_adam_dependency_selections_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_adam_dependency_selections")),
        sa.UniqueConstraint(
            "aggregate_id", name=op.f("uq_adam_dependency_selections_aggregate_id")
        ),
    )
    op.create_index(
        op.f("ix_adam_dependency_selections_study_id"),
        "adam_dependency_selections",
        ["study_id"],
        unique=False,
    )
    op.create_table(
        "document_dependency_selections",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["aggregate_id"],
            ["documents.id"],
            name=op.f("fk_document_dependency_selections_aggregate_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_document_dependency_selections_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_dependency_selections")),
        sa.UniqueConstraint(
            "aggregate_id", name=op.f("uq_document_dependency_selections_aggregate_id")
        ),
    )
    op.create_index(
        op.f("ix_document_dependency_selections_study_id"),
        "document_dependency_selections",
        ["study_id"],
        unique=False,
    )
    op.create_table(
        "raw_dependency_selections",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["aggregate_id"],
            ["raw_workbenches.id"],
            name=op.f("fk_raw_dependency_selections_aggregate_id_raw_workbenches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_raw_dependency_selections_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_dependency_selections")),
        sa.UniqueConstraint("aggregate_id", name=op.f("uq_raw_dependency_selections_aggregate_id")),
    )
    op.create_index(
        op.f("ix_raw_dependency_selections_study_id"),
        "raw_dependency_selections",
        ["study_id"],
        unique=False,
    )
    op.create_table(
        "reference_record_revisions",
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["reference_id"],
            ["reference_records.id"],
            name=op.f("fk_reference_record_revisions_reference_id_reference_records"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_reference_record_revisions_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reference_record_revisions")),
        sa.UniqueConstraint(
            "reference_id", "revision", name=op.f("uq_reference_record_revisions_reference_id")
        ),
    )
    op.create_index(
        op.f("ix_reference_record_revisions_reference_id"),
        "reference_record_revisions",
        ["reference_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reference_record_revisions_study_id"),
        "reference_record_revisions",
        ["study_id"],
        unique=False,
    )
    op.create_table(
        "review_comments",
        sa.Column("review_item_id", sa.Uuid(), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=False),
        sa.Column("body", sa.String(length=8000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["review_item_id"],
            ["review_items.id"],
            name=op.f("fk_review_comments_review_item_id_review_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_comments")),
    )
    op.create_index(
        op.f("ix_review_comments_review_item_id"),
        "review_comments",
        ["review_item_id"],
        unique=False,
    )
    op.create_table(
        "sdtm_dependency_selections",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["aggregate_id"],
            ["sdtm_workbenches.id"],
            name=op.f("fk_sdtm_dependency_selections_aggregate_id_sdtm_workbenches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_sdtm_dependency_selections_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sdtm_dependency_selections")),
        sa.UniqueConstraint(
            "aggregate_id", name=op.f("uq_sdtm_dependency_selections_aggregate_id")
        ),
    )
    op.create_index(
        op.f("ix_sdtm_dependency_selections_study_id"),
        "sdtm_dependency_selections",
        ["study_id"],
        unique=False,
    )
    op.create_table(
        "terminology_extension_revisions",
        sa.Column("extension_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["extension_id"],
            ["terminology_extensions.id"],
            name=op.f("fk_terminology_extension_revisions_extension_id_terminology_extensions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_terminology_extension_revisions_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminology_extension_revisions")),
        sa.UniqueConstraint(
            "extension_id", "revision", name=op.f("uq_terminology_extension_revisions_extension_id")
        ),
    )
    op.create_index(
        op.f("ix_terminology_extension_revisions_extension_id"),
        "terminology_extension_revisions",
        ["extension_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_terminology_extension_revisions_study_id"),
        "terminology_extension_revisions",
        ["study_id"],
        unique=False,
    )
    op.create_table(
        "terminology_terms",
        sa.Column("codelist_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("submission_value", sa.String(length=255), nullable=False),
        sa.Column("decode", sa.String(length=1000), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["codelist_id"],
            ["terminology_codelists.id"],
            name=op.f("fk_terminology_terms_codelist_id_terminology_codelists"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminology_terms")),
        sa.UniqueConstraint("codelist_id", "code", name=op.f("uq_terminology_terms_codelist_id")),
    )
    op.create_index(
        op.f("ix_terminology_terms_codelist_id"), "terminology_terms", ["codelist_id"], unique=False
    )
    op.create_table(
        "tlf_dependency_selections",
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["aggregate_id"],
            ["tlf_workbenches.id"],
            name=op.f("fk_tlf_dependency_selections_aggregate_id_tlf_workbenches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
            name=op.f("fk_tlf_dependency_selections_study_id_studies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tlf_dependency_selections")),
        sa.UniqueConstraint("aggregate_id", name=op.f("uq_tlf_dependency_selections_aggregate_id")),
    )
    op.create_index(
        op.f("ix_tlf_dependency_selections_study_id"),
        "tlf_dependency_selections",
        ["study_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop Phase 1 shared-service tables in dependency order."""
    op.drop_index(
        op.f("ix_tlf_dependency_selections_study_id"), table_name="tlf_dependency_selections"
    )
    op.drop_table("tlf_dependency_selections")
    op.drop_index(op.f("ix_terminology_terms_codelist_id"), table_name="terminology_terms")
    op.drop_table("terminology_terms")
    op.drop_index(
        op.f("ix_terminology_extension_revisions_study_id"),
        table_name="terminology_extension_revisions",
    )
    op.drop_index(
        op.f("ix_terminology_extension_revisions_extension_id"),
        table_name="terminology_extension_revisions",
    )
    op.drop_table("terminology_extension_revisions")
    op.drop_index(
        op.f("ix_sdtm_dependency_selections_study_id"), table_name="sdtm_dependency_selections"
    )
    op.drop_table("sdtm_dependency_selections")
    op.drop_index(op.f("ix_review_comments_review_item_id"), table_name="review_comments")
    op.drop_table("review_comments")
    op.drop_index(
        op.f("ix_reference_record_revisions_study_id"), table_name="reference_record_revisions"
    )
    op.drop_index(
        op.f("ix_reference_record_revisions_reference_id"), table_name="reference_record_revisions"
    )
    op.drop_table("reference_record_revisions")
    op.drop_index(
        op.f("ix_raw_dependency_selections_study_id"), table_name="raw_dependency_selections"
    )
    op.drop_table("raw_dependency_selections")
    op.drop_index(
        op.f("ix_document_dependency_selections_study_id"),
        table_name="document_dependency_selections",
    )
    op.drop_table("document_dependency_selections")
    op.drop_index(
        op.f("ix_adam_dependency_selections_study_id"), table_name="adam_dependency_selections"
    )
    op.drop_table("adam_dependency_selections")
    op.drop_index(op.f("ix_validation_rule_packs_study_id"), table_name="validation_rule_packs")
    op.drop_table("validation_rule_packs")
    op.drop_index(op.f("ix_trace_links_study_id"), table_name="trace_links")
    op.drop_table("trace_links")
    op.drop_index(op.f("ix_tlf_workbenches_study_id"), table_name="tlf_workbenches")
    op.drop_table("tlf_workbenches")
    op.drop_index(op.f("ix_terminology_extensions_study_id"), table_name="terminology_extensions")
    op.drop_table("terminology_extensions")
    op.drop_index(op.f("ix_terminology_codelists_release_id"), table_name="terminology_codelists")
    op.drop_table("terminology_codelists")
    op.drop_index(op.f("ix_template_versions_family_id"), table_name="template_versions")
    op.drop_table("template_versions")
    op.drop_index(op.f("ix_standard_versions_product_id"), table_name="standard_versions")
    op.drop_table("standard_versions")
    op.drop_index(op.f("ix_sdtm_workbenches_study_id"), table_name="sdtm_workbenches")
    op.drop_table("sdtm_workbenches")
    op.drop_index(op.f("ix_review_items_study_id"), table_name="review_items")
    op.drop_table("review_items")
    op.drop_index(op.f("ix_reference_records_study_id"), table_name="reference_records")
    op.drop_table("reference_records")
    op.drop_index(op.f("ix_raw_workbenches_study_id"), table_name="raw_workbenches")
    op.drop_table("raw_workbenches")
    op.drop_table("idempotency_records")
    op.drop_index(op.f("ix_documents_study_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_adam_workbenches_study_id"), table_name="adam_workbenches")
    op.drop_table("adam_workbenches")
    op.drop_index(op.f("ix_validation_rules_rule_id"), table_name="validation_rules")
    op.drop_table("validation_rules")
    op.drop_table("terminology_releases")
    op.drop_table("template_families")
    op.drop_table("standard_products")
