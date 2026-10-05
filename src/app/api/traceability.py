"""Verified cross-module traceability service and routes."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_session
from app.common.problems import ProblemException
from app.common.traceability import TraceLink
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import DependencyCapability
from app.kernel.registry import ModuleRegistry, ModuleRegistryError
from app.studies.service import StudyService

router = APIRouter(tags=["traceability"])
studies = StudyService()


class EntityEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    module: str
    entity_type: str
    entity_id: UUID


class TraceLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relationship_type: str
    source: EntityEndpoint
    target: EntityEndpoint


class TraceLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    relationship_type: str
    source_module: str
    source_entity_type: str
    source_entity_id: UUID
    target_module: str
    target_entity_type: str
    target_entity_id: UUID
    created_by: str
    created_at: datetime


def _resolve(session: Session, registry: ModuleRegistry, endpoint: EntityEndpoint) -> UUID | None:
    try:
        handler = cast(
            DependencyCapability,
            registry.require_handler(endpoint.module, ModuleCapability.ENTITY_RESOLUTION),
        )
    except ModuleRegistryError:
        return None
    return handler.resolve_entity(session, endpoint.entity_type, endpoint.entity_id)


@router.post(
    "/studies/{study_id}/trace-links",
    response_model=TraceLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_trace_link(
    study_id: UUID,
    command: TraceLinkCreate,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> TraceLinkResponse:
    studies.require_access(session, study_id, principal)
    if (
        _resolve(session, registry, command.source) != study_id
        or _resolve(session, registry, command.target) != study_id
    ):
        raise ProblemException(
            status_code=422,
            code="trace_endpoint_invalid",
            title="Trace endpoint is invalid",
            detail="Both endpoints must exist in the same study.",
        )
    link = TraceLink(
        study_id=study_id,
        relationship_type=command.relationship_type,
        source_module=command.source.module,
        source_entity_type=command.source.entity_type,
        source_entity_id=command.source.entity_id,
        target_module=command.target.module,
        target_entity_type=command.target.entity_type,
        target_entity_id=command.target.entity_id,
        created_by=principal.subject,
    )
    session.add(link)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="duplicate_trace_link",
            title="Trace link already exists",
            detail="The exact relationship already exists.",
        ) from error
    return TraceLinkResponse.model_validate(link)


@router.get("/studies/{study_id}/trace-links", response_model=list[TraceLinkResponse])
def list_trace_links(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[TraceLinkResponse]:
    studies.require_access(session, study_id, principal)
    return [
        TraceLinkResponse.model_validate(item)
        for item in session.scalars(select(TraceLink).where(TraceLink.study_id == study_id))
    ]


@router.get("/trace-links/{link_id}", response_model=TraceLinkResponse)
def get_trace_link(
    link_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> TraceLinkResponse:
    link = session.get(TraceLink, link_id)
    if link is None:
        raise ProblemException(
            status_code=404,
            code="trace_link_not_found",
            title="Trace link not found",
            detail="The link does not exist.",
        )
    studies.require_access(session, link.study_id, principal)
    return TraceLinkResponse.model_validate(link)


@router.delete("/trace-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trace_link(
    link_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> None:
    link = session.get(TraceLink, link_id)
    if link is None:
        raise ProblemException(
            status_code=404,
            code="trace_link_not_found",
            title="Trace link not found",
            detail="The link does not exist.",
        )
    studies.require_access(session, link.study_id, principal)
    session.delete(link)
    session.commit()


@router.get("/studies/{study_id}/traceability", response_model=list[TraceLinkResponse])
def query_traceability(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    entity_id: UUID | None = None,
) -> list[TraceLinkResponse]:
    studies.require_access(session, study_id, principal)
    statement = select(TraceLink).where(TraceLink.study_id == study_id)
    if entity_id is not None:
        statement = statement.where(
            or_(TraceLink.source_entity_id == entity_id, TraceLink.target_entity_id == entity_id)
        )
    return [TraceLinkResponse.model_validate(item) for item in session.scalars(statement)]
