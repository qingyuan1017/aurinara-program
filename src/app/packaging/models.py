"""Immutable submission-package operation records."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class SubmissionPackage(UuidPrimaryKey, Base):
    """One exact package request and its immutable terminal evidence."""

    __tablename__ = "submission_packages"

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    module_selections: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    artifact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    reconciliation_run_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    issues: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    manifest: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    zip_artifact_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="RESTRICT")
    )
    report_artifact_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="RESTRICT")
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
