"""TLF aggregate, dependency, and immutable authoring persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import Revisioned, Timestamped, UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class TlfWorkbench(UuidPrimaryKey, Revisioned, Timestamped, Base):
    __tablename__ = "tlf_workbenches"
    __table_args__ = (UniqueConstraint("study_id", "code"),)
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")


class TlfDependencySelection(UuidPrimaryKey, Base):
    __tablename__ = "tlf_dependency_selections"
    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tlf_workbenches.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class TlfAuthoringRevision(UuidPrimaryKey, Base):
    """One immutable revision of a TLF-owned authoring contract."""

    __tablename__ = "tlf_authoring_revisions"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_id", "content_type", "revision", name="uq_tlf_content_revision"
        ),
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tlf_workbenches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="current")
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
