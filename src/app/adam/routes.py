"""ADaM exact inputs, Specification exchange, plan, preview, and lineage APIs."""

import hashlib
import json
from datetime import datetime
from typing import Annotated, Protocol, cast
from uuid import UUID
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adam.contracts import AdamDerivationPlan, AdamInputSelectionWrite, AdamSpecification
from app.adam.models import (
    AdamDerivationPlanRevision,
    AdamInputSelection,
    AdamSpecificationRevision,
    AdamWorkbench,
)
from app.adam.service import (
    ADAM_BUILD_ARTIFACT_TYPES,
    AdamCapability,
    context_from_record,
    lower_plan,
    plan_from_record,
    validate_dependency_compatibility,
    validate_origins,
    validate_sdtm_sources,
)
from app.adam.specification_workbook import (
    parse_specification_xlsx,
    render_specification_xlsx,
)
from app.api.auth import Principal, get_principal
from app.api.dependencies import (
    get_application_settings,
    get_module_registry,
    get_object_storage,
    get_session,
)
from app.artifacts.builds import ArtifactBuildCreate, ArtifactBuildResponse, create_artifact_build
from app.artifacts.models import Artifact
from app.artifacts.service import ArtifactService
from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.idempotency import IdempotencyRecord
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
from app.kernel.traceability import (
    TraceabilityError,
    TraceabilityService,
    TraceCommand,
    TraceEndpoint,
)
from app.studies.service import StudyService
from app.transformation.evaluator import evaluate_dataflow
from app.transformation.service import canonical_ir, ir_fingerprint, lineage
from app.validation.models import ValidationRun
from app.validation.routes import ValidationRunResponse

router = APIRouter(tags=["adam"])
studies = StudyService()
artifacts = ArtifactService()
traceability = TraceabilityService()


class SdtmContextExporter(Protocol):
    def context_snapshot(
        self, session: Session, sdtm_id: UUID, study_id: UUID
    ) -> dict[str, object]: ...

    def read_context_dataset(
        self,
        session: Session,
        storage: ObjectStorage,
        *,
        sdtm_id: UUID,
        study_id: UUID,
        dataset_code: str,
        artifact_id: UUID,
        expected_checksum: str,
        maximum_rows: int = 10_000,
    ) -> tuple[dict[str, object | None], ...]: ...


class InputSelectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    revision: int
    state: str
    payload: dict[str, object]
    fingerprint: str


class SpecificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    aggregate_id: UUID
    revision: int
    schema_version: str
    payload: dict[str, object]
    fingerprint: str
    created_by: str
    created_at: datetime


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    aggregate_id: UUID
    revision: int
    schema_version: str
    specification_revision: int
    input_selection_revision: int
    state: str
    payload: dict[str, object]
    fingerprint: str
    created_by: str
    created_at: datetime


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datasets: tuple[str, ...] = ()
    limit: int = Field(default=100, ge=1, le=200)


class AdamArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_types: tuple[str, ...] = Field(min_length=1)
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: str = Field(pattern=r"^(python|r|sas)$")
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class AdamExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str = Field(pattern=r"^(python|r|sas)$")
    program_artifact_id: UUID
    input_artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    validation_run_id: UUID
    input_selection_revision: int = Field(ge=1)
    source_specification_revision: int = Field(ge=1)
    source_plan_revision: int = Field(ge=1)
    compiler_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    limits: ExecutionLimits


def _handler(registry: ModuleRegistry) -> AdamCapability:
    return cast(AdamCapability, registry.require_handler("adam", ModuleCapability.DEPENDENCIES))


def _adam(session: Session, adam_id: UUID, principal: Principal) -> AdamWorkbench:
    workbench = session.get(AdamWorkbench, adam_id)
    if workbench is None:
        raise ProblemException(
            status_code=404,
            code="adam_not_found",
            title="ADaM workbench not found",
            detail="The ADaM workbench does not exist.",
        )
    studies.require_access(session, workbench.study_id, principal)
    return workbench


def _stale(field: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=409,
        code=f"adam_{field}_stale",
        title="ADaM input is stale",
        detail=detail,
    )


