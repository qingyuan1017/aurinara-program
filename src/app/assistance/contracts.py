"""Transport and worker contracts for AI-authored, human-reviewed proposals."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProposalStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    REVIEW_REQUIRED = "review_required"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class ProposalCreate(BaseModel):
    """Request an AI proposal against the aggregate's exact current context."""

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    proposal_type: str = Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")
    target: dict[str, str] = Field(default_factory=dict)
    guidance: str | None = Field(default=None, max_length=4_000)


class ProposalDecisionCreate(BaseModel):
    """Human review evidence for one immutable proposal."""

    model_config = ConfigDict(extra="forbid")

    rationale: str = Field(min_length=1, max_length=4_000)


class ProposalResponse(BaseModel):
    """Safe reviewer-facing projection of an AI proposal and its provenance."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    generation_run_id: UUID
    supersedes_proposal_id: UUID | None
    study_id: UUID
    module_key: str
    aggregate_type: str
    aggregate_id: UUID
    proposal_type: str
    proposal_schema_version: str
    target: dict[str, str]
    status: ProposalStatus
    base_revision: int
    context_fingerprint: str
    response_checksum: str | None
    instruction_version: str
    provider: str | None
    model: str | None
    generation_parameters: dict[str, Any]
    usage: dict[str, Any]
    payload: dict[str, Any] | None
    diff: tuple[dict[str, Any], ...]
    assumptions: tuple[str, ...]
    unresolved_items: tuple[str, ...]
    evidence_references: tuple[str, ...]
    model_limitations: tuple[str, ...]
    validation_issues: tuple[dict[str, Any], ...]
    failure: dict[str, Any] | None
    created_by: str
    created_at: datetime
    completed_at: datetime | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_rationale: str | None
    resulting_revision_ids: tuple[str, ...]


class ProposalPage(BaseModel):
    items: tuple[ProposalResponse, ...]


class ProposalGenerationRequest(BaseModel):
    """Module-owned prompt package passed to a configured provider adapter."""

    model_config = ConfigDict(extra="forbid")

    system_instruction: str
    user_instruction: str
    output_schema: dict[str, Any]


class ProviderResult(BaseModel):
    """Normalized provider result; raw transport data never escapes this boundary."""

    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any]
    response_checksum: str
    usage: dict[str, Any] = Field(default_factory=dict)
