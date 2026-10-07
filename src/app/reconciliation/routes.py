"""Idempotent immutable Reconciliation operation APIs."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_session
from app.artifacts.models import Artifact
from app.common.canonical import fingerprint
from app.common.idempotency import IdempotencyRecord
from app.common.problems import ProblemException
from app.execution.jobs import Job
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import DependencyCapability
from app.kernel.registry import ModuleRegistry
from app.reconciliation.models import ReconciliationRun
from app.studies.service import StudyService

router = APIRouter(tags=["reconciliation"])
studies = StudyService()


class ReconciliationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entity_type: str | None = None
    entity_id: UUID | None = None
    revision: int | None = None
    artifact_id: UUID | None = None
    checksum: str | None = None


class ReconciliationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    study_id: UUID
    reconciliation_type: str
    reconciliation_version: str
    inputs: tuple[ReconciliationInput, ...]
    expected_input_fingerprint: str
    options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ReconciliationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    reconciliation_type: str
    reconciliation_version: str
    status: str
    input_fingerprint: str
    inputs: list[dict[str, object]]
    options: dict[str, object]
    started_at: datetime | None
    completed_at: datetime | None
    error_count: int
    warning_count: int
    info_count: int
    issues: list[dict[str, object]]
    report_artifact_ids: list[str]
    failure: dict[str, object] | None
    created_by: str
    created_at: datetime


@router.post(
    "/reconciliation-runs",
    response_model=ReconciliationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_reconciliation(
    command: ReconciliationCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReconciliationResponse:
    studies.require_access(session, command.study_id, principal)
    for item in command.inputs:
        if item.artifact_id is not None:
            artifact = session.get(Artifact, item.artifact_id)
            if (
                artifact is None
                or artifact.study_id != command.study_id
                or item.checksum is None
                or artifact.sha256 != item.checksum
            ):
                raise ProblemException(
                    status_code=422,
                    code="reconciliation_input_invalid",
                    title="Reconciliation input is invalid",
                    detail="Every artifact input must resolve to the exact study-owned checksum.",
                )
        if item.entity_id is not None or item.entity_type is not None or item.revision is not None:
            if item.entity_id is None or item.entity_type is None or item.revision is None:
                raise ProblemException(
                    status_code=422,
                    code="reconciliation_input_invalid",
                    title="Reconciliation input is invalid",
                    detail="Entity inputs require entity_type, entity_id, and revision.",
                )
            owner = registry.owner_of("entity_types", item.entity_type)
            if owner is None:
                raise ProblemException(
                    status_code=422,
                    code="reconciliation_input_unsupported",
                    title="Reconciliation input is unsupported",
                    detail="No enabled module owns the requested entity type.",
                )
            handler = cast(
                DependencyCapability,
                registry.require_handler(owner, ModuleCapability.RECONCILIATION_INPUTS),
            )
            if (
                handler.resolve_reconciliation_input(
                    session, item.entity_type, item.entity_id, item.revision
                )
                != command.study_id
            ):
                raise ProblemException(
                    status_code=422,
                    code="reconciliation_input_invalid",
                    title="Reconciliation input is invalid",
                    detail="The entity does not exist in the selected study.",
                )
    owner = registry.owner_of("reconciliation_types", command.reconciliation_type)
    if owner is None:
        raise ProblemException(
            status_code=422,
            code="reconciliation_type_unsupported",
            title="Reconciliation type is unsupported",
            detail="No enabled module owns the requested reconciliation type.",
        )
    registry.require_handler(owner, ModuleCapability.RECONCILIATION)
    if not idempotency_key:
        raise ProblemException(
            status_code=400,
            code="idempotency_key_required",
            title="Idempotency-Key is required",
            detail="Supply an Idempotency-Key header.",
        )
    request_payload = command.model_dump(mode="json", exclude={"expected_input_fingerprint"})
    request_fingerprint = fingerprint(request_payload)
    if request_fingerprint != command.expected_input_fingerprint:
        raise ProblemException(
            status_code=409,
            code="stale_input_fingerprint",
            title="Input fingerprint is stale",
            detail="The expected input fingerprint does not match the canonical request.",
        )
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.subject == principal.subject,
            IdempotencyRecord.route == "reconciliation-runs",
            IdempotencyRecord.study_id == command.study_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise ProblemException(
                status_code=409,
                code="idempotency_key_reused",
                title="Idempotency key was reused",
                detail="The key is already bound to a different request.",
            )
        run = session.get(ReconciliationRun, existing.resource_id)
        if run is None:
            raise RuntimeError("idempotency record references a missing run")
        return ReconciliationResponse.model_validate(run)
    run = ReconciliationRun(
        study_id=command.study_id,
        reconciliation_type=command.reconciliation_type,
        reconciliation_version=command.reconciliation_version,
        input_fingerprint=request_fingerprint,
        inputs=[item.model_dump(mode="json") for item in command.inputs],
        options=command.options,
        created_by=principal.subject,
    )
    session.add(run)
    session.flush()
    session.add(
        Job(
            operation_id=run.id,
            job_type="reconciliation",
            payload={"run_id": str(run.id)},
            max_attempts=3,
        )
    )
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route="reconciliation-runs",
            study_id=command.study_id,
            key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_type="reconciliation_run",
            resource_id=run.id,
        )
    )
    session.commit()
    response.headers["Location"] = f"/api/v1/reconciliation-runs/{run.id}"
    return ReconciliationResponse.model_validate(run)


@router.get("/reconciliation-runs/{run_id}", response_model=ReconciliationResponse)
def get_reconciliation(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReconciliationResponse:
    run = session.get(ReconciliationRun, run_id)
    if run is None:
        raise ProblemException(
            status_code=404,
            code="reconciliation_run_not_found",
            title="Reconciliation run not found",
            detail="The run does not exist.",
        )
    studies.require_access(session, run.study_id, principal)
    return ReconciliationResponse.model_validate(run)


@router.post("/reconciliation-runs/{run_id}/cancel", response_model=ReconciliationResponse)
def cancel_reconciliation(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReconciliationResponse:
    run = session.get(ReconciliationRun, run_id)
    if run is None:
        raise ProblemException(
            status_code=404,
            code="reconciliation_run_not_found",
            title="Reconciliation run not found",
            detail="The run does not exist.",
        )
    studies.require_access(session, run.study_id, principal)
    if run.status not in {"queued", "running"}:
        raise ProblemException(
            status_code=409,
            code="invalid_lifecycle_transition",
            title="Run cannot be cancelled",
            detail="Only queued or running runs can be cancelled.",
        )
    run.status = "cancelled"
    job = session.scalar(select(Job).where(Job.operation_id == run.id))
    if job is not None:
        job.cancellation_requested_at = datetime.now().astimezone()
    session.commit()
    return ReconciliationResponse.model_validate(run)


@router.get("/reconciliation-runs/{run_id}/issues", response_model=list[dict[str, object]])
def list_reconciliation_issues(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[dict[str, object]]:
    run = session.get(ReconciliationRun, run_id)
    if run is None:
        raise ProblemException(
            status_code=404,
            code="reconciliation_run_not_found",
            title="Reconciliation run not found",
            detail="The run does not exist.",
        )
    studies.require_access(session, run.study_id, principal)
    return run.issues
