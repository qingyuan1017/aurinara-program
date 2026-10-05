"""Study-scoped external integration persistence models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import Revisioned, Timestamped, UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class Integration(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """External-system registration inside one study."""

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("study_id", "integration_code"),)

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    integration_code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    external_subject: Mapped[str | None] = mapped_column(String(255))
    allowed_modules: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class IntegrationSecretVersion(UuidPrimaryKey, Base):
    """Encrypted, versioned delivery secret; plaintext is never readable by API."""

    __tablename__ = "integration_secret_versions"
    __table_args__ = (UniqueConstraint("integration_id", "version"),)

    integration_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integrations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    encrypted_secret: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class IntegrationSubscription(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """Versioned callback selection and bounded delivery policy."""

    __tablename__ = "integration_subscriptions"

    integration_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integrations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    callback_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    event_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    headers: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class ExternalIdentifier(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """Verified mapping from an external tuple to a typed platform entity."""

    __tablename__ = "external_identifiers"
    __table_args__ = (UniqueConstraint("integration_id", "external_entity_type", "external_id"),)

    integration_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integrations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    external_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_module: Mapped[str] = mapped_column(String(32), nullable=False)
    target_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class IntegrationDeliveryAttempt(UuidPrimaryKey, Base):
    """Append-only attempt evidence for one event/subscription revision."""

    __tablename__ = "integration_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("event_id", "subscription_id", "subscription_revision", "attempt_number"),
    )

    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("outbox_events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subscription_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integration_subscriptions.id", ondelete="RESTRICT"), nullable=False
    )
    subscription_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    destination_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_excerpt: Mapped[str | None] = mapped_column(String(65536))
    failure: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
