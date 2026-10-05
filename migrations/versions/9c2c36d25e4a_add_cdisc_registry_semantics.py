"""add CDISC registry semantics

Revision ID: 9c2c36d25e4a
Revises: 779018dbe1b7
Create Date: 2026-10-04 23:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9c2c36d25e4a"
down_revision: str | Sequence[str] | None = "779018dbe1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add exact CDISC product, release, concept, asset, and compatibility metadata."""

    op.add_column(
        "standard_products",
        sa.Column("provider", sa.String(length=64), server_default="AURINARA", nullable=False),
    )
    op.add_column(
        "standard_products",
        sa.Column("family", sa.String(length=64), server_default="other", nullable=False),
    )
    op.add_column(
        "standard_products",
        sa.Column("product_type", sa.String(length=64), server_default="other", nullable=False),
    )
    op.add_column(
        "standard_products",
        sa.Column("scope", sa.String(length=64), server_default="cross_domain", nullable=False),
    )
    op.add_column("standard_versions", sa.Column("publication_date", sa.Date(), nullable=True))
    op.add_column(
        "standard_versions", sa.Column("library_href", sa.String(length=1000), nullable=True)
    )
    op.add_column(
        "standard_versions",
        sa.Column(
            "content_schema_version",
            sa.String(length=32),
            server_default="1.0.0",
            nullable=False,
        ),
    )
    op.create_table(
        "standard_assets",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("asset_path", sa.String(length=512), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["standard_versions.id"],
            name=op.f("fk_standard_assets_version_id_standard_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_standard_assets")),
        sa.UniqueConstraint(
            "version_id", "role", "asset_path", name="uq_standard_assets_version_id"
        ),
    )
    op.create_index(
        op.f("ix_standard_assets_version_id"), "standard_assets", ["version_id"], unique=False
    )
    op.create_table(
        "standard_version_compatibilities",
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("target_version_id", sa.Uuid(), nullable=False),
        sa.Column("relationship", sa.String(length=64), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["standard_versions.id"],
            name=op.f("fk_standard_version_compatibilities_source_version_id_standard_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_version_id"],
            ["standard_versions.id"],
            name=op.f("fk_standard_version_compatibilities_target_version_id_standard_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_standard_version_compatibilities")),
        sa.UniqueConstraint(
            "source_version_id",
            "target_version_id",
            "relationship",
            name="uq_standard_version_compatibilities_source_version_id",
        ),
    )
    op.create_index(
        op.f("ix_standard_version_compatibilities_source_version_id"),
        "standard_version_compatibilities",
        ["source_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_standard_version_compatibilities_target_version_id"),
        "standard_version_compatibilities",
        ["target_version_id"],
        unique=False,
    )

    op.add_column(
        "terminology_releases",
        sa.Column("provider", sa.String(length=64), server_default="AURINARA", nullable=False),
    )
    op.add_column(
        "terminology_releases",
        sa.Column("product", sa.String(length=64), server_default="other", nullable=False),
    )
    op.add_column("terminology_releases", sa.Column("publication_date", sa.Date(), nullable=True))
    op.add_column(
        "terminology_releases",
        sa.Column("library_href", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "terminology_releases",
        sa.Column(
            "content_schema_version",
            sa.String(length=32),
            server_default="1.0.0",
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        op.f("uq_terminology_releases_code"), "terminology_releases", ["code", "version"]
    )
    op.add_column(
        "terminology_codelists", sa.Column("concept_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "terminology_codelists",
        sa.Column("submission_value", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "terminology_codelists", sa.Column("definition", sa.String(length=4000), nullable=True)
    )
    op.add_column(
        "terminology_codelists",
        sa.Column("preferred_term", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "terminology_codelists",
        sa.Column(
            "synonyms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "terminology_codelists",
        sa.Column("extensible", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(
        sa.text("UPDATE terminology_codelists SET extensible = true WHERE code = 'ISSUE_SEVERITY'")
    )
    op.create_index(
        op.f("ix_terminology_codelists_concept_id"),
        "terminology_codelists",
        ["concept_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_terminology_codelists_release_concept_id",
        "terminology_codelists",
        ["release_id", "concept_id"],
    )
    op.create_unique_constraint(
        "uq_terminology_codelists_release_submission_value",
        "terminology_codelists",
        ["release_id", "submission_value"],
    )
    op.add_column("terminology_terms", sa.Column("concept_id", sa.String(length=64), nullable=True))
    op.add_column(
        "terminology_terms", sa.Column("definition", sa.String(length=4000), nullable=True)
    )
    op.add_column(
        "terminology_terms", sa.Column("preferred_term", sa.String(length=1000), nullable=True)
    )
    op.add_column(
        "terminology_terms",
        sa.Column(
            "synonyms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "terminology_terms",
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
    )
    op.create_index(
        op.f("ix_terminology_terms_concept_id"),
        "terminology_terms",
        ["concept_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_terminology_terms_codelist_concept_id",
        "terminology_terms",
        ["codelist_id", "concept_id"],
    )
    op.create_unique_constraint(
        "uq_terminology_terms_codelist_submission_value",
        "terminology_terms",
        ["codelist_id", "submission_value"],
    )
    op.add_column(
        "terminology_extension_terms",
        sa.Column("definition", sa.String(length=4000), nullable=True),
    )
    op.add_column(
        "terminology_extension_terms",
        sa.Column("preferred_term", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "terminology_extension_terms",
        sa.Column(
            "synonyms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_table(
        "terminology_release_compatibilities",
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("standard_version_id", sa.Uuid(), nullable=False),
        sa.Column("terminology_scope", sa.String(length=64), nullable=False),
        sa.Column("standard_purpose", sa.String(length=64), nullable=False),
        sa.Column("relationship", sa.String(length=64), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["terminology_releases.id"],
            name=op.f("fk_terminology_release_compatibilities_release_id_terminology_releases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["standard_version_id"],
            ["standard_versions.id"],
            name=op.f(
                "fk_terminology_release_compatibilities_standard_version_id_standard_versions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminology_release_compatibilities")),
        sa.UniqueConstraint(
            "release_id",
            "standard_version_id",
            "terminology_scope",
            "standard_purpose",
            name="uq_terminology_release_compatibilities_release_id",
        ),
    )
    op.create_index(
        op.f("ix_terminology_release_compatibilities_release_id"),
        "terminology_release_compatibilities",
        ["release_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_terminology_release_compatibilities_standard_version_id"),
        "terminology_release_compatibilities",
        ["standard_version_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove CDISC-specific registry metadata."""

    op.drop_index(
        op.f("ix_terminology_release_compatibilities_standard_version_id"),
        table_name="terminology_release_compatibilities",
    )
    op.drop_index(
        op.f("ix_terminology_release_compatibilities_release_id"),
        table_name="terminology_release_compatibilities",
    )
    op.drop_table("terminology_release_compatibilities")
    op.drop_column("terminology_extension_terms", "synonyms")
    op.drop_column("terminology_extension_terms", "preferred_term")
    op.drop_column("terminology_extension_terms", "definition")
    op.drop_constraint(
        "uq_terminology_terms_codelist_submission_value",
        "terminology_terms",
        type_="unique",
    )
    op.drop_constraint(
        "uq_terminology_terms_codelist_concept_id", "terminology_terms", type_="unique"
    )
    op.drop_index(op.f("ix_terminology_terms_concept_id"), table_name="terminology_terms")
    op.drop_column("terminology_terms", "status")
    op.drop_column("terminology_terms", "synonyms")
    op.drop_column("terminology_terms", "preferred_term")
    op.drop_column("terminology_terms", "definition")
    op.drop_column("terminology_terms", "concept_id")
    op.drop_constraint(
        "uq_terminology_codelists_release_submission_value",
        "terminology_codelists",
        type_="unique",
    )
    op.drop_constraint(
        "uq_terminology_codelists_release_concept_id",
        "terminology_codelists",
        type_="unique",
    )
    op.drop_index(op.f("ix_terminology_codelists_concept_id"), table_name="terminology_codelists")
    op.drop_column("terminology_codelists", "extensible")
    op.drop_column("terminology_codelists", "synonyms")
    op.drop_column("terminology_codelists", "preferred_term")
    op.drop_column("terminology_codelists", "definition")
    op.drop_column("terminology_codelists", "submission_value")
    op.drop_column("terminology_codelists", "concept_id")
    op.drop_constraint(op.f("uq_terminology_releases_code"), "terminology_releases", type_="unique")
    op.drop_column("terminology_releases", "content_schema_version")
    op.drop_column("terminology_releases", "library_href")
    op.drop_column("terminology_releases", "publication_date")
    op.drop_column("terminology_releases", "product")
    op.drop_column("terminology_releases", "provider")

    op.drop_index(
        op.f("ix_standard_version_compatibilities_target_version_id"),
        table_name="standard_version_compatibilities",
    )
    op.drop_index(
        op.f("ix_standard_version_compatibilities_source_version_id"),
        table_name="standard_version_compatibilities",
    )
    op.drop_table("standard_version_compatibilities")
    op.drop_index(op.f("ix_standard_assets_version_id"), table_name="standard_assets")
    op.drop_table("standard_assets")
    op.drop_column("standard_versions", "content_schema_version")
    op.drop_column("standard_versions", "library_href")
    op.drop_column("standard_versions", "publication_date")
    op.drop_column("standard_products", "scope")
    op.drop_column("standard_products", "product_type")
    op.drop_column("standard_products", "family")
    op.drop_column("standard_products", "provider")
