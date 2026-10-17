"""SDTM aggregate, exact Raw input, Specification, and Derivation Plan persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import Revisioned, Timestamped, UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class SdtmWorkbench(UuidPrimaryKey, Revisioned, Timestamped, Base):
    __tablename__ = "sdtm_workbenches"
    __table_args__ = (UniqueConstraint("study_id", "code"),)
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")


class SdtmDependencySelection(UuidPrimaryKey, Base):
    __tablename__ = "sdtm_dependency_selections"
    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class SdtmInputSelection(UuidPrimaryKey, Base):
    """Exact immutable Raw context selected by one SDTM aggregate."""

    __tablename__ = "sdtm_input_selections"

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="unselected")
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class SdtmSpecificationRevision(UuidPrimaryKey, Base):
    """One immutable atomic SDTM Specification revision."""

    __tablename__ = "sdtm_specification_revisions"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_id", "revision", name="uq_sdtm_specification_aggregate_revision"
        ),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SdtmDomainMappingRevision(UuidPrimaryKey, Base):
    """Immutable declared input lineage for one generated SDTM domain."""

    __tablename__ = "sdtm_domain_mapping_revisions"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_id", "domain_code", "revision", name="uq_sdtm_domain_mapping_revision"
        ),
        Index("ix_sdtm_domain_mapping_head", "aggregate_id", "domain_code"),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    domain_code: Mapped[str] = mapped_column(String(8), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    specification_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    input_selection_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="aligned")
    alignment_reasons: Mapped[list[str] | None] = mapped_column(JSONB)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SdtmVariableMappingRevision(UuidPrimaryKey, Base):
    """Immutable sparse target/context to qualified-source mapping."""

    __tablename__ = "sdtm_variable_mapping_revisions"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_id", "domain_code", "revision", name="uq_sdtm_variable_mapping_revision"
        ),
        Index("ix_sdtm_variable_mapping_head", "aggregate_id", "domain_code"),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    domain_code: Mapped[str] = mapped_column(String(8), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    specification_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    domain_mapping_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="aligned")
    alignment_reasons: Mapped[list[str] | None] = mapped_column(JSONB)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SdtmCodeWorkarea(UuidPrimaryKey, Timestamped, Base):
    """Named code identity; domain and language never change after creation."""

    __tablename__ = "sdtm_code_workareas"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "name", name="uq_sdtm_code_workarea_name"),
        Index("ix_sdtm_code_workarea_domain", "aggregate_id", "domain_code"),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    domain_code: Mapped[str] = mapped_column(String(8), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)


class SdtmCodeRevision(UuidPrimaryKey, Base):
    """Immutable authored program source with exact mapping pins."""

    __tablename__ = "sdtm_code_revisions"
    __table_args__ = (UniqueConstraint("workarea_id", "revision", name="uq_sdtm_code_revision"),)

    workarea_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_code_workareas.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    specification_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    domain_mapping_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    variable_mapping_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SdtmOutputSelection(UuidPrimaryKey, Base):
    """Current revisioned exact all-domain output set."""

    __tablename__ = "sdtm_output_selections"

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    specification_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="current")
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class SdtmImportedDomainRevision(UuidPrimaryKey, Base):
    """Immutable externally produced SDTM domain accepted against one Specification."""

    __tablename__ = "sdtm_imported_domain_revisions"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_id",
            "domain_code",
            "revision",
            name="uq_sdtm_imported_domain_aggregate_domain_revision",
        ),
        Index(
            "ix_sdtm_imported_domain_aggregate_domain",
            "aggregate_id",
            "domain_code",
        ),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    domain_code: Mapped[str] = mapped_column(String(8), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    specification_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("source_files.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    validation_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("validation_runs.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="aligned")
    alignment_reasons: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    extracted_schema: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    issues: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SdtmDomainSourceSelection(UuidPrimaryKey, Base):
    """Current explicit provider for one SDTM domain."""

    __tablename__ = "sdtm_domain_source_selections"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_id", "domain_code", name="uq_sdtm_domain_source_aggregate_domain"
        ),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    domain_code: Mapped[str] = mapped_column(String(8), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class SdtmAcrfAnnotation(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """User-authored region on one immutable CRF PDF with exact typed targets."""

    __tablename__ = "sdtm_acrf_annotations"

    sdtm_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_pdf_artifact_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    region: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    annotation_text: Mapped[str | None] = mapped_column(String(4000))
    links: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    question: Mapped[str | None] = mapped_column(String(4000))
    resolution: Mapped[str | None] = mapped_column(String(4000))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)


class SdtmDefineRevision(UuidPrimaryKey, Base):
    """Immutable revision of the version-neutral SDTM Define metadata model."""

    __tablename__ = "sdtm_define_revisions"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "revision", name="uq_sdtm_define_aggregate_revision"),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    specification_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    output_artifact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SdtmCsdrgRevision(UuidPrimaryKey, Base):
    """Immutable cSDRG revision bound to exact Define and reconciliation evidence."""

    __tablename__ = "sdtm_csdrg_revisions"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "revision", name="uq_sdtm_csdrg_aggregate_revision"),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sdtm_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    specification_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    define_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    reconciliation_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
