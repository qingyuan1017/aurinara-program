"""Study identity persistence models."""

from uuid import UUID

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import Revisioned, Timestamped, UuidPrimaryKey
from app.database import Base


class Study(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """Top-level study ownership boundary."""

    __tablename__ = "studies"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_managed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    platform_revision: Mapped[int | None] = mapped_column(BigInteger)
    platform_registry_status: Mapped[str | None] = mapped_column(String(16))


class StudyMembership(UuidPrimaryKey, Timestamped, Base):
    """Externally identified subject membership in one study."""

    __tablename__ = "study_memberships"
    __table_args__ = (
        UniqueConstraint("study_id", "subject", name="uq_study_memberships_study_subject"),
    )

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="owner")
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
