"""TLF authoring, validation, compilation, execution, and rendering APIs."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
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
from app.kernel.context import DocumentContextExporter
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry
from app.studies.service import StudyService
from app.tlf.contracts import (
    TlfArs,
    TlfAssumptions,
    TlfBindings,
    TlfInputSelectionWrite,
    TlfInventoryOutput,
    TlfOutputInventory,
    TlfProgramPlan,
    TlfShell,
)
from app.tlf.models import (
    TlfAuthoringRevision,
    TlfDependencySelection,
    TlfInputSelection,
    TlfWorkbench,
)
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


class TlfInputSelectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    aggregate_id: UUID
    study_id: UUID
    revision: int
    state: str
    payload: dict[str, object]
    fingerprint: str


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
    output_code: str = Field(pattern=r"^[A-Z][A-Z0-9-]{1,31}$")


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: str = Field(pattern=r"^(python|r|sas)$")
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_code: str = Field(pattern=r"^[A-Z][A-Z0-9-]{1,31}$")


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: str = Field(pattern=r"^(rtf|pdf|png|svg)$")
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_code: str = Field(pattern=r"^[A-Z][A-Z0-9-]{1,31}$")


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
    output_code: str = Field(pattern=r"^[A-Z][A-Z0-9-]{1,31}$")


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


@router.get("/tlf-workbenches/{tlf_id}/input-selection", response_model=TlfInputSelectionResponse)
def get_input_selection(
    tlf_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> TlfInputSelectionResponse:
    workbench = _workbench(session, tlf_id, principal)
    record = session.scalar(
        select(TlfInputSelection).where(TlfInputSelection.aggregate_id == workbench.id)
    )
    if record is None:
        raise ProblemException(
            status_code=404,
            code="tlf_input_selection_not_found",
            title="TLF input selection not found",
            detail="Select exact source documents and ADaM artifacts first.",
        )
    return TlfInputSelectionResponse.model_validate(record)


@router.put("/tlf-workbenches/{tlf_id}/input-selection", response_model=TlfInputSelectionResponse)
def put_input_selection(
    tlf_id: UUID,
    command: TlfInputSelectionWrite,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> TlfInputSelectionResponse:
    workbench = _workbench(session, tlf_id, principal)
    require_matching_etag(if_match, workbench.revision)
    document_exporter = cast(
        DocumentContextExporter,
        registry.require_handler("documents", ModuleCapability.CONTEXT_EXPORT),
    )
    for selected in command.documents:
        document = document_exporter.content_context(
            session,
            workbench.study_id,
            selected.content_id,
            expected_document_type=selected.document_type,
            expected_fingerprint=selected.fingerprint,
        )
        if document is None:
            raise ProblemException(
                status_code=422,
                code="tlf_source_document_invalid",
                title="TLF source document is invalid",
                detail="Every source document must resolve to exact same-study content.",
            )
    _handler(registry).validate_input_datasets(session, workbench.study_id, command.datasets)
    current = session.scalar(
        select(TlfInputSelection).where(TlfInputSelection.aggregate_id == workbench.id)
    )
    payload = command.model_dump(mode="json")
    if current is None:
        current = TlfInputSelection(
            aggregate_id=workbench.id,
            study_id=workbench.study_id,
            revision=1,
            state="current",
            payload=payload,
            fingerprint=fingerprint(payload),
        )
        session.add(current)
    else:
        current.revision += 1
        current.state = "current"
        current.payload = payload
        current.fingerprint = fingerprint(payload)
    for authored in session.scalars(
        select(TlfAuthoringRevision).where(
            TlfAuthoringRevision.aggregate_id == workbench.id,
            TlfAuthoringRevision.state == "current",
        )
    ):
        authored.state = "misaligned"
    workbench.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return TlfInputSelectionResponse.model_validate(current)


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


def _manual_authoring_prerequisites(
    session: Session, workbench: TlfWorkbench
) -> TlfInputSelection:
    dependency = session.scalar(
        select(TlfDependencySelection).where(
            TlfDependencySelection.aggregate_id == workbench.id
        )
    )
    selection = session.scalar(
        select(TlfInputSelection).where(TlfInputSelection.aggregate_id == workbench.id)
    )
    if dependency is None or dependency.state != "current":
        raise ProblemException(
            status_code=409,
            code="tlf_dependencies_required",
            title="TLF dependencies are required",
            detail="Select exact compatible dependencies before authoring TLF content.",
        )
    if selection is None or selection.state != "current":
        raise ProblemException(
            status_code=409,
            code="tlf_input_selection_required",
            title="TLF input selection is required",
            detail="Select exact SAP and ADaM evidence before authoring TLF content.",
        )
    return selection


def _inventory_output(
    handler: TlfCapability,
    session: Session,
    workbench: TlfWorkbench,
    output_code: str,
) -> TlfInventoryOutput:
    record = handler.latest_content(session, workbench.id, "inventory")
    if record is None or record.state != "current":
        raise ProblemException(
            status_code=409,
            code="tlf_inventory_required",
            title="Current TLF inventory is required",
            detail="Create or refresh the output inventory first.",
        )
    inventory = TlfOutputInventory.model_validate(record.payload)
    output = next((item for item in inventory.outputs if item.output_code == output_code), None)
    if output is None:
        raise ProblemException(
            status_code=404,
            code="tlf_output_unknown",
            title="TLF output is unknown",
            detail=f"Output '{output_code}' is not declared in the current inventory.",
        )
    return output


def _mark_manual_dependents_misaligned(
    session: Session,
    aggregate_id: UUID,
    *,
    inventory_changed: bool,
    output_code: str | None = None,
) -> None:
    records = session.scalars(
        select(TlfAuthoringRevision).where(
            TlfAuthoringRevision.aggregate_id == aggregate_id,
            TlfAuthoringRevision.state == "current",
        )
    )
    for record in records:
        inventory_dependent = inventory_changed and record.content_type != "inventory"
        output_plan = (
            output_code is not None
            and record.content_type == f"program_plan:{output_code}"
        )
        if inventory_dependent or output_plan:
            record.state = "misaligned"


def _save_manual_content(
    *,
    content_type: str,
    model: BaseModel,
    tlf_id: UUID,
    response: Response,
    session: Session,
    registry: ModuleRegistry,
    principal: Principal,
    if_match: str | None,
) -> AuthoringResponse:
    workbench = _workbench(session, tlf_id, principal)
    require_matching_etag(if_match, workbench.revision)
    selection_record = _manual_authoring_prerequisites(session, workbench)
    selection = TlfInputSelectionWrite.model_validate(selection_record.payload)
    handler = _handler(registry)
    output_code: str | None = None
    kind = content_type

    if content_type != "inventory":
        kind, output_code = content_type.split(":", 1)
        output = _inventory_output(handler, session, workbench, output_code)
        if isinstance(model, TlfShell) and (
            model.output_code != output_code
            or model.output_type != output.output_type
            or model.title != output.title
        ):
            raise ProblemException(
                status_code=422,
                code="tlf_shell_inventory_mismatch",
                title="TLF shell does not match the inventory",
                detail="The output code, type, and title must match the current inventory.",
            )
        if isinstance(model, TlfBindings):
            expected = [item.model_dump(mode="json") for item in selection.datasets]
            actual = [item.model_dump(mode="json") for item in model.datasets]
            if actual != expected:
                raise ProblemException(
                    status_code=422,
                    code="tlf_binding_selection_mismatch",
                    title="TLF bindings do not match selected ADaM evidence",
                    detail="Bindings must preserve the exact current ADaM input selection.",
                )
            handler.validate_bindings(session, workbench.study_id, model)
        if isinstance(model, TlfArs):
            shell_record = handler.latest_content(session, workbench.id, f"shell:{output_code}")
            bindings_record = handler.latest_content(
                session, workbench.id, f"bindings:{output_code}"
            )
            if shell_record is None or bindings_record is None:
                raise ProblemException(
                    status_code=409,
                    code="tlf_analysis_prerequisites_required",
                    title="TLF analysis prerequisites are required",
                    detail="Save the shell and bindings before authoring ARS.",
                )
            shell = TlfShell.model_validate(shell_record.payload)
            bindings = TlfBindings.model_validate(bindings_record.payload)
            leaves = {item.id for item in shell.rows if item.leaf}
            if {item.leaf_row_id for item in model.analyses} != leaves:
                raise ProblemException(
                    status_code=422,
                    code="tlf_leaf_coverage_invalid",
                    title="TLF shell leaf coverage is invalid",
                    detail="ARS must cover every shell leaf exactly once.",
                )
            named = {item.id: item.kind for item in bindings.named}
            datasets = {item.id for item in bindings.datasets}
            for analysis in model.analyses:
                valid_parameter = (
                    analysis.parameter_binding_id is None
                    or named.get(analysis.parameter_binding_id) == "parameter"
                )
                if (
                    analysis.dataset_binding_id not in datasets
                    or named.get(analysis.population_binding_id) != "population"
                    or named.get(analysis.statistic_binding_id) != "statistic"
                    or not valid_parameter
                ):
                    raise ProblemException(
                        status_code=422,
                        code="tlf_ars_binding_invalid",
                        title="TLF ARS binding is invalid",
                        detail="Every ARS reference must resolve to a compatible named binding.",
                    )
        if isinstance(model, TlfProgramPlan):
            records = handler.current_authoring_without_plan(
                session, workbench.id, output_code
            )
            if (
                model.shell_revision != records["shell"].revision
                or model.bindings_revision != records["bindings"].revision
                or model.assumptions_revision != records["assumptions"].revision
                or model.ars_revision != records["ars"].revision
            ):
                raise ProblemException(
                    status_code=409,
                    code="tlf_program_plan_misaligned",
                    title="TLF ProgramPlan is misaligned",
                    detail=(
                        "ProgramPlan must pin the current shell, bindings, assumptions, "
                        "and ARS revisions."
                    ),
                )
            lower_analysis_ir(
                TlfShell.model_validate(records["shell"].payload),
                TlfBindings.model_validate(records["bindings"].payload),
                TlfArs.model_validate(records["ars"].payload),
                model,
            )

    record = handler.save_content(
        session,
        workbench,
        content_type,
        model,
        created_by=principal.subject,
    )
    _mark_manual_dependents_misaligned(
        session,
        workbench.id,
        inventory_changed=content_type == "inventory",
        output_code=output_code if kind != "program_plan" else None,
    )
    workbench.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return AuthoringResponse.model_validate(record)


@router.get("/tlf-workbenches/{tlf_id}/inventory", response_model=AuthoringResponse)
def get_inventory(
    tlf_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AuthoringResponse:
    return _get_content("inventory", tlf_id, response, session, registry, principal)


@router.put("/tlf-workbenches/{tlf_id}/inventory", response_model=AuthoringResponse)
def put_inventory(
    tlf_id: UUID,
    command: TlfOutputInventory,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AuthoringResponse:
    return _save_manual_content(
        content_type="inventory",
        model=command,
        tlf_id=tlf_id,
        response=response,
        session=session,
        registry=registry,
        principal=principal,
        if_match=if_match,
    )


@router.get(
    "/tlf-workbenches/{tlf_id}/outputs/{output_code}/shell",
    response_model=AuthoringResponse,
)
def get_shell(
    tlf_id: UUID,
    output_code: str,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AuthoringResponse:
    return _get_content(
        f"shell:{output_code.upper()}", tlf_id, response, session, registry, principal
    )


@router.put(
    "/tlf-workbenches/{tlf_id}/outputs/{output_code}/shell",
    response_model=AuthoringResponse,
)
def put_shell(
    tlf_id: UUID,
    output_code: str,
    command: TlfShell,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AuthoringResponse:
    return _save_manual_content(
        content_type=f"shell:{output_code.upper()}",
        model=command,
        tlf_id=tlf_id,
        response=response,
        session=session,
        registry=registry,
        principal=principal,
        if_match=if_match,
    )


@router.get(
    "/tlf-workbenches/{tlf_id}/outputs/{output_code}/bindings",
    response_model=AuthoringResponse,
)
def get_bindings(
    tlf_id: UUID,
    output_code: str,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AuthoringResponse:
    return _get_content(
        f"bindings:{output_code.upper()}", tlf_id, response, session, registry, principal
    )


@router.put(
    "/tlf-workbenches/{tlf_id}/outputs/{output_code}/bindings",
    response_model=AuthoringResponse,
)
def put_bindings(
    tlf_id: UUID,
    output_code: str,
    command: TlfBindings,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AuthoringResponse:
    return _save_manual_content(
        content_type=f"bindings:{output_code.upper()}",
        model=command,
        tlf_id=tlf_id,
        response=response,
        session=session,
        registry=registry,
        principal=principal,
        if_match=if_match,
    )


@router.get(
    "/tlf-workbenches/{tlf_id}/outputs/{output_code}/assumptions",
    response_model=AuthoringResponse,
)
def get_assumptions(
    tlf_id: UUID,
    output_code: str,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AuthoringResponse:
    return _get_content(
        f"assumptions:{output_code.upper()}", tlf_id, response, session, registry, principal
    )


@router.put(
    "/tlf-workbenches/{tlf_id}/outputs/{output_code}/assumptions",
    response_model=AuthoringResponse,
)
def put_assumptions(
    tlf_id: UUID,
    output_code: str,
    command: TlfAssumptions,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AuthoringResponse:
    return _save_manual_content(
        content_type=f"assumptions:{output_code.upper()}",
        model=command,
        tlf_id=tlf_id,
        response=response,
        session=session,
        registry=registry,
        principal=principal,
        if_match=if_match,
    )


@router.get(
    "/tlf-workbenches/{tlf_id}/outputs/{output_code}/ars",
    response_model=AuthoringResponse,
)
def get_ars(
    tlf_id: UUID,
    output_code: str,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AuthoringResponse:
    return _get_content(
        f"ars:{output_code.upper()}", tlf_id, response, session, registry, principal
    )


@router.put(
    "/tlf-workbenches/{tlf_id}/outputs/{output_code}/ars",
    response_model=AuthoringResponse,
)
def put_ars(
    tlf_id: UUID,
    output_code: str,
    command: TlfArs,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AuthoringResponse:
    return _save_manual_content(
        content_type=f"ars:{output_code.upper()}",
        model=command,
        tlf_id=tlf_id,
        response=response,
        session=session,
        registry=registry,
        principal=principal,
        if_match=if_match,
    )


@router.get(
    "/tlf-workbenches/{tlf_id}/outputs/{output_code}/program-plan",
    response_model=AuthoringResponse,
)
def get_program_plan(
    tlf_id: UUID,
    output_code: str,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AuthoringResponse:
    return _get_content(
        f"program_plan:{output_code.upper()}",
        tlf_id,
        response,
        session,
        registry,
        principal,
    )


@router.put(
    "/tlf-workbenches/{tlf_id}/outputs/{output_code}/program-plan",
    response_model=AuthoringResponse,
)
def put_program_plan(
    tlf_id: UUID,
    output_code: str,
    command: TlfProgramPlan,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AuthoringResponse:
    return _save_manual_content(
        content_type=f"program_plan:{output_code.upper()}",
        model=command,
        tlf_id=tlf_id,
        response=response,
        session=session,
        registry=registry,
        principal=principal,
        if_match=if_match,
    )


def _validate(
    tlf_id: UUID,
    output_code: str,
    session: Session,
    registry: ModuleRegistry,
    principal: Principal,
) -> ValidationRunResponse:
    workbench = _workbench(session, tlf_id, principal)
    handler = _handler(registry)
    records, internal = handler.validate_authoring(
        session, workbench.id, workbench.study_id, output_code.upper()
    )
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


@router.post(
    "/tlf-workbenches/{tlf_id}/program-plan:validate", response_model=ValidationRunResponse
)
def validate_program_plan(
    tlf_id: UUID,
    output_code: str,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    return _validate(tlf_id, output_code, session, registry, principal)


@router.post("/tlf-workbenches/{tlf_id}:validate", response_model=ValidationRunResponse)
def validate_tlf(
    tlf_id: UUID,
    output_code: str,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    return _validate(tlf_id, output_code, session, registry, principal)


@router.post("/tlf-workbenches/{tlf_id}/program-plan:preview", response_model=PreviewResponse)
def preview_program_plan(
    tlf_id: UUID,
    output_code: str,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> PreviewResponse:
    workbench = _workbench(session, tlf_id, principal)
    _, internal = _handler(registry).validate_authoring(
        session, workbench.id, workbench.study_id, output_code.upper()
    )
    canonical = canonical_analysis_ir(internal)
    return PreviewResponse(
        normalized_result_schema=internal.procedures[0].result_schema,
        procedure_count=len(internal.procedures),
        analysis_ir_fingerprint=fingerprint(canonical),
        normalized_analysis_ir=canonical,
    )


def _build(
    workbench: TlfWorkbench,
    output_code: str,
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
            options={"domain_code": output_code.upper()},
        ),
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/tlf-workbenches/{tlf_id}/artifacts:build",
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
        command.output_code,
        command.artifact_types,
        command.expected_input_fingerprint,
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/tlf-workbenches/{tlf_id}:compile",
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
        command.output_code,
        (f"tlf_program_{command.backend}",),
        command.expected_input_fingerprint,
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/tlf-workbenches/{tlf_id}:render",
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
    shell_record = _handler(registry).latest_content(
        session, workbench.id, f"shell:{command.output_code}"
    )
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
        command.output_code,
        (artifact_type,),
        command.expected_input_fingerprint,
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/tlf-workbenches/{tlf_id}:execute",
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
