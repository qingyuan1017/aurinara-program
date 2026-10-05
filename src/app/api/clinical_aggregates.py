"""Consistent Phase 1 identity and dependency routes for clinical modules."""

from collections.abc import Callable
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_session
from app.common.etag import etag_for_revision
from app.common.pagination import paginate
from app.common.problems import ProblemException
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import (
    AggregateCreate,
    AggregateResponse,
    DependencyCapability,
    DependencySelectionInput,
    DependencySelectionResponse,
)
from app.kernel.registry import ModuleRegistry
from app.studies.service import StudyService

studies = StudyService()


class AggregateCollection(BaseModel):
    """Stable clinical aggregate collection."""

    items: tuple[AggregateResponse, ...]
    next_cursor: str | None = None


def _handler(registry: ModuleRegistry, module_key: str) -> DependencyCapability:
    return cast(
        DependencyCapability,
        registry.require_handler(module_key, ModuleCapability.DEPENDENCIES),
    )


def _create_endpoint(module_key: str) -> Callable[..., AggregateResponse]:
    def create(
        study_id: UUID,
        command: AggregateCreate,
        response: Response,
        session: Annotated[Session, Depends(get_session)],
        registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> AggregateResponse:
        studies.require_access(session, study_id, principal)
        aggregate = _handler(registry, module_key).create(session, study_id, command)
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise ProblemException(
                status_code=409,
                code="duplicate_natural_key",
                title="Aggregate code already exists",
                detail="The code is already used in this study and module.",
            ) from error
        result = AggregateResponse.model_validate(aggregate)
        response.headers["ETag"] = etag_for_revision(result.revision)
        return result

    return create


def _list_endpoint(module_key: str) -> Callable[..., AggregateCollection]:
    def list_items(
        study_id: UUID,
        session: Annotated[Session, Depends(get_session)],
        registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
        principal: Annotated[Principal, Depends(get_principal)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        after: str | None = None,
    ) -> AggregateCollection:
        studies.require_access(session, study_id, principal)
        records, next_cursor = paginate(
            _handler(registry, module_key).list(session, study_id),
            limit=limit,
            after=after,
            filters={"study_id": str(study_id), "module": module_key},
        )
        return AggregateCollection(
            items=tuple(AggregateResponse.model_validate(record) for record in records),
            next_cursor=next_cursor,
        )

    return list_items


def _get_endpoint(module_key: str, parameter_name: str) -> Callable[..., AggregateResponse]:
    def get_item(
        aggregate_id: Annotated[UUID, Path(alias=parameter_name)],
        response: Response,
        session: Annotated[Session, Depends(get_session)],
        registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> AggregateResponse:
        handler = _handler(registry, module_key)
        study_id = handler.resolve_entity(session, handler.entity_type, aggregate_id)
        if study_id is None:
            raise ProblemException(
                status_code=404,
                code=f"{module_key}_not_found",
                title="Clinical aggregate not found",
                detail="The aggregate does not exist.",
            )
        studies.require_access(session, study_id, principal)
        result = AggregateResponse.model_validate(handler.require(session, aggregate_id, study_id))
        response.headers["ETag"] = etag_for_revision(result.revision)
        return result

    return get_item


def _get_dependencies_endpoint(
    module_key: str, parameter_name: str
) -> Callable[..., DependencySelectionResponse]:
    def get_dependencies(
        aggregate_id: Annotated[UUID, Path(alias=parameter_name)],
        session: Annotated[Session, Depends(get_session)],
        registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> DependencySelectionResponse:
        handler = _handler(registry, module_key)
        study_id = handler.resolve_entity(session, handler.entity_type, aggregate_id)
        if study_id is None:
            raise ProblemException(
                status_code=404,
                code=f"{module_key}_not_found",
                title="Clinical aggregate not found",
                detail="The aggregate does not exist.",
            )
        studies.require_access(session, study_id, principal)
        return handler.get_selection(session, aggregate_id, study_id)

    return get_dependencies


def _put_dependencies_endpoint(
    module_key: str, parameter_name: str
) -> Callable[..., DependencySelectionResponse]:
    def put_dependencies(
        aggregate_id: Annotated[UUID, Path(alias=parameter_name)],
        command: DependencySelectionInput,
        response: Response,
        session: Annotated[Session, Depends(get_session)],
        registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
        principal: Annotated[Principal, Depends(get_principal)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> DependencySelectionResponse:
        handler = _handler(registry, module_key)
        study_id = handler.resolve_entity(session, handler.entity_type, aggregate_id)
        if study_id is None:
            raise ProblemException(
                status_code=404,
                code=f"{module_key}_not_found",
                title="Clinical aggregate not found",
                detail="The aggregate does not exist.",
            )
        studies.require_access(session, study_id, principal)
        aggregate, selection = handler.replace_selection(
            session, aggregate_id, study_id, command, if_match
        )
        session.commit()
        response.headers["ETag"] = etag_for_revision(aggregate.revision)
        return selection

    return put_dependencies


def dependency_aggregate_router(
    module_key: str,
    collection_path: str,
    member_path: str,
    parameter_name: str,
) -> APIRouter:
    """Build consistent routes for any reviewed dependency-consuming module."""

    router = APIRouter(tags=[module_key])
    router.add_api_route(
        collection_path,
        _create_endpoint(module_key),
        methods=["POST"],
        response_model=AggregateResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id=f"create_{module_key}_aggregate",
    )
    router.add_api_route(
        collection_path,
        _list_endpoint(module_key),
        methods=["GET"],
        response_model=AggregateCollection,
        operation_id=f"list_{module_key}_aggregates",
    )
    router.add_api_route(
        member_path,
        _get_endpoint(module_key, parameter_name),
        methods=["GET"],
        response_model=AggregateResponse,
        operation_id=f"get_{module_key}_aggregate",
    )
    router.add_api_route(
        f"{member_path}/dependencies",
        _get_dependencies_endpoint(module_key, parameter_name),
        methods=["GET"],
        response_model=DependencySelectionResponse,
        operation_id=f"get_{module_key}_dependencies",
    )
    router.add_api_route(
        f"{member_path}/dependencies",
        _put_dependencies_endpoint(module_key, parameter_name),
        methods=["PUT"],
        response_model=DependencySelectionResponse,
        operation_id=f"replace_{module_key}_dependencies",
    )
    return router
