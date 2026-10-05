"""Documents aggregate, immutable content, USDM, and evidence persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import Revisioned, Timestamped, UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class Document(UuidPrimaryKey, Revisioned, Timestamped, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("study_id", "code"),)
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content_schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    source_pdf_file_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("source_files.id", ondelete="RESTRICT"), nullable=True
    )
    related_document_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class DocumentDependencySelection(UuidPrimaryKey, Base):
    __tablename__ = "document_dependency_selections"
    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class DocumentContent(UuidPrimaryKey, Base):
    """Immutable revision of one type-specific manually authored content payload."""

    __tablename__ = "document_contents"
    __table_args__ = (UniqueConstraint("document_id", "revision"),)

    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ProtocolUsdmDocument(UuidPrimaryKey, Base):
    """Immutable validated USDM JSON revision for a Protocol document."""

    __tablename__ = "protocol_usdm_documents"
    __table_args__ = (UniqueConstraint("document_id", "revision"),)

    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    usdm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ProtocolEvidence(UuidPrimaryKey, Revisioned, Timestamped, Base):
    """Mutable evidence decision pointing into immutable Protocol source bytes and USDM IDs."""

    __tablename__ = "protocol_evidence"

    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_pdf_file_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("source_files.id", ondelete="RESTRICT"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    region: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    excerpt: Mapped[str | None] = mapped_column(String(4000))
    linked_usdm_entity_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    question: Mapped[str | None] = mapped_column(String(4000))
    resolution: Mapped[str | None] = mapped_column(String(4000))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
