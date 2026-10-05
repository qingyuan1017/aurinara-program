"""Immutable pinned Standards registry persistence."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class StandardProduct(UuidPrimaryKey, Base):
    """Stable identity for one standard product family."""

    __tablename__ = "standard_products"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="AURINARA")
    family: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    product_type: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="cross_domain")


class StandardVersion(UuidPrimaryKey, Base):
    """Immutable exact version backed by repository-pinned assets."""

    __tablename__ = "standard_versions"
    __table_args__ = (UniqueConstraint("product_id", "version"),)

    product_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("standard_products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    library_href: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_path: Mapped[str] = mapped_column(String(512), nullable=False)
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    applicable_modules: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    purposes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    compatibility: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class StandardAsset(UuidPrimaryKey, Base):
    """One immutable file belonging to an exact standard version."""

    __tablename__ = "standard_assets"
    __table_args__ = (
        UniqueConstraint("version_id", "role", "asset_path"),
        UniqueConstraint(
            "version_id",
            "canonical_href",
            name="uq_standard_assets_version_canonical_href",
        ),
    )

    version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("standard_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_path: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    canonical_href: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")


class StandardVersionCompatibility(UuidPrimaryKey, Base):
    """Typed directional relationship between exact standard versions."""

    __tablename__ = "standard_version_compatibilities"
    __table_args__ = (UniqueConstraint("source_version_id", "target_version_id", "relationship"),)

    source_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("standard_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    target_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("standard_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    relationship: Mapped[str] = mapped_column(String(64), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
