"""TLF authoring, validation, compilation, execution, and rendering APIs."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_application_settings, get_module_registry, get_session
from app.artifacts.builds import ArtifactBuildCreate, ArtifactBuildResponse, create_artifact_build
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.config import Settings
from app.execution.routes import (
    ExecutionLimits,
    ExecutionRunCreate,
    ExecutionRunResponse,
    create_execution_run,
)
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry
from app.studies.service import StudyService
from app.tlf.contracts import TlfArs, TlfAssumptions, TlfBindings, TlfProgramPlan, TlfShell
from app.tlf.models import TlfAuthoringRevision, TlfWorkbench
from app.tlf.service import (
    TLF_BUILD_ARTIFACT_TYPES,
    TLF_RENDER_ARTIFACT_TYPES,
    TlfCapability,
    authoring_manifest,
    content_contract,
    lower_analysis_ir,
)
from app.transformation.analysis import canonical_analysis_ir
from app.validation.models import ValidationRun
from app.validation.routes import ValidationRunResponse

router = APIRouter(tags=["tlf"])
studies = StudyService()


class AuthoringResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    aggregate_id: UUID
    content_type: str
    revision: int
    schema_version: str
    state: str
    payload: dict[str, object]
    fingerprint: str
    created_by: str
    created_at: datetime


class PreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    normalized_result_schema: dict[str, str]
    procedure_count: int
    analysis_ir_fingerprint: str
    normalized_analysis_ir: dict[str, object]


class ArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_types: tuple[str, ...] = Field(min_length=1)
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: str = Field(pattern=r"^(python|r|sas)$")
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: str = Field(pattern=r"^(rtf|pdf|png|svg)$")
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class TlfExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str = Field(pattern=r"^(python|r|sas)$")
    program_artifact_id: UUID
    input_artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    validation_run_id: UUID
    bindings_revision: int = Field(ge=1)
    shell_revision: int = Field(ge=1)
    program_plan_revision: int = Field(ge=1)
    compiler_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    limits: ExecutionLimits


def _handler(registry: ModuleRegistry) -> TlfCapability:
    return cast(TlfCapability, registry.require_handler("tlf", ModuleCapability.DEPENDENCIES))


def _workbench(session: Session, tlf_id: UUID, principal: Principal) -> TlfWorkbench:
    workbench = session.get(TlfWorkbench, tlf_id)
    if workbench is None:
        raise ProblemException(
            status_code=404,
            code="tlf_not_found",
            title="TLF workbench not found",
            detail="The TLF workbench does not exist.",
        )
    studies.require_access(session, workbench.study_id, principal)
    return workbench


def _get_content(
    content_type: str,
    tlf_id: UUID,
    response: Response,
    session: Session,
    registry: ModuleRegistry,
    principal: Principal,
) -> AuthoringResponse:
    workbench = _workbench(session, tlf_id, principal)
    record = _handler(registry).latest_content(session, workbench.id, content_type)
    if record is None:
        raise ProblemException(
            status_code=404,
            code=f"tlf_{content_type}_not_found",
            title="TLF authoring resource not found",
            detail=f"The TLF {content_type.replace('_', ' ')} has not been authored.",
        )
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return AuthoringResponse.model_validate(record)


def _put_content(
    content_type: str,
    command: TlfShell | TlfBindings | TlfAssumptions | TlfArs | TlfProgramPlan,
    tlf_id: UUID,
    response: Response,
    session: Session,
    registry: ModuleRegistry,
    principal: Principal,
    if_match: str | None,
) -> AuthoringResponse:
    workbench = _workbench(session, tlf_id, principal)
    require_matching_etag(if_match, workbench.revision)
    handler = _handler(registry)
    if content_type == "bindings":
        handler.validate_bindings(session, workbench.study_id, cast(TlfBindings, command))
    current = {
        key: handler.latest_content(session, workbench.id, key)
        for key in ("shell", "bindings", "assumptions", "ars")
    }
    if content_type == "ars":
        shell_record = current["shell"]
        bindings_record = current["bindings"]
        if shell_record is None or bindings_record is None:
            raise ProblemException(
                status_code=409,
                code="tlf_ars_prerequisites_missing",
                title="TLF ARS prerequisites are missing",
                detail="Author shell and bindings before ARS.",
            )
        shell = cast(TlfShell, content_contract(shell_record))
        bindings = cast(TlfBindings, content_contract(bindings_record))
        ars = cast(TlfArs, command)
        leaf_ids = {row.id for row in shell.rows if row.leaf}
        if {item.leaf_row_id for item in ars.analyses} != leaf_ids:
            raise ProblemException(
                status_code=422,
                code="tlf_leaf_coverage_invalid",
                title="TLF shell leaf coverage is invalid",
                detail="ARS must contain exactly one analysis for every leaf shell row.",
            )
        dataset_ids = {item.id for item in bindings.datasets}
        named_ids = {item.id for item in bindings.named}
        if any(
            item.dataset_binding_id not in dataset_ids
            or item.population_binding_id not in named_ids
            or item.statistic_binding_id not in named_ids
            or (
                item.parameter_binding_id is not None and item.parameter_binding_id not in named_ids
            )
            for item in ars.analyses
        ):
            raise ProblemException(
                status_code=422,
                code="tlf_reference_invalid",
                title="TLF ARS reference is invalid",
                detail="Every ARS reference must resolve to the current exact bindings.",
            )
    if content_type == "program_plan":
        if any(value is None for value in current.values()):
            raise ProblemException(
                status_code=409,
                code="tlf_program_plan_prerequisites_missing",
                title="TLF ProgramPlan prerequisites are missing",
                detail="Author shell, bindings, assumptions, and ARS before ProgramPlan.",
            )
        plan = cast(TlfProgramPlan, command)
        revisions = {
            key: cast(TlfAuthoringRevision, value).revision for key, value in current.items()
        }
        if (
            plan.shell_revision != revisions["shell"]
            or plan.bindings_revision != revisions["bindings"]
            or plan.assumptions_revision != revisions["assumptions"]
            or plan.ars_revision != revisions["ars"]
        ):
            raise ProblemException(
                status_code=409,
                code="tlf_program_plan_misaligned",
                title="TLF ProgramPlan is misaligned",
                detail="ProgramPlan must pin every current TLF authoring revision.",
            )
        lower_analysis_ir(
            cast(TlfShell, content_contract(cast(TlfAuthoringRevision, current["shell"]))),
            cast(TlfBindings, content_contract(cast(TlfAuthoringRevision, current["bindings"]))),
            cast(TlfArs, content_contract(cast(TlfAuthoringRevision, current["ars"]))),
            plan,
        )
    previous = handler.latest_content(session, workbench.id, content_type)
    payload = command.model_dump(mode="json")
    record = TlfAuthoringRevision(
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        content_type=content_type,
        revision=1 if previous is None else previous.revision + 1,
        schema_version=command.schema_version,
        state="current",
        payload=payload,
        fingerprint=fingerprint(payload),
        created_by=principal.subject,
    )
    session.add(record)
    workbench.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return AuthoringResponse.model_validate(record)


@router.get("/tlfs/{tlf_id}/shell", response_model=AuthoringResponse)
def get_shell(
    tlf_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AuthoringResponse:
    return _get_content("shell", tlf_id, response, session, registry, principal)


@router.put("/tlfs/{tlf_id}/shell", response_model=AuthoringResponse)
def put_shell(
    tlf_id: UUID,
    command: TlfShell,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AuthoringResponse:
    return _put_content("shell", command, tlf_id, response, session, registry, principal, if_match)


@router.get("/tlfs/{tlf_id}/bindings", response_model=AuthoringResponse)
def get_bindings(
    tlf_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AuthoringResponse:
    return _get_content("bindings", tlf_id, response, session, registry, principal)


@router.put("/tlfs/{tlf_id}/bindings", response_model=AuthoringResponse)
def put_bindings(
    tlf_id: UUID,
    command: TlfBindings,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AuthoringResponse:
    return _put_content(
        "bindings", command, tlf_id, response, session, registry, principal, if_match
    )


@router.get("/tlfs/{tlf_id}/assumptions", response_model=AuthoringResponse)
def get_assumptions(
    tlf_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AuthoringResponse:
    return _get_content("assumptions", tlf_id, response, session, registry, principal)


@router.put("/tlfs/{tlf_id}/assumptions", response_model=AuthoringResponse)
def put_assumptions(
    tlf_id: UUID,
    command: TlfAssumptions,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AuthoringResponse:
    return _put_content(
        "assumptions", command, tlf_id, response, session, registry, principal, if_match
    )


@router.get("/tlfs/{tlf_id}/ars", response_model=AuthoringResponse)
def get_ars(
    tlf_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AuthoringResponse:
    return _get_content("ars", tlf_id, response, session, registry, principal)


@router.put("/tlfs/{tlf_id}/ars", response_model=AuthoringResponse)
def put_ars(
    tlf_id: UUID,
    command: TlfArs,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AuthoringResponse:
    return _put_content("ars", command, tlf_id, response, session, registry, principal, if_match)


@router.get("/tlfs/{tlf_id}/program-plan", response_model=AuthoringResponse)
def get_program_plan(
    tlf_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AuthoringResponse:
    return _get_content("program_plan", tlf_id, response, session, registry, principal)


@router.put("/tlfs/{tlf_id}/program-plan", response_model=AuthoringResponse)
def put_program_plan(
    tlf_id: UUID,
    command: TlfProgramPlan,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AuthoringResponse:
    return _put_content(
        "program_plan", command, tlf_id, response, session, registry, principal, if_match
    )


def _validate(
    tlf_id: UUID,
    session: Session,
    registry: ModuleRegistry,
    principal: Principal,
) -> ValidationRunResponse:
    workbench = _workbench(session, tlf_id, principal)
    handler = _handler(registry)
    records, internal = handler.validate_authoring(session, workbench.id, workbench.study_id)
    manifest = authoring_manifest(handler, session, workbench.id, records, internal)
    now = utc_now()
    run = ValidationRun(
        study_id=workbench.study_id,
        module_key="tlf",
        owner_type="tlf_workbench",
        owner_id=workbench.id,
        status="succeeded",
        validator_name="tlf-authoring-validator",
        validator_version="1.0.0",
        input_fingerprint=fingerprint(manifest),
        input_manifest=manifest,
        started_at=now,
        completed_at=now,
        error_count=0,
        warning_count=0,
        info_count=0,
        issues=[],
        report_artifact_ids=[],
        created_by=principal.subject,
    )
    session.add(run)
    session.commit()
    return ValidationRunResponse.model_validate(run)


@router.post("/tlfs/{tlf_id}/program-plan/validate", response_model=ValidationRunResponse)
def validate_program_plan(
    tlf_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    return _validate(tlf_id, session, registry, principal)


@router.post("/tlfs/{tlf_id}/validate", response_model=ValidationRunResponse)
def validate_tlf(
    tlf_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    return _validate(tlf_id, session, registry, principal)


@router.post("/tlfs/{tlf_id}/program-plan/preview", response_model=PreviewResponse)
def preview_program_plan(
    tlf_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> PreviewResponse:
    workbench = _workbench(session, tlf_id, principal)
    _, internal = _handler(registry).validate_authoring(session, workbench.id, workbench.study_id)
    canonical = canonical_analysis_ir(internal)
    return PreviewResponse(
        normalized_result_schema=internal.procedures[0].result_schema,
        procedure_count=len(internal.procedures),
        analysis_ir_fingerprint=fingerprint(canonical),
        normalized_analysis_ir=canonical,
    )


def _build(
    workbench: TlfWorkbench,
    artifact_types: tuple[str, ...],
    expected_input_fingerprint: str,
    response: Response,
    session: Session,
    registry: ModuleRegistry,
    principal: Principal,
    idempotency_key: str | None,
) -> ArtifactBuildResponse:
    unsupported = sorted(set(artifact_types) - set(TLF_BUILD_ARTIFACT_TYPES))
    if unsupported:
        raise ProblemException(
            status_code=422,
            code="artifact_type_unsupported",
            title="Artifact type is unsupported",
            detail=f"Unsupported TLF artifact types: {', '.join(unsupported)}",
        )
    return create_artifact_build(
        ArtifactBuildCreate(
            study_id=workbench.study_id,
            owner_type="tlf_workbench",
            owner_id=workbench.id,
            artifact_types=artifact_types,
            expected_input_fingerprint=expected_input_fingerprint,
            options={},
        ),
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/tlfs/{tlf_id}/artifacts",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_tlf_artifacts(
    tlf_id: UUID,
    command: ArtifactRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    return _build(
        _workbench(session, tlf_id, principal),
        command.artifact_types,
        command.expected_input_fingerprint,
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/tlfs/{tlf_id}/compile",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def compile_tlf(
    tlf_id: UUID,
    command: CompileRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    return _build(
        _workbench(session, tlf_id, principal),
        (f"tlf_program_{command.backend}",),
        command.expected_input_fingerprint,
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/tlfs/{tlf_id}/render",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def render_tlf(
    tlf_id: UUID,
    command: RenderRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    workbench = _workbench(session, tlf_id, principal)
    shell_record = _handler(registry).latest_content(session, workbench.id, "shell")
    if shell_record is None:
        raise ProblemException(
            status_code=409,
            code="tlf_shell_required",
            title="TLF shell is required",
            detail="Author shell first.",
        )
    shell = cast(TlfShell, content_contract(shell_record))
    allowed = {
        "table": {"rtf", "pdf"},
        "listing": {"rtf", "pdf"},
        "figure": {"png", "svg", "pdf"},
    }[shell.output_type]
    if command.format not in allowed:
        raise ProblemException(
            status_code=422,
            code="tlf_render_format_invalid",
            title="TLF render format is invalid",
            detail=f"{shell.output_type} outputs support: {', '.join(sorted(allowed))}.",
        )
    artifact_type = f"tlf_{shell.output_type}_{command.format}"
    assert artifact_type in TLF_RENDER_ARTIFACT_TYPES
    return _build(
        workbench,
        (artifact_type,),
        command.expected_input_fingerprint,
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/tlfs/{tlf_id}/execute",
    response_model=ExecutionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def execute_tlf(
    tlf_id: UUID,
    command: TlfExecutionRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExecutionRunResponse:
    workbench = _workbench(session, tlf_id, principal)
    return create_execution_run(
        ExecutionRunCreate(
            study_id=workbench.study_id,
            module="tlf",
            owner_type="tlf_workbench",
            owner_id=workbench.id,
            language=command.language,
            program_artifact_id=command.program_artifact_id,
            input_artifact_ids=command.input_artifact_ids,
            validation_run_id=command.validation_run_id,
            input_selection_revision=command.bindings_revision,
            source_specification_revision=command.shell_revision,
            source_plan_type="tlf_program_plan",
            source_plan_revision=command.program_plan_revision,
            compiler_fingerprint=command.compiler_fingerprint,
            expected_input_fingerprint=command.expected_input_fingerprint,
            limits=command.limits,
        ),
        response,
        session,
        settings,
        principal,
        idempotency_key,
    )
