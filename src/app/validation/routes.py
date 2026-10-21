"""Declarative validation rule and study rule-pack APIs."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_session
from app.artifacts.models import Artifact
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.execution.jobs import Job
from app.studies.service import StudyService
from app.validation.models import ValidationRule, ValidationRulePack, ValidationRun

router = APIRouter(tags=["validation"])
studies = StudyService()


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    rule_id: str
    version: str
    module_key: str
    applicability: dict[str, object]
    parameter_schema: dict[str, object]
    default_severity: str
    mandatory: bool


class RuleSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    validation_rule_id: UUID
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    severity: str | None = None


class RulePackWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    selections: tuple[RuleSelection, ...]


class RulePackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID | None
    code: str
    name: str
    lifecycle: str
    selections: list[dict[str, object]]
    revision: int
    created_at: datetime
    updated_at: datetime


class ValidationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    module_key: str
    owner_type: str
    owner_id: UUID
    status: str
    validator_name: str
    validator_version: str
    input_fingerprint: str
    started_at: datetime | None
    completed_at: datetime | None
    error_count: int
    warning_count: int
    info_count: int
    issues: list[dict[str, object]]
    report_artifact_ids: list[str]
    failure: dict[str, object] | None
    created_by: str


def _validate_selections(session: Session, selections: tuple[RuleSelection, ...]) -> None:
    if len({item.validation_rule_id for item in selections}) != len(selections):
        raise ProblemException(
            status_code=422,
            code="duplicate_rule_selection",
            title="Rule selection is invalid",
            detail="A rule version can be selected only once.",
        )
    missing = [
        str(item.validation_rule_id)
        for item in selections
        if session.get(ValidationRule, item.validation_rule_id) is None
    ]
    if missing:
        raise ProblemException(
            status_code=422,
            code="rule_version_not_found",
            title="Rule selection is invalid",
            detail=f"Unknown rule versions: {', '.join(missing)}",
        )


@router.get("/validation-rules", response_model=list[RuleResponse])
def list_rules(
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> list[RuleResponse]:
    return [RuleResponse.model_validate(item) for item in session.scalars(select(ValidationRule))]


@router.get("/validation-rules/{rule_id}", response_model=RuleResponse)
def get_rule(
    rule_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> RuleResponse:
    rule = session.get(ValidationRule, rule_id)
    if rule is None:
        raise ProblemException(
            status_code=404,
            code="validation_rule_not_found",
            title="Validation rule not found",
            detail="The exact rule version does not exist.",
        )
    return RuleResponse.model_validate(rule)


@router.get("/validation-rule-packs", response_model=list[RulePackResponse])
def list_platform_rule_packs(
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> list[RulePackResponse]:
    return [
        RulePackResponse.model_validate(item)
        for item in session.scalars(
            select(ValidationRulePack).where(ValidationRulePack.study_id.is_(None))
        )
    ]


@router.get("/validation-rule-packs/{pack_id}", response_model=RulePackResponse)
def get_rule_pack(
    pack_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RulePackResponse:
    pack = session.get(ValidationRulePack, pack_id)
    if pack is None:
        raise ProblemException(
            status_code=404,
            code="rule_pack_not_found",
            title="Rule pack not found",
            detail="The rule pack does not exist.",
        )
    if pack.study_id is not None:
        studies.require_access(session, pack.study_id, principal)
    return RulePackResponse.model_validate(pack)


@router.post(
    "/studies/{study_id}/validation-rule-packs",
    response_model=RulePackResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_rule_pack(
    study_id: UUID,
    command: RulePackWrite,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RulePackResponse:
    studies.require_access(session, study_id, principal)
    _validate_selections(session, command.selections)
    pack = ValidationRulePack(
        study_id=study_id,
        code=command.code,
        name=command.name,
        lifecycle="active",
        selections=[item.model_dump(mode="json") for item in command.selections],
    )
    session.add(pack)
    session.commit()
    response.headers["ETag"] = etag_for_revision(pack.revision)
    return RulePackResponse.model_validate(pack)


@router.get("/studies/{study_id}/validation-rule-packs", response_model=list[RulePackResponse])
def list_study_rule_packs(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[RulePackResponse]:
    studies.require_access(session, study_id, principal)
    return [
        RulePackResponse.model_validate(item)
        for item in session.scalars(
            select(ValidationRulePack).where(ValidationRulePack.study_id == study_id)
        )
    ]


@router.put("/validation-rule-packs/{pack_id}", response_model=RulePackResponse)
def replace_rule_pack(
    pack_id: UUID,
    command: RulePackWrite,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> RulePackResponse:
    pack = session.get(ValidationRulePack, pack_id)
    if pack is None or pack.study_id is None:
        raise ProblemException(
            status_code=404,
            code="rule_pack_not_found",
            title="Rule pack not found",
            detail="The editable study rule pack does not exist.",
        )
    studies.require_access(session, pack.study_id, principal)
    require_matching_etag(if_match, pack.revision)
    _validate_selections(session, command.selections)
    pack.code, pack.name = command.code, command.name
    pack.selections = [item.model_dump(mode="json") for item in command.selections]
    pack.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(pack.revision)
    return RulePackResponse.model_validate(pack)


@router.get("/validation-runs/{run_id}", response_model=ValidationRunResponse)
def get_validation_run(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    run = session.get(ValidationRun, run_id)
    if run is None:
        raise ProblemException(
            status_code=404,
            code="validation_run_not_found",
            title="Validation run not found",
            detail="The run does not exist.",
        )
    studies.require_access(session, run.study_id, principal)
    return ValidationRunResponse.model_validate(run)


@router.post(
    "/artifacts/{artifact_id}/validate",
    response_model=ValidationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def validate_artifact(
    artifact_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise ProblemException(
            status_code=404,
            code="artifact_not_found",
            title="Artifact not found",
            detail="The artifact does not exist.",
        )
    studies.require_access(
        session,
        artifact.study_id,
        principal,
        action="aurinara.validation.run",
    )
    input_manifest = {
        "schema_version": "1.0.0",
        "artifact_id": str(artifact.id),
        "sha256": artifact.sha256,
        "size": artifact.size,
    }
    run = ValidationRun(
        study_id=artifact.study_id,
        module_key=artifact.module_key,
        owner_type="artifact",
        owner_id=artifact.id,
        validator_name="immutable-artifact-integrity",
        validator_version="1.0.0",
        input_fingerprint=fingerprint(input_manifest),
        input_manifest=input_manifest,
        created_by=principal.subject,
    )
    session.add(run)
    session.flush()
    session.add(
        Job(
            operation_id=run.id,
            job_type="validation",
            payload={"run_id": str(run.id)},
            max_attempts=3,
        )
    )
    session.commit()
    response.headers["Location"] = f"/api/v1/validation-runs/{run.id}"
    return ValidationRunResponse.model_validate(run)


@router.post("/validation-runs/{run_id}/cancel", response_model=ValidationRunResponse)
def cancel_validation_run(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    run = session.get(ValidationRun, run_id)
    if run is None:
        raise ProblemException(
            status_code=404,
            code="validation_run_not_found",
            title="Validation run not found",
            detail="The run does not exist.",
        )
    studies.require_access(session, run.study_id, principal)
    if run.status not in {"queued", "running"}:
        raise ProblemException(
            status_code=409,
            code="invalid_lifecycle_transition",
            title="Validation run cannot be cancelled",
            detail="Only queued or running validation runs can be cancelled.",
        )
    run.status = "cancelled"
    run.completed_at = utc_now()
    job = session.scalar(select(Job).where(Job.operation_id == run.id))
    if job is not None:
        job.cancellation_requested_at = utc_now()
    session.commit()
    return ValidationRunResponse.model_validate(run)
