"""Immutable presentation Template registry persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class TemplateFamily(UuidPrimaryKey, Base):
    """Stable template family identity."""

    __tablename__ = "template_families"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class TemplateVersion(UuidPrimaryKey, Base):
    """Immutable presentation-only template version."""

    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("family_id", "version"),)

    family_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("template_families.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_path: Mapped[str] = mapped_column(String(512), nullable=False)
    applicable_modules: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    artifact_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content_schema_versions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    renderer_versions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    blank_structure: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
