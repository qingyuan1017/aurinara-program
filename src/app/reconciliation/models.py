"""Immutable reconciliation snapshot persistence models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class ReconciliationRun(UuidPrimaryKey, Base):
    """Comparison operation bound to exact input identities and checksums."""

    __tablename__ = "reconciliation_runs"

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reconciliation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reconciliation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    options: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    info_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issues: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    report_artifact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    failure: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
