"""Immutable source-file and generated-artifact persistence models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class Artifact(UuidPrimaryKey, Base):
    """Immutable artifact metadata and internal storage locator."""

    __tablename__ = "artifacts"

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    module_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    dependency_selection_revision: Mapped[int | None] = mapped_column(Integer)
    dependency_fingerprint: Mapped[str | None] = mapped_column(String(64))
    input_selection_revision: Mapped[int | None] = mapped_column(Integer)
    source_specification_revision: Mapped[int | None] = mapped_column(Integer)
    source_specification_fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_plan_type: Mapped[str | None] = mapped_column(String(64), index=True)
    source_plan_revision: Mapped[int | None] = mapped_column(Integer)
    compiler_fingerprint: Mapped[str | None] = mapped_column(String(64))
    manifest: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    generator_name: Mapped[str] = mapped_column(String(128), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    validation_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    reconciliation_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    execution_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SourceFile(UuidPrimaryKey, Base):
    """Immutable metadata for one uploaded source object."""

    __tablename__ = "source_files"

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ArtifactBuild(UuidPrimaryKey, Base):
    """Idempotent asynchronous request for immutable module-owned artifacts."""

    __tablename__ = "artifact_builds"

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    module_key: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    artifact_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    options: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    result_artifact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    failure: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
