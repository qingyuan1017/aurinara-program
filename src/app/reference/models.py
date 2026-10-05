"""Revisioned study Reference persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import Revisioned, Timestamped, UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class ReferenceRecord(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """Stable logical identity for one manually maintained study fact."""

    __tablename__ = "reference_records"
    __table_args__ = (UniqueConstraint("study_id", "reference_type", "natural_key"),)

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reference_type: Mapped[str] = mapped_column(String(32), nullable=False)
    natural_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class ReferenceRevision(UuidPrimaryKey, Base):
    """Immutable Reference value snapshot."""

    __tablename__ = "reference_record_revisions"
    __table_args__ = (UniqueConstraint("reference_id", "revision"),)

    reference_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("reference_records.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ReferenceImportBatch(UuidPrimaryKey, Base):
    """Idempotent evidence for one fully validated atomic Reference import."""

    __tablename__ = "reference_import_batches"

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
