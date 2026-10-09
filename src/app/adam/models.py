"""ADaM aggregate, exact SDTM input, Specification, and plan persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import Revisioned, Timestamped, UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class AdamWorkbench(UuidPrimaryKey, Revisioned, Timestamped, Base):
    __tablename__ = "adam_workbenches"
    __table_args__ = (UniqueConstraint("study_id", "code"),)
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")


class AdamDependencySelection(UuidPrimaryKey, Base):
    __tablename__ = "adam_dependency_selections"
    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("adam_workbenches.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class AdamInputSelection(UuidPrimaryKey, Base):
    """Exact immutable SDTM context selected by one ADaM aggregate."""

    __tablename__ = "adam_input_selections"

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("adam_workbenches.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="unselected")
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class AdamSpecificationRevision(UuidPrimaryKey, Base):
    """One immutable atomic ADaM Specification revision."""

    __tablename__ = "adam_specification_revisions"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_id", "revision", name="uq_adam_specification_aggregate_revision"
        ),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("adam_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
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


class AdamDerivationPlanRevision(UuidPrimaryKey, Base):
    """One immutable per-dataset ADaM plan pinned to Specification and SDTM input."""

    __tablename__ = "adam_derivation_plan_revisions"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_id",
            "dataset_code",
            "revision",
            name="uq_adam_plan_aggregate_dataset_revision",
        ),
        Index("ix_adam_plan_aggregate_dataset", "aggregate_id", "dataset_code"),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("adam_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    dataset_code: Mapped[str] = mapped_column(String(8), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    specification_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    input_selection_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    upstream_plan_pins: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    alignment_reasons: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AdamDefineRevision(UuidPrimaryKey, Base):
    """Immutable version-neutral ADaM Define metadata revision."""

    __tablename__ = "adam_define_revisions"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "revision", name="uq_adam_define_aggregate_revision"),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("adam_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    specification_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    input_selection_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    output_artifact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AdamAdrgRevision(UuidPrimaryKey, Base):
    """Immutable ADRG revision bound to exact Define and reconciliation evidence."""

    __tablename__ = "adam_adrg_revisions"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "revision", name="uq_adam_adrg_aggregate_revision"),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("adam_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
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