def _missing(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=409,
        code=code,
        title="ADaM authoring is incomplete",
        detail=detail,
    )


def _selection_command(selection: AdamInputSelection) -> AdamInputSelectionWrite:
    payload = {
        key: value for key, value in selection.payload.items() if key != "sdtm_context_fingerprint"
    }
    return AdamInputSelectionWrite.model_validate(payload)


def _sdtm_context(
    session: Session,
    registry: ModuleRegistry,
    command: AdamInputSelectionWrite,
    study_id: UUID,
    adam_id: UUID,
) -> dict[str, object]:
    provider = cast(
        SdtmContextExporter,
        registry.require_handler("sdtm", ModuleCapability.CONTEXT_EXPORT),
    )
    context = provider.context_snapshot(session, command.sdtm_id, study_id)
    validate_dependency_compatibility(
        _handler(registry).get_selection(session, adam_id, study_id),
        context,
    )
    if context["sdtm_revision"] != command.sdtm_revision:
        raise _stale("sdtm_revision", "The selected SDTM revision is no longer current.")
    if context["dependency_fingerprint"] != command.sdtm_dependency_fingerprint:
        raise _stale("sdtm_dependency_fingerprint", "The SDTM dependency selection has changed.")
    eligible = {
        (str(item["artifact_id"]), str(item["dataset_code"]), str(item["checksum"])): item
        for item in cast(list[dict[str, object]], context["xpt_artifacts"])
    }
    selected_rows: list[dict[str, object]] = []
    for selected in command.xpt_artifacts:
        key = (str(selected.artifact_id), selected.dataset_code, selected.checksum)
        candidate = eligible.get(key)
        artifact = session.get(Artifact, selected.artifact_id)
        if (
            candidate is None
            or artifact is None
            or artifact.study_id != study_id
            or artifact.module_key != "sdtm"
            or artifact.artifact_type != "sdtm_dataset_xpt"
            or artifact.status != "available"
            or artifact.sha256 != selected.checksum
        ):
            raise ProblemException(
                status_code=422,
                code="adam_sdtm_artifact_invalid",
                title="ADaM SDTM input is invalid",
                detail="Every XPT must match the exact current SDTM context.",
            )
        selected_rows.append(candidate)
    selected_context = {**context, "xpt_artifacts": selected_rows}
    validation = session.get(ValidationRun, command.validation_run_id)
    manifest = validation.input_manifest if validation is not None else {}
    if (
        validation is None
        or validation.study_id != study_id
        or validation.module_key != "sdtm"
        or validation.owner_type != "sdtm_workbench"
        or validation.owner_id != command.sdtm_id
        or validation.status != "succeeded"
        or validation.error_count != 0
        or manifest.get("sdtm_revision") != command.sdtm_revision
        or manifest.get("dependency_fingerprint") != command.sdtm_dependency_fingerprint
        or manifest.get("input_selection_revision") != context["input_selection_revision"]
        or manifest.get("specification_revision") != context["specification_revision"]
        or manifest.get("plan_revision") != context["plan_revision"]
    ):
        raise ProblemException(
            status_code=422,
            code="adam_sdtm_validation_invalid",
            title="ADaM SDTM validation is invalid",
            detail="Select a successful validation snapshot for the exact SDTM revisions.",
        )
    return {
        **selected_context,
        "validation_run": {
            "id": str(validation.id),
            "input_fingerprint": validation.input_fingerprint,
            "status": validation.status,
            "error_count": validation.error_count,
            "warning_count": validation.warning_count,
        },
    }


