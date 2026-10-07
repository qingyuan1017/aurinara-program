"""SDTM aggregate, exact Raw input, Specification, and Derivation Plan persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
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


class SdtmDerivationPlanRevision(UuidPrimaryKey, Base):
    """One immutable SDTM plan revision pinned to Specification and Raw selection."""

    __tablename__ = "sdtm_derivation_plan_revisions"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "revision", name="uq_sdtm_plan_aggregate_revision"),
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
    input_selection_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
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
