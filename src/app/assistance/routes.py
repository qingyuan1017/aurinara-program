"""Reusable aggregate-scoped AI proposal HTTP routes."""

from collections.abc import Callable
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal, require_human_principal
from app.api.dependencies import (
    get_application_settings,
    get_module_registry,
    get_platform_agent_client,
    get_session,
)
from app.assistance.contracts import (
    ProposalCreate,
    ProposalDecisionCreate,
    ProposalPage,
    ProposalResponse,
)
from app.assistance.models import AiGenerationRun, AuthoringProposal
from app.assistance.platform_agents import PlatformAgentClient
from app.assistance.service import AssistanceService, ProposalCapability
from app.common.canonical import fingerprint
from app.common.etag import require_matching_etag
from app.common.idempotency import IdempotencyRecord
from app.common.problems import ProblemException
from app.config import Settings
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry
from app.studies.service import StudyService

service = AssistanceService()
studies = StudyService()


def proposal_router(
    *,
    module_key: str,
    collection: str,
    aggregate_model: type[Any],
    not_found_code: str,
    not_found_title: str,
) -> APIRouter:
    """Build the common proposal surface while dispatching semantics through the registry."""

    router = APIRouter(tags=[module_key, "ai-proposals"])
    base = f"/{collection}/{{aggregate_id}}"

    def aggregate(session: Session, aggregate_id: UUID, principal: Principal) -> Any:
        item = session.get(aggregate_model, aggregate_id)
        if item is None:
            raise ProblemException(
                status_code=404,
                code=not_found_code,
                title=not_found_title,
                detail=f"The {module_key.upper()} workbench does not exist.",
            )
        studies.require_access(session, item.study_id, principal)
        return item

    def handler(registry: ModuleRegistry) -> ProposalCapability:
        return cast(
            ProposalCapability,
            registry.require_handler(module_key, ModuleCapability.PROPOSALS),
        )

    def require_key(value: str | None) -> str:
        if not value:
            raise ProblemException(
                status_code=422,
                code="idempotency_key_required",
                title="Idempotency-Key is required",
                detail="Supply an Idempotency-Key header for this proposal operation.",
            )
        return value

    def existing(
        session: Session,
        *,
        principal: Principal,
        route: str,
        study_id: UUID,
        key: str,
        request_fingerprint: str,
    ) -> AuthoringProposal | None:
        record = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.subject == principal.subject,
                IdempotencyRecord.route == route,
                IdempotencyRecord.study_id == study_id,
                IdempotencyRecord.key == key,
            )
        )
        if record is None:
            return None
        if record.request_fingerprint != request_fingerprint:
            raise ProblemException(
                status_code=409,
                code="idempotency_key_reused",
                title="Idempotency key was reused",
                detail="The same key was already bound to a different proposal command.",
            )
        proposal = session.get(AuthoringProposal, record.resource_id)
        if proposal is None:
            raise RuntimeError("idempotency record references a missing proposal")
        return proposal

    @router.post(
        f"{base}/proposals",
        response_model=ProposalResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name=f"create_{module_key}_proposal",
    )
    def create_proposal(
        aggregate_id: UUID,
        command: ProposalCreate,
        session: Annotated[Session, Depends(get_session)],
        registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
        settings: Annotated[Settings, Depends(get_application_settings)],
        agent_client: Annotated[PlatformAgentClient, Depends(get_platform_agent_client)],
        principal: Annotated[Principal, Depends(get_principal)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ProposalResponse:
        item = aggregate(session, aggregate_id, principal)
        key = require_key(idempotency_key)
        request_fingerprint = fingerprint(command.model_dump(mode="json"))
        route = f"{module_key}-proposal-create"
        prior = existing(
            session,
            principal=principal,
            route=route,
            study_id=item.study_id,
            key=key,
            request_fingerprint=request_fingerprint,
        )
        if prior is not None:
            return service.response(session, prior)
        proposal = service.create(
            session,
            module_key=module_key,
            aggregate_id=item.id,
            command=command,
            created_by=principal.subject,
            handler=handler(registry),
            settings=settings,
            registry=registry,
            agent_client=agent_client,
        )
        session.add(
            IdempotencyRecord(
                subject=principal.subject,
                route=route,
                study_id=item.study_id,
                key=key,
                request_fingerprint=request_fingerprint,
                resource_type="authoring_proposal",
                resource_id=proposal.id,
            )
        )
        session.commit()
        return service.response(session, proposal)

    @router.get(
        f"{base}/proposals",
        response_model=ProposalPage,
        name=f"list_{module_key}_proposals",
    )
    def list_proposals(
        aggregate_id: UUID,
        session: Annotated[Session, Depends(get_session)],
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> ProposalPage:
        item = aggregate(session, aggregate_id, principal)
        return ProposalPage(
            items=tuple(
                service.response(session, proposal)
                for proposal in service.list(session, module_key=module_key, aggregate_id=item.id)
            )
        )

    @router.get(
        f"{base}/proposals/{{proposal_id}}",
        response_model=ProposalResponse,
        name=f"get_{module_key}_proposal",
    )
    def get_proposal(
        aggregate_id: UUID,
        proposal_id: UUID,
        session: Annotated[Session, Depends(get_session)],
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> ProposalResponse:
        item = aggregate(session, aggregate_id, principal)
        proposal = service.get(session, proposal_id, module_key=module_key, aggregate_id=item.id)
        return service.response(session, proposal)

    def decide(
        *,
        aggregate_id: UUID,
        proposal_id: UUID,
        command: ProposalDecisionCreate,
        decision: str,
        session: Session,
        registry: ModuleRegistry,
        settings: Settings,
        agent_client: PlatformAgentClient,
        principal: Principal,
        if_match: str | None,
        idempotency_key: str | None,
    ) -> ProposalResponse:
        require_human_principal(principal)
        item = aggregate(session, aggregate_id, principal)
        require_matching_etag(if_match, item.revision)
        proposal = service.get(session, proposal_id, module_key=module_key, aggregate_id=item.id)
        key = require_key(idempotency_key)
        request_fingerprint = fingerprint(
            {
                "proposal_id": str(proposal_id),
                "decision": decision,
                **command.model_dump(mode="json"),
            }
        )
        route = f"{module_key}-proposal-{proposal_id}-{decision}"
        prior = existing(
            session,
            principal=principal,
            route=route,
            study_id=item.study_id,
            key=key,
            request_fingerprint=request_fingerprint,
        )
        if prior is not None:
            return service.response(session, prior)
        service.decide(
            session,
            proposal=proposal,
            decision=decision,
            reviewer=principal.subject,
            rationale=command.rationale,
            handler=handler(registry),
            registry=registry,
        )
        result = proposal
        if decision == "revision_requested":
            run = session.get(AiGenerationRun, proposal.generation_run_id)
            if run is None:
                raise RuntimeError("proposal generation run is missing")
            result = service.create(
                session,
                module_key=module_key,
                aggregate_id=item.id,
                command=ProposalCreate(
                    agent_id=UUID(str(run.generation_parameters["platform_agent_id"])),
                    proposal_type=proposal.proposal_type,
                    target=run.target,
                    guidance=command.rationale,
                ),
                created_by=principal.subject,
                handler=handler(registry),
                settings=settings,
                registry=registry,
                agent_client=agent_client,
                supersedes_proposal_id=proposal.id,
                expected_agent_revision=int(
                    str(run.generation_parameters["platform_agent_revision"])
                ),
            )
        session.add(
            IdempotencyRecord(
                subject=principal.subject,
                route=route,
                study_id=item.study_id,
                key=key,
                request_fingerprint=request_fingerprint,
                resource_type="authoring_proposal",
                resource_id=result.id,
            )
        )
        session.commit()
        return service.response(session, result)

    def decision_endpoint(decision: str) -> Callable[..., ProposalResponse]:
        def endpoint(
            aggregate_id: UUID,
            proposal_id: UUID,
            command: ProposalDecisionCreate,
            session: Annotated[Session, Depends(get_session)],
            registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
            settings: Annotated[Settings, Depends(get_application_settings)],
            agent_client: Annotated[
                PlatformAgentClient, Depends(get_platform_agent_client)
            ],
            principal: Annotated[Principal, Depends(get_principal)],
            if_match: Annotated[str | None, Header(alias="If-Match")] = None,
            idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        ) -> ProposalResponse:
            return decide(
                aggregate_id=aggregate_id,
                proposal_id=proposal_id,
                command=command,
                decision=decision,
                session=session,
                registry=registry,
                settings=settings,
                agent_client=agent_client,
                principal=principal,
                if_match=if_match,
                idempotency_key=idempotency_key,
            )

        return endpoint

    for decision, suffix, response_status in (
        ("accepted", "accept", status.HTTP_200_OK),
        ("rejected", "reject", status.HTTP_200_OK),
        ("revision_requested", "request-revision", status.HTTP_202_ACCEPTED),
    ):
        router.add_api_route(
            f"{base}/proposals/{{proposal_id}}:{suffix}",
            decision_endpoint(decision),
            methods=["POST"],
            response_model=ProposalResponse,
            status_code=response_status,
            name=f"{suffix.replace('-', '_')}_{module_key}_proposal",
        )

    return router
