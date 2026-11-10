"""SDTM AI proposal generation and explicit human-review routes."""

from typing import Annotated, cast
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
from app.sdtm.models import SdtmWorkbench
from app.studies.service import StudyService

router = APIRouter(tags=["sdtm", "ai-proposals"])
service = AssistanceService()
studies = StudyService()


def _workbench(session: Session, sdtm_id: UUID, principal: Principal) -> SdtmWorkbench:
    workbench = session.get(SdtmWorkbench, sdtm_id)
    if workbench is None:
        raise ProblemException(
            status_code=404,
            code="sdtm_not_found",
            title="SDTM workbench not found",
            detail="The SDTM workbench does not exist.",
        )
    studies.require_access(session, workbench.study_id, principal)
    return workbench


def _handler(registry: ModuleRegistry) -> ProposalCapability:
    return cast(
        ProposalCapability,
        registry.require_handler("sdtm", ModuleCapability.PROPOSALS),
    )


def _require_idempotency_key(value: str | None) -> str:
    if not value:
        raise ProblemException(
            status_code=422,
            code="idempotency_key_required",
            title="Idempotency-Key is required",
            detail="Supply an Idempotency-Key header for this proposal operation.",
        )
    return value


def _existing_idempotent(
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
    "/sdtm-workbenches/{sdtm_id}/proposals",
    response_model=ProposalResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_proposal(
    sdtm_id: UUID,
    command: ProposalCreate,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    agent_client: Annotated[PlatformAgentClient, Depends(get_platform_agent_client)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProposalResponse:
    workbench = _workbench(session, sdtm_id, principal)
    key = _require_idempotency_key(idempotency_key)
    request_fingerprint = fingerprint(command.model_dump(mode="json"))
    route = "sdtm-proposal-create"
    existing = _existing_idempotent(
        session,
        principal=principal,
        route=route,
        study_id=workbench.study_id,
        key=key,
        request_fingerprint=request_fingerprint,
    )
    if existing is not None:
        return service.response(session, existing)
    proposal = service.create(
        session,
        module_key="sdtm",
        aggregate_id=workbench.id,
        command=command,
        created_by=principal.subject,
        handler=_handler(registry),
        settings=settings,
        registry=registry,
        agent_client=agent_client,
    )
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route=route,
            study_id=workbench.study_id,
            key=key,
            request_fingerprint=request_fingerprint,
            resource_type="authoring_proposal",
            resource_id=proposal.id,
        )
    )
    session.commit()
    return service.response(session, proposal)


@router.get("/sdtm-workbenches/{sdtm_id}/proposals", response_model=ProposalPage)
def list_proposals(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ProposalPage:
    workbench = _workbench(session, sdtm_id, principal)
    return ProposalPage(
        items=tuple(
            service.response(session, item)
            for item in service.list(session, module_key="sdtm", aggregate_id=workbench.id)
        )
    )


@router.get(
    "/sdtm-workbenches/{sdtm_id}/proposals/{proposal_id}",
    response_model=ProposalResponse,
)
def get_proposal(
    sdtm_id: UUID,
    proposal_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ProposalResponse:
    workbench = _workbench(session, sdtm_id, principal)
    return service.response(
        session,
        service.get(session, proposal_id, module_key="sdtm", aggregate_id=workbench.id),
    )


def _decide(
    *,
    sdtm_id: UUID,
    proposal_id: UUID,
    command: ProposalDecisionCreate,
    decision: str,
    session: Session,
    registry: ModuleRegistry,
    principal: Principal,
    settings: Settings,
    agent_client: PlatformAgentClient,
    if_match: str | None,
    idempotency_key: str | None,
) -> ProposalResponse:
    require_human_principal(principal)
    workbench = _workbench(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    proposal = service.get(
        session, proposal_id, module_key="sdtm", aggregate_id=workbench.id
    )
    key = _require_idempotency_key(idempotency_key)
    request_fingerprint = fingerprint(
        {"proposal_id": str(proposal_id), "decision": decision, **command.model_dump(mode="json")}
    )
    route = f"sdtm-proposal-{proposal_id}-{decision}"
    existing = _existing_idempotent(
        session,
        principal=principal,
        route=route,
        study_id=workbench.study_id,
        key=key,
        request_fingerprint=request_fingerprint,
    )
    if existing is not None:
        return service.response(session, existing)
    service.decide(
        session,
        proposal=proposal,
        decision=decision,
        reviewer=principal.subject,
        rationale=command.rationale,
        handler=_handler(registry),
        registry=registry,
    )
    result = proposal
    if decision == "revision_requested":
        run = session.get(AiGenerationRun, proposal.generation_run_id)
        if run is None:
            raise RuntimeError("proposal generation run is missing")
        result = service.create(
            session,
            module_key="sdtm",
            aggregate_id=workbench.id,
            command=ProposalCreate(
                agent_id=UUID(str(run.generation_parameters["platform_agent_id"])),
                proposal_type=proposal.proposal_type,
                target=run.target,
                guidance=command.rationale,
            ),
            created_by=principal.subject,
            handler=_handler(registry),
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
            study_id=workbench.study_id,
            key=key,
            request_fingerprint=request_fingerprint,
            resource_type="authoring_proposal",
            resource_id=result.id,
        )
    )
    session.commit()
    return service.response(session, result)


@router.post(
    "/sdtm-workbenches/{sdtm_id}/proposals/{proposal_id}:accept",
    response_model=ProposalResponse,
)
def accept_proposal(
    sdtm_id: UUID,
    proposal_id: UUID,
    command: ProposalDecisionCreate,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    agent_client: Annotated[PlatformAgentClient, Depends(get_platform_agent_client)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProposalResponse:
    return _decide(
        sdtm_id=sdtm_id,
        proposal_id=proposal_id,
        command=command,
        decision="accepted",
        session=session,
        registry=registry,
        principal=principal,
        settings=settings,
        agent_client=agent_client,
        if_match=if_match,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/sdtm-workbenches/{sdtm_id}/proposals/{proposal_id}:reject",
    response_model=ProposalResponse,
)
def reject_proposal(
    sdtm_id: UUID,
    proposal_id: UUID,
    command: ProposalDecisionCreate,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    agent_client: Annotated[PlatformAgentClient, Depends(get_platform_agent_client)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProposalResponse:
    return _decide(
        sdtm_id=sdtm_id,
        proposal_id=proposal_id,
        command=command,
        decision="rejected",
        session=session,
        registry=registry,
        principal=principal,
        settings=settings,
        agent_client=agent_client,
        if_match=if_match,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/sdtm-workbenches/{sdtm_id}/proposals/{proposal_id}:request-revision",
    response_model=ProposalResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_proposal_revision(
    sdtm_id: UUID,
    proposal_id: UUID,
    command: ProposalDecisionCreate,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    agent_client: Annotated[PlatformAgentClient, Depends(get_platform_agent_client)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProposalResponse:
    return _decide(
        sdtm_id=sdtm_id,
        proposal_id=proposal_id,
        command=command,
        decision="revision_requested",
        session=session,
        registry=registry,
        principal=principal,
        settings=settings,
        agent_client=agent_client,
        if_match=if_match,
        idempotency_key=idempotency_key,
    )
