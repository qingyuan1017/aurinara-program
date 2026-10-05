"""Immutable validation run persistence models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import Revisioned, Timestamped, UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class ValidationRun(UuidPrimaryKey, Base):
    """Immutable validation input snapshot with lifecycle state."""

    __tablename__ = "validation_runs"

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    module_key: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    validator_name: Mapped[str] = mapped_column(String(128), nullable=False)
    validator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_manifest: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
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


class ValidationRule(UuidPrimaryKey, Base):
    """Immutable declarative rule definition; never executable user code."""

    __tablename__ = "validation_rules"

    rule_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    module_key: Mapped[str] = mapped_column(String(32), nullable=False)
    applicability: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    parameter_schema: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    default_severity: Mapped[str] = mapped_column(String(16), nullable=False)
    mandatory: Mapped[bool] = mapped_column(nullable=False, default=False)


class ValidationRulePack(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """Study-authored exact selection of registered rule versions."""

    __tablename__ = "validation_rule_packs"
    __table_args__ = (UniqueConstraint("study_id", "code"),)

    study_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    selections: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
