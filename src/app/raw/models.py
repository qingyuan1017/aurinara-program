"""Raw aggregate identity and dependency-selection persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import Revisioned, Timestamped, UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class RawWorkbench(UuidPrimaryKey, Revisioned, Timestamped, Base):
    __tablename__ = "raw_workbenches"
    __table_args__ = (UniqueConstraint("study_id", "code"),)
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")


class RawDependencySelection(UuidPrimaryKey, Base):
    __tablename__ = "raw_dependency_selections"
    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("raw_workbenches.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class RawDataset(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """Manually maintained dataset identity bound to one immutable source file."""

    __tablename__ = "raw_datasets"
    __table_args__ = (UniqueConstraint("raw_id", "code", name="uq_raw_datasets_raw_code"),)

    raw_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("raw_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4000))
    current_source_file_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("source_files.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class RawDatasetFileBinding(UuidPrimaryKey, Base):
    """Immutable history of every source-file binding accepted for a Raw dataset."""

    __tablename__ = "raw_dataset_file_bindings"
    __table_args__ = (
        UniqueConstraint("dataset_id", "dataset_revision", name="uq_raw_dataset_binding_revision"),
    )

    dataset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("raw_datasets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    dataset_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("source_files.id", ondelete="RESTRICT"), nullable=False
    )
    source_artifact_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RawVariable(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """User-maintained Raw variable metadata; initialization fills missing facts only."""

    __tablename__ = "raw_variables"
    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="uq_raw_variables_dataset_name"),
        UniqueConstraint("dataset_id", "ordinal", name="uq_raw_variables_dataset_ordinal"),
    )

    dataset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("raw_datasets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))
    physical_type: Mapped[str | None] = mapped_column(String(32))
    length: Mapped[int | None] = mapped_column(Integer)
    precision: Mapped[int | None] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(4000))
    terminology_binding: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class RawDatasetImport(UuidPrimaryKey, Base):
    """Operation row for one asynchronous bulk dataset import.

    This is an operation row (like ``artifact_builds``), not an owned entity
    type; study ownership for its status endpoints is enforced directly.
    """

    __tablename__ = "raw_dataset_imports"

    raw_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("raw_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    entries: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    files_inspected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_dataset_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    issues: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    failure: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
