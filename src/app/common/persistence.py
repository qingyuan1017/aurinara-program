"""Technical persistence mixins shared by application tables."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.time import utc_now


class UuidPrimaryKey:
    """Provide a generated UUID primary key without domain semantics."""

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class Timestamped:
    """Provide UTC creation and update timestamps."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Revisioned:
    """Provide an integer revision for optimistic concurrency."""

    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
