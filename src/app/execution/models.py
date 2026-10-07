"""Immutable execution requests and controlled lifecycle results."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class ExecutionRun(UuidPrimaryKey, Base):
    """One exact program execution over immutable selected inputs."""

    __tablename__ = "execution_runs"

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    module_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    owner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    program_artifact_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    input_artifact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    validation_run_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    input_selection_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_specification_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_plan_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_plan_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    compiler_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    limits: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    manifest: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    output_artifact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    failure: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    stdout: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    exit_code: Mapped[int | None] = mapped_column(Integer)
    metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
