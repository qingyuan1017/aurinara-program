"""Published terminology and sponsor-extension persistence."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import Revisioned, Timestamped, UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class TerminologyRelease(UuidPrimaryKey, Base):
    """Immutable exact controlled-terminology release."""

    __tablename__ = "terminology_releases"
    __table_args__ = (UniqueConstraint("code", "version"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="AURINARA")
    product: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    library_href: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_path: Mapped[str] = mapped_column(String(512), nullable=False)
    applicable_modules: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class TerminologyCodelist(UuidPrimaryKey, Base):
    """Codelist identity inside one immutable release."""

    __tablename__ = "terminology_codelists"
    __table_args__ = (
        UniqueConstraint("release_id", "code"),
        UniqueConstraint(
            "release_id",
            "concept_id",
            name="uq_terminology_codelists_release_concept_id",
        ),
        UniqueConstraint(
            "release_id",
            "submission_value",
            name="uq_terminology_codelists_release_submission_value",
        ),
    )

    release_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("terminology_releases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    concept_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    submission_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    definition: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    preferred_term: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    synonyms: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    extensible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TerminologyTerm(UuidPrimaryKey, Base):
    """Immutable published term."""

    __tablename__ = "terminology_terms"
    __table_args__ = (
        UniqueConstraint("codelist_id", "code"),
        UniqueConstraint(
            "codelist_id",
            "concept_id",
            name="uq_terminology_terms_codelist_concept_id",
        ),
        UniqueConstraint(
            "codelist_id",
            "submission_value",
            name="uq_terminology_terms_codelist_submission_value",
        ),
    )

    codelist_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("terminology_codelists.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    concept_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    submission_value: Mapped[str] = mapped_column(String(255), nullable=False)
    decode: Mapped[str] = mapped_column(String(1000), nullable=False)
    definition: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    preferred_term: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    synonyms: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class TerminologyReleaseCompatibility(UuidPrimaryKey, Base):
    """Compatibility evidence between an exact CT release and standard version."""

    __tablename__ = "terminology_release_compatibilities"
    __table_args__ = (
        UniqueConstraint(
            "release_id", "standard_version_id", "terminology_scope", "standard_purpose"
        ),
    )

    release_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("terminology_releases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    standard_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("standard_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    terminology_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    standard_purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    relationship: Mapped[str] = mapped_column(String(64), nullable=False, default="supports")
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class TerminologyAsset(UuidPrimaryKey, Base):
    """One immutable raw Library resource belonging to an exact CT release."""

    __tablename__ = "terminology_assets"
    __table_args__ = (UniqueConstraint("release_id", "canonical_href"),)

    release_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("terminology_releases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_path: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_href: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")


class TerminologyExtension(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """Study-owned logical sponsor extension."""

    __tablename__ = "terminology_extensions"
    __table_args__ = (UniqueConstraint("study_id", "code"),)

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_release_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("terminology_releases.id", ondelete="RESTRICT"), nullable=False
    )
    codelist_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class TerminologyExtensionRevision(UuidPrimaryKey, Base):
    """Immutable snapshot created for every accepted extension edit."""

    __tablename__ = "terminology_extension_revisions"
    __table_args__ = (UniqueConstraint("extension_id", "revision"),)

    extension_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("terminology_extensions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class TerminologyExtensionTerm(UuidPrimaryKey, Timestamped, Base):
    """Current manually maintained term; immutable revisions retain prior states."""

    __tablename__ = "terminology_extension_terms"
    __table_args__ = (
        UniqueConstraint(
            "extension_id", "code", name="uq_terminology_extension_terms_extension_code"
        ),
        UniqueConstraint(
            "extension_id",
            "submission_value",
            name="uq_terminology_extension_terms_extension_submission_value",
        ),
    )

    extension_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("terminology_extensions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    submission_value: Mapped[str] = mapped_column(String(255), nullable=False)
    decode: Mapped[str] = mapped_column(String(1000), nullable=False)
    definition: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    preferred_term: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    synonyms: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
