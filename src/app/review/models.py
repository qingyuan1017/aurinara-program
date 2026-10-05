"""Human review workflow persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import Revisioned, Timestamped, UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class ReviewItem(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """Study-owned question against a verified typed entity."""

    __tablename__ = "review_items"

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    target_module: Mapped[str] = mapped_column(String(32), nullable=False)
    target_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(512))
    question: Mapped[str] = mapped_column(String(4000), nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    disposition: Mapped[str | None] = mapped_column(String(64))
    resolution: Mapped[str | None] = mapped_column(String(4000))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)


class ReviewComment(UuidPrimaryKey, Base):
    """Append-only review comment."""

    __tablename__ = "review_comments"

    review_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("review_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String(8000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