@router.get("/adams/{adam_id}/input-selection", response_model=InputSelectionResponse)
def get_input_selection(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> InputSelectionResponse:
    workbench = _adam(session, adam_id, principal)
    return InputSelectionResponse.model_validate(
        _handler(registry).current_input(session, workbench.id)
    )


@router.put("/adams/{adam_id}/input-selection", response_model=InputSelectionResponse)
def put_input_selection(
    adam_id: UUID,
    command: AdamInputSelectionWrite,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> InputSelectionResponse:
    workbench = _adam(session, adam_id, principal)
    require_matching_etag(if_match, workbench.revision)
    context = _sdtm_context(session, registry, command, workbench.study_id, workbench.id)
    payload = command.model_dump(mode="json")
    payload["sdtm_context_fingerprint"] = fingerprint(context)
    record = session.scalar(
        select(AdamInputSelection).where(AdamInputSelection.aggregate_id == workbench.id)
    )
    if record is None:
        record = AdamInputSelection(
            aggregate_id=workbench.id,
            study_id=workbench.study_id,
            revision=1,
            state="current",
            payload=payload,
            fingerprint=fingerprint(payload),
        )
        session.add(record)
    else:
        record.revision += 1
        record.state = "current"
        record.payload = payload
        record.fingerprint = fingerprint(payload)
    plan = _handler(registry).latest_plan(session, workbench.id)
    if plan is not None:
        plan.state = "misaligned"
    workbench.revision += 1
    artifacts.mark_owner_stale(session, owner_type="adam_workbench", owner_id=workbench.id)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return InputSelectionResponse.model_validate(record)


@router.get("/adams/{adam_id}/sdtm-context")
def get_sdtm_context(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    workbench = _adam(session, adam_id, principal)
    selection = _handler(registry).current_input(session, workbench.id)
    return _sdtm_context(
        session,
        registry,
        _selection_command(selection),
        workbench.study_id,
        workbench.id,
    )


@router.get("/adams/{adam_id}/specification", response_model=SpecificationResponse)
def get_specification(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> SpecificationResponse:
    workbench = _adam(session, adam_id, principal)
    record = _handler(registry).latest_specification(session, workbench.id)
    if record is None:
        raise _missing("adam_specification_required", "ADaM Specification is not saved.")
    return SpecificationResponse.model_validate(record)


def _save_specification(
    session: Session,
    registry: ModuleRegistry,
    workbench: AdamWorkbench,
    command: AdamSpecification,
    principal: Principal,
) -> AdamSpecificationRevision:
    handler = _handler(registry)
    current = handler.latest_specification(session, workbench.id)
    previous_specification = context_from_record(current) if current is not None else None
    record = AdamSpecificationRevision(
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        revision=1 if current is None else current.revision + 1,
        schema_version=command.schema_version,
        payload=command.model_dump(mode="json"),
        fingerprint=fingerprint(command.model_dump(mode="json")),
        created_by=principal.subject,
    )
    session.add(record)
    session.flush()
    try:
        traceability.replace(
            session,
            registry,
            workbench.study_id,
            _trace_commands(previous_specification),
            _trace_commands(command),
            principal.subject,
        )
    except TraceabilityError as error:
        raise ProblemException(
            status_code=422,
            code=error.code,
            title="ADaM trace target is invalid",
            detail=error.detail,
        ) from error
    plan = handler.latest_plan(session, workbench.id)
    if plan is not None:
        plan.state = "misaligned"
    workbench.revision += 1
    artifacts.mark_owner_stale(session, owner_type="adam_workbench", owner_id=workbench.id)
    return record


def _trace_commands(specification: AdamSpecification | None) -> tuple[TraceCommand, ...]:
    if specification is None:
        return ()
    return tuple(
        TraceCommand(
            relationship_type=item.relationship_type,
            source=TraceEndpoint(
                module=item.source.module,
                entity_type=item.source.entity_type,
                entity_id=item.source.entity_id,
            ),
            target=TraceEndpoint(
                module=item.target.module,
                entity_type=item.target.entity_type,
                entity_id=item.target.entity_id,
            ),
        )
        for item in specification.trace_targets
    )


@router.put("/adams/{adam_id}/specification", response_model=SpecificationResponse)
def put_specification(
    adam_id: UUID,
    command: AdamSpecification,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SpecificationResponse:
    workbench = _adam(session, adam_id, principal)
    require_matching_etag(if_match, workbench.revision)
    record = _save_specification(session, registry, workbench, command, principal)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return SpecificationResponse.model_validate(record)


@router.post("/adams/{adam_id}/specification/import", response_model=SpecificationResponse)
async def import_specification(
    adam_id: UUID,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SpecificationResponse:
    workbench = _adam(session, adam_id, principal)
    data = await request.body()
    request_fingerprint = hashlib.sha256(data).hexdigest()
    route = f"adams:{workbench.id}:specification-import"
    if not idempotency_key:
        raise ProblemException(
            status_code=400,
            code="idempotency_key_required",
            title="Idempotency-Key is required",
            detail="Supply an Idempotency-Key header for an atomic import.",
        )
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.subject == principal.subject,
            IdempotencyRecord.route == route,
            IdempotencyRecord.study_id == workbench.study_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise ProblemException(
                status_code=409,
                code="idempotency_key_reused",
                title="Idempotency key was reused",
                detail="The key is already bound to different import bytes.",
            )
        record = session.get(AdamSpecificationRevision, existing.resource_id)
        if record is None:
            raise RuntimeError("idempotency record references a missing ADaM Specification")
        response.headers["ETag"] = etag_for_revision(workbench.revision)
        return SpecificationResponse.model_validate(record)
    require_matching_etag(if_match, workbench.revision)
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            command = AdamSpecification.model_validate(json.loads(data))
        else:
            command = parse_specification_xlsx(data)
    except (BadZipFile, InvalidFileException, ValidationError, ValueError) as error:
        raise ProblemException(
            status_code=422,
            code="adam_specification_import_invalid",
            title="ADaM Specification import is invalid",
            detail=str(error),
        ) from error
    record = _save_specification(session, registry, workbench, command, principal)
    session.flush()
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route=route,
            study_id=workbench.study_id,
            key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_type="adam_specification_revision",
            resource_id=record.id,
        )
    )
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return SpecificationResponse.model_validate(record)


@router.get("/adams/{adam_id}/specification/export", operation_id="export_adam_specification")
def export_specification(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    export_format: Annotated[str, Query(alias="format", pattern=r"^(json|xlsx)$")] = "json",
) -> Response:
    record = get_specification(adam_id, session, registry, principal)
    if export_format == "json":
        return JSONResponse(content=record.payload)
    specification = AdamSpecification.model_validate(record.payload)
    return Response(
        render_specification_xlsx(specification),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="adam-specification.xlsx"'},
    )


@router.get("/adams/{adam_id}/derivation-plan", response_model=PlanResponse)
def get_plan(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> PlanResponse:
    workbench = _adam(session, adam_id, principal)
    record = _handler(registry).latest_plan(session, workbench.id)
    if record is None:
        raise _missing("adam_derivation_plan_required", "ADaM Derivation Plan is not saved.")
    return PlanResponse.model_validate(record)


@router.put("/adams/{adam_id}/derivation-plan", response_model=PlanResponse)
def put_plan(
    adam_id: UUID,
    command: AdamDerivationPlan,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> PlanResponse:
    workbench = _adam(session, adam_id, principal)
    require_matching_etag(if_match, workbench.revision)
    handler = _handler(registry)
    specification = handler.latest_specification(session, workbench.id)
    selection = handler.current_input(session, workbench.id)
    if (
        specification is None
        or selection.state != "current"
        or command.specification_revision != specification.revision
        or command.input_selection_revision != selection.revision
    ):
        raise _stale("plan_alignment", "Plan revisions do not match current inputs.")
    context = _sdtm_context(
        session,
        registry,
        _selection_command(selection),
        workbench.study_id,
        workbench.id,
    )
    validate_sdtm_sources(command, context)
    specification_contract = context_from_record(specification)
    validate_origins(specification_contract, context)
    lower_plan(specification_contract, command)
    current = handler.latest_plan(session, workbench.id)
    record = AdamDerivationPlanRevision(
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        revision=1 if current is None else current.revision + 1,
        schema_version=command.schema_version,
        specification_revision=command.specification_revision,
        input_selection_revision=command.input_selection_revision,
        state="aligned",
        payload=command.model_dump(mode="json"),
        fingerprint=fingerprint(command.model_dump(mode="json")),
        created_by=principal.subject,
    )
    session.add(record)
    workbench.revision += 1
    artifacts.mark_owner_stale(session, owner_type="adam_workbench", owner_id=workbench.id)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return PlanResponse.model_validate(record)


@router.post("/adams/{adam_id}/derivation-plan/validate", operation_id="validate_adam_plan")
def validate_plan(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    workbench = _adam(session, adam_id, principal)
    specification, selection, plan = _handler(registry).require_aligned(session, workbench.id)
    context = _sdtm_context(
        session,
        registry,
        _selection_command(selection),
        workbench.study_id,
        workbench.id,
    )
    plan_contract = plan_from_record(plan)
    validate_sdtm_sources(plan_contract, context)
    specification_contract = context_from_record(specification)
    validate_origins(specification_contract, context)
    internal = lower_plan(specification_contract, plan_contract)
    return {
        "status": "valid",
        "input_selection_revision": selection.revision,
        "specification_revision": specification.revision,
        "plan_revision": plan.revision,
        "ir_fingerprint": ir_fingerprint(internal),
        "issues": [],
    }


@router.post("/adams/{adam_id}/derivation-plan/preview", operation_id="preview_adam_plan")
def preview_plan(
    adam_id: UUID,
    command: PreviewRequest,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    """Evaluate the aligned plan over exact selected SDTM XPTs with bounded rows."""

    workbench = _adam(session, adam_id, principal)
    specification, selection, plan = _handler(registry).require_aligned(session, workbench.id)
    context = _sdtm_context(
        session,
        registry,
        _selection_command(selection),
        workbench.study_id,
        workbench.id,
    )
    plan_contract = plan_from_record(plan)
    validate_sdtm_sources(plan_contract, context)
    specification_contract = context_from_record(specification)
    validate_origins(specification_contract, context)
    internal = lower_plan(specification_contract, plan_contract)
    provider = cast(
        SdtmContextExporter,
        registry.require_handler("sdtm", ModuleCapability.CONTEXT_EXPORT),
    )
    selected = {
        str(item["dataset_code"]): item
        for item in cast(list[dict[str, object]], context["xpt_artifacts"])
    }
    required = {node.dataset for node in plan_contract.nodes if node.node_type == "sdtm_read"}
    datasets = {
        code: provider.read_context_dataset(
            session,
            storage,
            sdtm_id=UUID(str(context["sdtm_id"])),
            study_id=workbench.study_id,
            dataset_code=code,
            artifact_id=UUID(str(selected[code]["artifact_id"])),
            expected_checksum=str(selected[code]["checksum"]),
        )
        for code in required
    }
    outputs = evaluate_dataflow(internal, datasets, row_limit=command.limit)
    unknown = sorted(set(command.datasets) - set(outputs))
    if unknown:
        raise ProblemException(
            status_code=422,
            code="adam_preview_dataset_unknown",
            title="ADaM preview dataset is unknown",
            detail=f"The plan did not produce: {', '.join(unknown)}.",
        )
    requested = command.datasets or tuple(outputs)
    return {
        "schema_version": "1.0.0",
        "ir_fingerprint": ir_fingerprint(internal),
        "input_selection_revision": selection.revision,
        "specification_revision": specification.revision,
        "plan_revision": plan.revision,
        "limit": command.limit,
        "outputs": {name: outputs[name] for name in requested},
    }


@router.get("/adams/{adam_id}/lineage", operation_id="get_adam_lineage")
def get_lineage(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    workbench = _adam(session, adam_id, principal)
    specification, selection, plan = _handler(registry).require_aligned(session, workbench.id)
    context = _sdtm_context(
        session,
        registry,
        _selection_command(selection),
        workbench.study_id,
        workbench.id,
    )
    plan_contract = plan_from_record(plan)
    validate_sdtm_sources(plan_contract, context)
    specification_contract = context_from_record(specification)
    validate_origins(specification_contract, context)
    internal = lower_plan(specification_contract, plan_contract)
    return {"ir_fingerprint": ir_fingerprint(internal), "outputs": lineage(internal)}


@router.post("/adams/{adam_id}/validate", response_model=ValidationRunResponse)
def validate_adam(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    """Snapshot validation of the exact aligned ADaM authoring inputs."""

    workbench = _adam(session, adam_id, principal)
    specification, selection, plan = _handler(registry).require_aligned(session, workbench.id)
    context = _sdtm_context(
        session,
        registry,
        _selection_command(selection),
        workbench.study_id,
        workbench.id,
    )
    specification_contract = context_from_record(specification)
    plan_contract = plan_from_record(plan)
    validate_sdtm_sources(plan_contract, context)
    validate_origins(specification_contract, context)
    internal = lower_plan(specification_contract, plan_contract)
    manifest = {
        "adam_revision": workbench.revision,
        "dependency_fingerprint": _handler(registry)
        .get_selection(session, workbench.id, workbench.study_id)
        .fingerprint,
        "input_selection_revision": selection.revision,
        "input_selection_fingerprint": selection.fingerprint,
        "specification_revision": specification.revision,
        "specification_fingerprint": specification.fingerprint,
        "plan_revision": plan.revision,
        "plan_fingerprint": plan.fingerprint,
        "sdtm_context_fingerprint": fingerprint(context),
        "selected_xpt_artifacts": [
            {
                "artifact_id": str(item["artifact_id"]),
                "dataset_code": str(item["dataset_code"]),
                "checksum": str(item["checksum"]),
            }
            for item in cast(list[dict[str, object]], context["xpt_artifacts"])
        ],
        "normalized_ir": canonical_ir(internal),
    }
    now = utc_now()
    run = ValidationRun(
        study_id=workbench.study_id,
        module_key="adam",
        owner_type="adam_workbench",
        owner_id=workbench.id,
        status="succeeded",
        validator_name="adam-authoring-validator",
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


def _build(
    workbench: AdamWorkbench,
    artifact_types: tuple[str, ...],
    expected_input_fingerprint: str,
    response: Response,
    session: Session,
    registry: ModuleRegistry,
    principal: Principal,
    idempotency_key: str | None,
) -> ArtifactBuildResponse:
    unsupported = sorted(set(artifact_types) - set(ADAM_BUILD_ARTIFACT_TYPES))
    if unsupported:
        raise ProblemException(
            status_code=422,
            code="artifact_type_unsupported",
            title="Artifact type is unsupported",
            detail=f"Unsupported ADaM artifact types: {', '.join(unsupported)}",
        )
    return create_artifact_build(
        ArtifactBuildCreate(
            study_id=workbench.study_id,
            owner_type="adam_workbench",
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
    "/adams/{adam_id}/artifacts",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_adam_artifacts(
    adam_id: UUID,
    command: AdamArtifactRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    workbench = _adam(session, adam_id, principal)
    return _build(
        workbench,
        command.artifact_types,
        command.expected_input_fingerprint,
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/adams/{adam_id}/compile",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def compile_adam(
    adam_id: UUID,
    command: CompileRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    workbench = _adam(session, adam_id, principal)
    return _build(
        workbench,
        (f"adam_program_{command.backend}",),
        command.expected_input_fingerprint,
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/adams/{adam_id}/execute",
    response_model=ExecutionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def execute_adam(
    adam_id: UUID,
    command: AdamExecutionRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExecutionRunResponse:
    """Submit exact ADaM execution through the shared isolated run service."""

    workbench = _adam(session, adam_id, principal)
    return create_execution_run(
        ExecutionRunCreate(
            study_id=workbench.study_id,
            module="adam",
            owner_type="adam_workbench",
            owner_id=workbench.id,
            language=command.language,
            program_artifact_id=command.program_artifact_id,
            input_artifact_ids=command.input_artifact_ids,
            validation_run_id=command.validation_run_id,
            input_selection_revision=command.input_selection_revision,
            source_specification_revision=command.source_specification_revision,
            source_plan_type="adam_derivation_plan",
            source_plan_revision=command.source_plan_revision,
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
