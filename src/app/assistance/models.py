"""Immutable AI generation, proposal, and human-review persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.persistence import UuidPrimaryKey
from app.common.time import utc_now
from app.database import Base


class AiGenerationRun(UuidPrimaryKey, Base):
    """Exact immutable context and provider envelope for one generation attempt."""

    __tablename__ = "ai_generation_runs"
    __table_args__ = (
        Index("ix_ai_generation_runs_owner", "module_key", "aggregate_id", "created_at"),
    )

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    module_key: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    proposal_type: Mapped[str] = mapped_column(String(96), nullable=False)
    proposal_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    base_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    context: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    instruction_version: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    guidance: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(255))
    generation_parameters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    response_checksum: Mapped[str | None] = mapped_column(String(64))
    usage: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    failure: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthoringProposal(UuidPrimaryKey, Base):
    """Validated module-owned proposal that cannot activate itself."""

    __tablename__ = "authoring_proposals"
    __table_args__ = (
        UniqueConstraint("generation_run_id", name="uq_authoring_proposals_generation_run"),
        Index("ix_authoring_proposals_owner", "module_key", "aggregate_id", "created_at"),
    )

    generation_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("ai_generation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    supersedes_proposal_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("authoring_proposals.id", ondelete="RESTRICT"), index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    module_key: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    proposal_type: Mapped[str] = mapped_column(String(96), nullable=False)
    proposal_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    base_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    instruction_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    diff: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    assumptions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    unresolved_items: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_references: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model_limitations: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    validation_issues: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    failure: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProposalReviewDecision(UuidPrimaryKey, Base):
    """Append-only human decision evidence for a proposal."""

    __tablename__ = "proposal_review_decisions"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_proposal_review_decisions_proposal"),
    )

    proposal_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("authoring_proposals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(255), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    resulting_revision_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
