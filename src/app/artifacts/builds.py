"""Idempotent asynchronous artifact-build API and worker handler."""

from datetime import datetime
from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_session
from app.artifacts.models import ArtifactBuild
from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.idempotency import IdempotencyRecord
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.execution.jobs import Job
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import RenderedArtifact
from app.kernel.registry import ModuleRegistry
from app.studies.service import StudyService

router = APIRouter(tags=["artifact-builds"])
studies = StudyService()


class ArtifactBuilderCapability(Protocol):
    entity_type: str

    def resolve_entity(
        self, session: Session, entity_type: str, entity_id: UUID
    ) -> UUID | None: ...

    def build_artifact_payload(
        self, session: Session, aggregate_id: UUID, study_id: UUID, artifact_type: str
    ) -> dict[str, object]: ...

    def render_artifact(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> RenderedArtifact: ...


class ArtifactBuildCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    study_id: UUID
    owner_type: str
    owner_id: UUID
    artifact_types: tuple[str, ...] = Field(min_length=1)
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("artifact_types")
    @classmethod
    def unique_artifact_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("artifact types must be unique")
        return value


class ArtifactBuildResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    module_key: str
    owner_type: str
    owner_id: UUID
    artifact_types: list[str]
    options: dict[str, object]
    input_fingerprint: str
    status: str
    result_artifact_ids: list[str]
    failure: dict[str, object] | None
    started_at: datetime | None
    completed_at: datetime | None
    created_by: str
    created_at: datetime


def resolve_build_input(
    session: Session,
    registry: ModuleRegistry,
    *,
    study_id: UUID,
    owner_type: str,
    owner_id: UUID,
    artifact_types: tuple[str, ...] | list[str],
    options: dict[str, object],
) -> tuple[str, ArtifactBuilderCapability, dict[str, object]]:
    """Resolve ownership and return the canonical exact build input."""

    module_key = registry.owner_of("entity_types", owner_type)
    if module_key is None:
        raise ProblemException(
            status_code=422,
            code="artifact_owner_unsupported",
            title="Artifact owner is unsupported",
            detail="No enabled module owns the requested entity type.",
        )
    descriptor = registry.require(module_key)
    if not set(artifact_types) <= set(descriptor.artifact_types):
        raise ProblemException(
            status_code=422,
            code="artifact_type_unsupported",
            title="Artifact type is unsupported",
            detail="Every requested artifact type must be owned by the target module.",
        )
    handler = cast(
        ArtifactBuilderCapability,
        registry.require_handler(module_key, ModuleCapability.ARTIFACTS),
    )
    if handler.resolve_entity(session, owner_type, owner_id) != study_id:
        raise ProblemException(
            status_code=422,
            code="artifact_owner_invalid",
            title="Artifact owner is invalid",
            detail="The owner does not exist in the selected study.",
        )
    payloads = [
        handler.build_artifact_payload(session, owner_id, study_id, artifact_type)
        for artifact_type in artifact_types
    ]
    resolved: dict[str, object] = {
        "study_id": str(study_id),
        "owner_type": owner_type,
        "owner_id": str(owner_id),
        "artifact_types": list(artifact_types),
        "options": options,
        "payloads": payloads,
    }
    return module_key, handler, resolved


def _require_build(session: Session, build_id: UUID, principal: Principal) -> ArtifactBuild:
    build = session.get(ArtifactBuild, build_id)
    if build is None:
        raise ProblemException(
            status_code=404,
            code="artifact_build_not_found",
            title="Artifact build not found",
            detail="The artifact build does not exist.",
        )
    studies.require_access(session, build.study_id, principal)
    return build


@router.post(
    "/artifact-builds",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_artifact_build(
    command: ArtifactBuildCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    studies.require_access(session, command.study_id, principal)
    if not idempotency_key:
        raise ProblemException(
            status_code=400,
            code="idempotency_key_required",
            title="Idempotency-Key is required",
            detail="Supply an Idempotency-Key header.",
        )
    module_key, _, resolved = resolve_build_input(
        session,
        registry,
        study_id=command.study_id,
        owner_type=command.owner_type,
        owner_id=command.owner_id,
        artifact_types=command.artifact_types,
        options=dict(command.options),
    )
    input_fingerprint = fingerprint(resolved)
    if input_fingerprint != command.expected_input_fingerprint:
        raise ProblemException(
            status_code=409,
            code="stale_input_fingerprint",
            title="Input fingerprint is stale",
            detail="The expected input fingerprint does not match the resolved exact inputs.",
        )
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.subject == principal.subject,
            IdempotencyRecord.route == "artifact-builds",
            IdempotencyRecord.study_id == command.study_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != input_fingerprint:
            raise ProblemException(
                status_code=409,
                code="idempotency_key_reused",
                title="Idempotency key was reused",
                detail="The key is already bound to different exact inputs.",
            )
        prior = session.get(ArtifactBuild, existing.resource_id)
        if prior is None:
            raise RuntimeError("idempotency record references a missing artifact build")
        return ArtifactBuildResponse.model_validate(prior)
    build = ArtifactBuild(
        study_id=command.study_id,
        module_key=module_key,
        owner_type=command.owner_type,
        owner_id=command.owner_id,
        artifact_types=list(command.artifact_types),
        options=command.options,
        input_fingerprint=input_fingerprint,
        created_by=principal.subject,
    )
    session.add(build)
    session.flush()
    session.add(
        Job(
            operation_id=build.id,
            job_type="artifact_build",
            payload={"build_id": str(build.id)},
            max_attempts=3,
        )
    )
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route="artifact-builds",
            study_id=command.study_id,
            key=idempotency_key,
            request_fingerprint=input_fingerprint,
            resource_type="artifact_build",
            resource_id=build.id,
        )
    )
    session.commit()
    response.headers["Location"] = f"/api/v1/artifact-builds/{build.id}"
    return ArtifactBuildResponse.model_validate(build)


@router.get("/artifact-builds/{build_id}", response_model=ArtifactBuildResponse)
def get_artifact_build(
    build_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ArtifactBuildResponse:
    return ArtifactBuildResponse.model_validate(_require_build(session, build_id, principal))


@router.post("/artifact-builds/{build_id}/cancel", response_model=ArtifactBuildResponse)
def cancel_artifact_build(
    build_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ArtifactBuildResponse:
    build = _require_build(session, build_id, principal)
    if build.status not in {"queued", "running"}:
        raise ProblemException(
            status_code=409,
            code="invalid_lifecycle_transition",
            title="Build cannot be cancelled",
            detail="Only queued or running builds can be cancelled.",
        )
    build.status = "cancelled"
    build.completed_at = utc_now()
    job = session.scalar(select(Job).where(Job.operation_id == build.id))
    if job is not None:
        job.cancellation_requested_at = utc_now()
    session.commit()
    return ArtifactBuildResponse.model_validate(build)
