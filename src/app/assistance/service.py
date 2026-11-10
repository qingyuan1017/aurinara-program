"""Application service for durable AI proposals and human review decisions."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistance.contracts import (
    ProposalCreate,
    ProposalGenerationRequest,
    ProposalResponse,
    ProposalStatus,
    ProviderResult,
)
from app.assistance.models import AiGenerationRun, AuthoringProposal, ProposalReviewDecision
from app.assistance.platform_agents import (
    PlatformAgentClient,
    PlatformAgentClientError,
    as_problem,
)
from app.common.canonical import canonical_json, fingerprint
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.config import Settings
from app.execution.jobs import Job, JobService
from app.kernel.registry import ModuleRegistry


@dataclass(frozen=True, slots=True)
class PreparedProposal:
    """Module-owned exact generation context and versioned prompt contract."""

    study_id: UUID
    aggregate_type: str
    base_revision: int
    schema_version: str
    instruction_version: str
    context: dict[str, object]


class ProposalValidation(BaseModel):
    """Normalized result after strict module validation."""

    payload: dict[str, Any]
    diff: tuple[dict[str, Any], ...] = ()
    assumptions: tuple[str, ...] = ()
    unresolved_items: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = ()
    model_limitations: tuple[str, ...] = ()
    validation_issues: tuple[dict[str, Any], ...] = ()


class ProposalCapability(Protocol):
    """Typed module boundary used by the shared lifecycle service."""

    def prepare_proposal(
        self,
        session: Session,
        registry: ModuleRegistry,
        aggregate_id: UUID,
        command: ProposalCreate,
    ) -> PreparedProposal: ...

    def validate_proposal(
        self, session: Session, run: AiGenerationRun, payload: dict[str, Any]
    ) -> ProposalValidation: ...

    def generation_request(self, run: AiGenerationRun) -> ProposalGenerationRequest: ...

    def apply_proposal(
        self,
        session: Session,
        registry: ModuleRegistry,
        proposal: AuthoringProposal,
        reviewer: str,
        decision_id: UUID,
    ) -> tuple[str, ...]: ...


class AssistanceService:
    """Keep provider mechanics generic while module owners retain clinical semantics."""

    def create(
        self,
        session: Session,
        *,
        module_key: str,
        aggregate_id: UUID,
        command: ProposalCreate,
        created_by: str,
        handler: ProposalCapability,
        settings: Settings,
        registry: ModuleRegistry,
        agent_client: PlatformAgentClient,
        supersedes_proposal_id: UUID | None = None,
        expected_agent_revision: int | None = None,
    ) -> AuthoringProposal:
        if (
            not settings.assistance_enabled
            or settings.assistance_provider != "platform_agent"
        ):
            raise ProblemException(
                status_code=503,
                code="assistance_not_configured",
                title="AI proposal generation is not configured",
                detail=(
                    "Enable assistance and configure the Platform agent service "
                    "before requesting an AI proposal."
                ),
            )
        try:
            agent = agent_client.get_agent(command.agent_id)
        except PlatformAgentClientError as error:
            raise as_problem(error) from error
        if expected_agent_revision is not None and agent.revision != expected_agent_revision:
            raise ProblemException(
                status_code=409,
                code="platform_agent_revision_stale",
                title="Selected agent changed",
                detail="The selected Platform agent revision has changed.",
            )
        prepared = handler.prepare_proposal(session, registry, aggregate_id, command)
        if len(canonical_json(prepared.context)) > settings.assistance_max_context_bytes:
            raise ProblemException(
                status_code=422,
                code="proposal_context_too_large",
                title="Proposal context is too large",
                detail="Narrow the proposal target or reduce the selected evidence.",
            )
        context_fingerprint = fingerprint(prepared.context)
        run = AiGenerationRun(
            study_id=prepared.study_id,
            module_key=module_key,
            aggregate_type=prepared.aggregate_type,
            aggregate_id=aggregate_id,
            proposal_type=command.proposal_type,
            proposal_schema_version=prepared.schema_version,
            status=ProposalStatus.QUEUED,
            base_revision=prepared.base_revision,
            context=prepared.context,
            context_fingerprint=context_fingerprint,
            instruction_version=prepared.instruction_version,
            target=command.target,
            guidance=command.guidance,
            provider="aurinara_platform",
            model=f"agent:{agent.id}:revision:{agent.revision}",
            generation_parameters={
                "temperature": settings.assistance_temperature,
                "max_output_tokens": settings.assistance_max_output_tokens,
                "platform_agent_contract_version": "1.0.0",
                "platform_agent_id": str(agent.id),
                "platform_agent_revision": agent.revision,
                "platform_agent_name": agent.name,
            },
            created_by=created_by,
        )
        session.add(run)
        session.flush()
        proposal = AuthoringProposal(
            generation_run_id=run.id,
            supersedes_proposal_id=supersedes_proposal_id,
            study_id=run.study_id,
            module_key=module_key,
            aggregate_type=run.aggregate_type,
            aggregate_id=aggregate_id,
            proposal_type=run.proposal_type,
            proposal_schema_version=run.proposal_schema_version,
            status=ProposalStatus.QUEUED,
            base_revision=run.base_revision,
            context_fingerprint=context_fingerprint,
            instruction_version=run.instruction_version,
            provider=run.provider,
            model=run.model,
            created_by=created_by,
        )
        session.add(proposal)
        session.add(
            Job(
                operation_id=run.id,
                job_type="ai_proposal",
                status="queued",
                payload={"generation_run_id": str(run.id)},
                max_attempts=settings.job_max_attempts,
            )
        )
        session.flush()
        return proposal

    def begin_generation(
        self,
        session: Session,
        *,
        run: AiGenerationRun,
        proposal: AuthoringProposal,
        handler: ProposalCapability,
        registry: ModuleRegistry,
    ) -> ProposalGenerationRequest | None:
        """Mark a run active and resolve its exact request in a short transaction."""

        if proposal.status == ProposalStatus.REVIEW_REQUIRED:
            return None
        run.status = ProposalStatus.RUNNING
        proposal.status = ProposalStatus.RUNNING
        run.started_at = run.started_at or utc_now()
        command = ProposalCreate(
            agent_id=UUID(str(run.generation_parameters["platform_agent_id"])),
            proposal_type=run.proposal_type,
            target=run.target,
            guidance=run.guidance,
        )

        def prepare_current() -> PreparedProposal:
            return handler.prepare_proposal(
                session,
                registry,
                run.aggregate_id,
                command,
            )

        def context_matches(prepared: PreparedProposal) -> bool:
            return (
                prepared.base_revision == run.base_revision
                and fingerprint(prepared.context) == run.context_fingerprint
            )

        prepared = prepare_current()
        if not context_matches(prepared):
            # Live provider-backed context may suffer a transient inconsistent
            # read. One immediate, bounded reconstruction prevents a false
            # stale failure while still requiring an exact fingerprint match.
            prepared = prepare_current()
        if not context_matches(prepared):
            self.fail(run, proposal, "proposal_context_stale", "The bound context changed.")
            return None
        return handler.generation_request(run)

    def complete_generation(
        self,
        session: Session,
        *,
        run: AiGenerationRun,
        proposal: AuthoringProposal,
        result: ProviderResult,
        handler: ProposalCapability,
    ) -> None:
        """Validate and publish provider output in a new short transaction."""

        try:
            validated = handler.validate_proposal(session, run, result.payload)
        except ValueError as error:
            self.fail(run, proposal, "proposal_validation_failed", str(error))
            return
        completed_at = utc_now()
        run.status = ProposalStatus.REVIEW_REQUIRED
        run.response_checksum = result.response_checksum
        run.usage = result.usage
        run.completed_at = completed_at
        proposal.status = ProposalStatus.REVIEW_REQUIRED
        proposal.payload = validated.payload
        proposal.diff = list(validated.diff)
        proposal.assumptions = list(validated.assumptions)
        proposal.unresolved_items = list(validated.unresolved_items)
        proposal.evidence_references = list(validated.evidence_references)
        proposal.model_limitations = list(validated.model_limitations)
        proposal.validation_issues = list(validated.validation_issues)
        proposal.completed_at = completed_at

    @staticmethod
    def fail(run: AiGenerationRun, proposal: AuthoringProposal, code: str, detail: str) -> None:
        failure: dict[str, object] = {"code": code, "detail": detail}
        completed_at = utc_now()
        run.status = ProposalStatus.FAILED
        run.failure = failure
        run.completed_at = completed_at
        proposal.status = ProposalStatus.FAILED
        proposal.failure = failure
        proposal.completed_at = completed_at

    def decide(
        self,
        session: Session,
        *,
        proposal: AuthoringProposal,
        decision: str,
        reviewer: str,
        rationale: str,
        handler: ProposalCapability,
        registry: ModuleRegistry,
    ) -> AuthoringProposal:
        if proposal.status != ProposalStatus.REVIEW_REQUIRED:
            raise ProblemException(
                status_code=409,
                code="proposal_not_reviewable",
                title="Proposal is not reviewable",
                detail="Only a validated proposal awaiting review can receive a decision.",
            )
        decision_record = ProposalReviewDecision(
            proposal_id=proposal.id,
            study_id=proposal.study_id,
            decision=decision,
            reviewer=reviewer,
            rationale=rationale,
            resulting_revision_ids=[],
        )
        session.add(decision_record)
        session.flush()
        resulting: tuple[str, ...] = ()
        if decision == "accepted":
            resulting = handler.apply_proposal(
                session, registry, proposal, reviewer, decision_record.id
            )
        proposal.status = decision
        decision_record.resulting_revision_ids = list(resulting)
        return proposal

    @staticmethod
    def get(
        session: Session, proposal_id: UUID, *, module_key: str, aggregate_id: UUID
    ) -> AuthoringProposal:
        proposal = session.get(AuthoringProposal, proposal_id)
        if (
            proposal is None
            or proposal.module_key != module_key
            or proposal.aggregate_id != aggregate_id
        ):
            raise ProblemException(
                status_code=404,
                code="proposal_not_found",
                title="Proposal not found",
                detail="The requested proposal does not exist for this aggregate.",
            )
        return proposal

    @staticmethod
    def list(
        session: Session, *, module_key: str, aggregate_id: UUID
    ) -> tuple[AuthoringProposal, ...]:
        return tuple(
            session.scalars(
                select(AuthoringProposal)
                .where(
                    AuthoringProposal.module_key == module_key,
                    AuthoringProposal.aggregate_id == aggregate_id,
                )
                .order_by(AuthoringProposal.created_at.desc(), AuthoringProposal.id.desc())
            )
        )

    @staticmethod
    def response(session: Session, proposal: AuthoringProposal) -> ProposalResponse:
        run = session.get(AiGenerationRun, proposal.generation_run_id)
        if run is None:
            raise RuntimeError("proposal generation run is missing")
        decision = session.scalar(
            select(ProposalReviewDecision).where(ProposalReviewDecision.proposal_id == proposal.id)
        )
        return ProposalResponse(
            id=proposal.id,
            generation_run_id=proposal.generation_run_id,
            supersedes_proposal_id=proposal.supersedes_proposal_id,
            study_id=proposal.study_id,
            module_key=proposal.module_key,
            aggregate_type=proposal.aggregate_type,
            aggregate_id=proposal.aggregate_id,
            proposal_type=proposal.proposal_type,
            proposal_schema_version=proposal.proposal_schema_version,
            target=run.target,
            status=ProposalStatus(proposal.status),
            base_revision=proposal.base_revision,
            context_fingerprint=proposal.context_fingerprint,
            response_checksum=run.response_checksum,
            instruction_version=proposal.instruction_version,
            provider=proposal.provider,
            model=proposal.model,
            generation_parameters=run.generation_parameters,
            usage=run.usage,
            payload=proposal.payload,
            diff=tuple(proposal.diff),
            assumptions=tuple(proposal.assumptions),
            unresolved_items=tuple(proposal.unresolved_items),
            evidence_references=tuple(proposal.evidence_references),
            model_limitations=tuple(proposal.model_limitations),
            validation_issues=tuple(proposal.validation_issues),
            failure=proposal.failure,
            created_by=proposal.created_by,
            created_at=proposal.created_at,
            completed_at=proposal.completed_at,
            reviewed_by=decision.reviewer if decision else None,
            reviewed_at=decision.created_at if decision else None,
            review_rationale=decision.rationale if decision else None,
            resulting_revision_ids=tuple(decision.resulting_revision_ids) if decision else (),
        )


def complete_job(job: Job) -> None:
    """Complete through the queue service so lease fencing remains authoritative."""

    JobService().complete(job)
