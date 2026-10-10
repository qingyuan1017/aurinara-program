"""Exact-input execution-run API and lifecycle controls."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_application_settings, get_session
from app.artifacts.models import Artifact
from app.common.canonical import fingerprint
from app.common.idempotency import IdempotencyRecord
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.config import Settings
from app.execution.jobs import Job
from app.execution.models import ExecutionRun
from app.studies.service import StudyService
from app.validation.models import ValidationRun

router = APIRouter(tags=["execution"])
studies = StudyService()


class ExecutionLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu: float = Field(gt=0)
    memory_mb: int = Field(gt=0)
    runtime_seconds: int = Field(gt=0)
    output_bytes: int = Field(gt=0)


class ExecutionRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    study_id: UUID
    module: str = Field(pattern=r"^[a-z][a-z0-9]*$")
    owner_type: str
    owner_id: UUID
    language: str = Field(pattern=r"^(python|r|sas)$")
    program_artifact_id: UUID
    input_artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    validation_run_id: UUID
    input_selection_revision: int = Field(ge=1)
    source_specification_revision: int = Field(ge=1)
    source_plan_type: str
    source_plan_revision: int = Field(ge=1)
    compiler_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    limits: ExecutionLimits

    @model_validator(mode="after")
    def unique_inputs(self) -> "ExecutionRunCreate":
        if len(self.input_artifact_ids) != len(set(self.input_artifact_ids)):
            raise ValueError("input artifact IDs must be unique")
        if self.program_artifact_id in self.input_artifact_ids:
            raise ValueError("the program artifact cannot also be an input artifact")
        return self


class ExecutionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    module: str = Field(validation_alias="module_key")
    owner_type: str
    owner_id: UUID
    language: str
    program_artifact_id: UUID
    input_artifact_ids: list[str]
    validation_run_id: UUID
    input_selection_revision: int
    source_specification_revision: int
    source_plan_type: str
    source_plan_revision: int
    compiler_fingerprint: str
    input_fingerprint: str
    limits: dict[str, object]
    status: str
    output_artifact_ids: list[str]
    failure: dict[str, object] | None
    exit_code: int | None
    metrics: dict[str, object]
    cancellation_requested_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_by: str
    created_at: datetime


def _problem(status_code: int, code: str, title: str, detail: str) -> ProblemException:
    return ProblemException(status_code=status_code, code=code, title=title, detail=detail)


def _require_run(session: Session, run_id: UUID, principal: Principal) -> ExecutionRun:
    run = session.get(ExecutionRun, run_id)
    if run is None:
        raise _problem(
            404, "execution_run_not_found", "Execution run not found", "The run does not exist."
        )
    studies.require_access(session, run.study_id, principal)
    return run


def _validate_limits(requested: ExecutionLimits, settings: Settings) -> None:
    maximums = {
        "cpu": settings.execution_cpu_limit,
        "memory_mb": settings.execution_memory_mb,
        "runtime_seconds": settings.execution_timeout_seconds,
        "output_bytes": settings.execution_output_limit_bytes,
    }
    values = requested.model_dump()
    exceeded = [name for name, maximum in maximums.items() if values[name] > maximum]
    if exceeded:
        raise _problem(
            422,
            "execution_limit_exceeded",
            "Execution limit exceeds server policy",
            f"Requested limits exceed policy for: {', '.join(sorted(exceeded))}.",
        )


def _selected_inputs(program: Artifact) -> dict[UUID, str]:
    selection = program.manifest.get("input_selection")
    if not isinstance(selection, dict):
        raise _problem(
            422,
            "execution_manifest_invalid",
            "Program manifest is invalid",
            "The program does not contain an exact input selection.",
        )
    payload = selection.get("payload")
    sources = None
    if isinstance(payload, dict):
        candidates = [
            payload.get("source_artifacts"),
            payload.get("xpt_artifacts"),
        ]
        selected = [item for item in candidates if isinstance(item, list)]
        if len(selected) == 1:
            sources = selected[0]
    if not isinstance(sources, list):
        raise _problem(
            422,
            "execution_manifest_invalid",
            "Program manifest is invalid",
            "The program input selection does not contain one exact artifact collection.",
        )
    try:
        return {
            UUID(str(item["artifact_id"])): str(item["dataset_code"])
            for item in sources
            if isinstance(item, dict)
        }
    except (KeyError, ValueError) as error:
        raise _problem(
            422,
            "execution_manifest_invalid",
            "Program manifest is invalid",
            "A selected source artifact identity is malformed.",
        ) from error


def _resolve_manifest(
    session: Session, command: ExecutionRunCreate
) -> tuple[Artifact, list[Artifact], ValidationRun, dict[str, object]]:
    program = session.get(Artifact, command.program_artifact_id)
    expected_type = f"{command.module}_program_{command.language}"
    if (
        program is None
        or program.study_id != command.study_id
        or program.module_key != command.module
        or program.owner_type != command.owner_type
        or program.owner_id != command.owner_id
        or program.artifact_type != expected_type
        or program.status != "available"
    ):
        raise _problem(
            422,
            "execution_program_invalid",
            "Execution program is invalid",
            "Select an available program artifact owned by the exact module aggregate.",
        )
    provenance_matches = (
        program.validation_run_id == command.validation_run_id
        and program.input_selection_revision == command.input_selection_revision
        and program.source_specification_revision == command.source_specification_revision
        and program.source_plan_type == command.source_plan_type
        and program.source_plan_revision == command.source_plan_revision
        and program.compiler_fingerprint == command.compiler_fingerprint
        and program.input_fingerprint == command.expected_input_fingerprint
    )
    if not provenance_matches:
        raise _problem(
            409,
            "execution_provenance_mismatch",
            "Execution provenance does not match",
            "The requested revisions and fingerprints must match the immutable program.",
        )
    validation = session.get(ValidationRun, command.validation_run_id)
    if (
        validation is None
        or validation.study_id != command.study_id
        or validation.owner_id != command.owner_id
        or validation.module_key != command.module
        or validation.status != "succeeded"
    ):
        raise _problem(
            422,
            "execution_validation_invalid",
            "Execution validation is invalid",
            "Bind a successful validation run for the exact program owner.",
        )
    selected_inputs = _selected_inputs(program)
    if set(command.input_artifact_ids) != set(selected_inputs):
        raise _problem(
            409,
            "execution_inputs_mismatch",
            "Execution inputs do not match",
            "Input artifacts must exactly match the program compiler manifest.",
        )
    inputs: list[Artifact] = []
    for artifact_id in command.input_artifact_ids:
        artifact = session.get(Artifact, artifact_id)
        if (
            artifact is None
            or artifact.study_id != command.study_id
            or artifact.status != "available"
        ):
            raise _problem(
                422,
                "execution_input_invalid",
                "Execution input is invalid",
                "Every input must be an available immutable artifact in the selected study.",
            )
        inputs.append(artifact)
    manifest: dict[str, object] = {
        "schema_version": "1.0.0",
        "program": {"artifact_id": str(program.id), "sha256": program.sha256},
        "inputs": [
            {
                "artifact_id": str(item.id),
                "dataset": selected_inputs[item.id],
                "sha256": item.sha256,
                "filename": item.filename,
            }
            for item in inputs
        ],
        "validation_run_id": str(validation.id),
        "input_selection_revision": command.input_selection_revision,
        "source_specification_revision": command.source_specification_revision,
        "source_plan_type": command.source_plan_type,
        "source_plan_revision": command.source_plan_revision,
        "compiler_fingerprint": command.compiler_fingerprint,
        "program_input_fingerprint": command.expected_input_fingerprint,
        "source_specification": program.manifest.get("specification"),
        "resolved_dependencies": program.manifest.get("resolved_dependencies"),
    }
    return program, inputs, validation, manifest


@router.post(
    "/execution-runs",
    response_model=ExecutionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_execution_run(
    command: ExecutionRunCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExecutionRunResponse:
    studies.require_access(session, command.study_id, principal)
    if not idempotency_key:
        raise _problem(
            400,
            "idempotency_key_required",
            "Idempotency-Key is required",
            "Supply an Idempotency-Key header.",
        )
    _validate_limits(command.limits, settings)
    _, _, _, manifest = _resolve_manifest(session, command)
    request_fingerprint = fingerprint(
        {"command": command.model_dump(mode="json"), "resolved_manifest": manifest}
    )
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.subject == principal.subject,
            IdempotencyRecord.route == "execution-runs",
            IdempotencyRecord.study_id == command.study_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise _problem(
                409,
                "idempotency_key_reused",
                "Idempotency key was reused",
                "The key is bound to different exact inputs.",
            )
        prior = session.get(ExecutionRun, existing.resource_id)
        if prior is None:
            raise RuntimeError("idempotency record references a missing execution run")
        response.headers["Location"] = f"/api/v1/execution-runs/{prior.id}"
        return ExecutionRunResponse.model_validate(prior)
    terminal_sas = command.language == "sas" and settings.sas_runner_adapter is None
    run = ExecutionRun(
        study_id=command.study_id,
        module_key=command.module,
        owner_type=command.owner_type,
        owner_id=command.owner_id,
        language=command.language,
        program_artifact_id=command.program_artifact_id,
        input_artifact_ids=[str(item) for item in command.input_artifact_ids],
        validation_run_id=command.validation_run_id,
        input_selection_revision=command.input_selection_revision,
        source_specification_revision=command.source_specification_revision,
        source_plan_type=command.source_plan_type,
        source_plan_revision=command.source_plan_revision,
        compiler_fingerprint=command.compiler_fingerprint,
        input_fingerprint=request_fingerprint,
        limits=command.limits.model_dump(),
        manifest=manifest,
        status="failed" if terminal_sas else "queued",
        failure=(
            {"code": "runner_not_configured", "detail": "No external SAS runner is configured."}
            if terminal_sas
            else None
        ),
        completed_at=utc_now() if terminal_sas else None,
        created_by=principal.subject,
    )
    session.add(run)
    session.flush()
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route="execution-runs",
            study_id=command.study_id,
            key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_type="execution_run",
            resource_id=run.id,
        )
    )
    if not terminal_sas:
        session.add(
            Job(
                operation_id=run.id,
                job_type="execution",
                payload={"run_id": str(run.id)},
                max_attempts=settings.job_max_attempts,
            )
        )
    session.commit()
    response.headers["Location"] = f"/api/v1/execution-runs/{run.id}"
    return ExecutionRunResponse.model_validate(run)


@router.get("/execution-runs/{run_id}", response_model=ExecutionRunResponse)
def get_execution_run(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ExecutionRunResponse:
    return ExecutionRunResponse.model_validate(_require_run(session, run_id, principal))


@router.get("/execution-runs/{run_id}/logs")
def get_execution_logs(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    run = _require_run(session, run_id, principal)
    limit = settings.execution_log_limit_bytes
    return {
        "stdout": run.stdout[:limit],
        "stderr": run.stderr[:limit],
        "truncated": len(run.stdout) > limit or len(run.stderr) > limit,
    }


@router.get("/execution-runs/{run_id}/outputs")
def get_execution_outputs(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    run = _require_run(session, run_id, principal)
    artifacts = [session.get(Artifact, UUID(item)) for item in run.output_artifact_ids]
    return {
        "items": [
            {
                "artifact_id": str(item.id),
                "artifact_type": item.artifact_type,
                "sha256": item.sha256,
                "size": item.size,
            }
            for item in artifacts
            if item is not None and item.study_id == run.study_id
        ]
    }


@router.post("/execution-runs/{run_id}/cancel", response_model=ExecutionRunResponse)
def cancel_execution_run(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ExecutionRunResponse:
    run = _require_run(session, run_id, principal)
    if run.status not in {"queued", "running"}:
        raise _problem(
            409,
            "execution_not_cancellable",
            "Execution run is not cancellable",
            "Only queued or running runs can be cancelled.",
        )
    now = utc_now()
    run.cancellation_requested_at = now
    if run.status == "queued":
        run.status = "cancelled"
        run.completed_at = now
    job = session.scalar(select(Job).where(Job.operation_id == run.id))
    if job is not None:
        job.cancellation_requested_at = now
        if job.status == "queued":
            job.status = "succeeded"
            job.completed_at = now
    session.commit()
    return ExecutionRunResponse.model_validate(run)
