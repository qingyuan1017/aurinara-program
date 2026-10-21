"""Submission-package request, status, collection, and download APIs."""

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_object_storage, get_session
from app.artifacts.models import Artifact
from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.idempotency import IdempotencyRecord
from app.common.pagination import paginate
from app.common.problems import ProblemException
from app.execution.jobs import Job
from app.kernel.registry import ModuleRegistry
from app.packaging.models import SubmissionPackage
from app.packaging.service import resolve_package
from app.studies.service import StudyService

router = APIRouter(tags=["packaging"])
studies = StudyService()


class ModuleSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module: str = Field(pattern=r"^[a-z][a-z0-9]{1,31}$")
    artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    options: dict[str, object] = Field(default_factory=dict)


class SubmissionPackageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    module_selections: tuple[ModuleSelection, ...] = Field(min_length=1)
    artifact_ids: tuple[UUID, ...] = ()
    reconciliation_run_ids: tuple[UUID, ...] = ()
    expected_study_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class SubmissionPackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    name: str
    module_selections: list[dict[str, object]]
    artifact_ids: list[str]
    reconciliation_run_ids: list[str]
    input_fingerprint: str
    status: str
    issues: list[dict[str, object]]
    manifest: dict[str, object]
    zip_artifact_id: UUID | None
    report_artifact_id: UUID | None
    created_by: str
    created_at: datetime
    completed_at: datetime | None


class SubmissionPackageCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: tuple[SubmissionPackageResponse, ...]
    next_cursor: str | None


def _require_package(session: Session, package_id: UUID, principal: Principal) -> SubmissionPackage:
    package = session.get(SubmissionPackage, package_id)
    if package is None:
        raise ProblemException(
            status_code=404,
            code="submission_package_not_found",
            title="Submission package not found",
            detail="The submission package does not exist.",
        )
    studies.require_access(session, package.study_id, principal)
    return package


@router.post(
    "/studies/{study_id}/submission-packages",
    response_model=SubmissionPackageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_submission_package(
    study_id: UUID,
    command: SubmissionPackageCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SubmissionPackageResponse:
    studies.require_access(session, study_id, principal, action="aurinara.packaging.run")
    if not idempotency_key:
        raise ProblemException(
            status_code=400,
            code="idempotency_key_required",
            title="Idempotency-Key is required",
            detail="Supply an Idempotency-Key header.",
        )
    module_selections = tuple(item.model_dump(mode="json") for item in command.module_selections)
    resolved = resolve_package(
        session,
        registry,
        study_id=study_id,
        module_selections=module_selections,
        supporting_artifact_ids=command.artifact_ids,
        reconciliation_run_ids=command.reconciliation_run_ids,
    )
    if resolved.fingerprint != command.expected_study_fingerprint:
        raise ProblemException(
            status_code=409,
            code="stale_input_fingerprint",
            title="Package input fingerprint is stale",
            detail="The expected fingerprint does not match the exact resolved selection.",
        )
    request_fingerprint = fingerprint(
        {"name": command.name, "resolved_fingerprint": resolved.fingerprint}
    )
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.subject == principal.subject,
            IdempotencyRecord.route == "submission-packages",
            IdempotencyRecord.study_id == study_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise ProblemException(
                status_code=409,
                code="idempotency_key_reused",
                title="Idempotency key was reused",
                detail="The key is already bound to a different package selection.",
            )
        prior = session.get(SubmissionPackage, existing.resource_id)
        if prior is None:
            raise RuntimeError("idempotency record references a missing package")
        response.headers["Location"] = f"/api/v1/submission-packages/{prior.id}"
        return SubmissionPackageResponse.model_validate(prior)
    package = SubmissionPackage(
        study_id=study_id,
        name=command.name,
        module_selections=list(module_selections),
        artifact_ids=[str(value) for value in command.artifact_ids],
        reconciliation_run_ids=[str(value) for value in command.reconciliation_run_ids],
        input_fingerprint=resolved.fingerprint,
        status="queued",
        issues=[],
        manifest={},
        created_by=principal.subject,
    )
    session.add(package)
    session.flush()
    session.add(
        Job(
            operation_id=package.id,
            job_type="submission_package",
            payload={"package_id": str(package.id)},
            max_attempts=3,
        )
    )
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route="submission-packages",
            study_id=study_id,
            key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_type="submission_package",
            resource_id=package.id,
        )
    )
    session.commit()
    response.headers["Location"] = f"/api/v1/submission-packages/{package.id}"
    return SubmissionPackageResponse.model_validate(package)


@router.get("/studies/{study_id}/submission-packages", response_model=SubmissionPackageCollection)
def list_submission_packages(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    after: str | None = None,
) -> SubmissionPackageCollection:
    studies.require_access(session, study_id, principal)
    records = tuple(
        session.scalars(
            select(SubmissionPackage)
            .where(SubmissionPackage.study_id == study_id)
            .order_by(SubmissionPackage.created_at.desc(), SubmissionPackage.id.desc())
        )
    )
    page, next_cursor = paginate(
        records, limit=limit, after=after, filters={"study_id": str(study_id)}
    )
    return SubmissionPackageCollection(
        items=tuple(SubmissionPackageResponse.model_validate(item) for item in page),
        next_cursor=next_cursor,
    )


@router.get("/submission-packages/{package_id}", response_model=SubmissionPackageResponse)
def get_submission_package(
    package_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> SubmissionPackageResponse:
    return SubmissionPackageResponse.model_validate(
        _require_package(session, package_id, principal)
    )


@router.get("/submission-packages/{package_id}/download")
def download_submission_package(
    package_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> StreamingResponse:
    package = _require_package(session, package_id, principal)
    artifact = (
        session.get(Artifact, package.zip_artifact_id)
        if package.zip_artifact_id is not None
        else None
    )
    if package.status != "succeeded" or artifact is None or artifact.status != "available":
        raise ProblemException(
            status_code=409,
            code="submission_package_unavailable",
            title="Submission package is unavailable",
            detail="Only a successfully completed package can be downloaded.",
        )
    object_key = artifact.object_key

    def body() -> Iterator[bytes]:
        with storage.open(object_key) as source:
            while chunk := source.read(1024 * 1024):
                yield chunk

    return StreamingResponse(
        body(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="submission-package.zip"'},
    )
