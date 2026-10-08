"""SDTM exact Raw input, atomic Specification, and Derivation Plan APIs."""

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
from app.sdtm.contracts import (
    SdtmDerivationPlan,
    SdtmInputSelectionWrite,
    SdtmSpecification,
)
from app.sdtm.models import (
    SdtmAcrfAnnotation,
    SdtmDerivationPlanRevision,
    SdtmInputSelection,
    SdtmSpecificationRevision,
    SdtmWorkbench,
)
from app.sdtm.service import (
    SDTM_BUILD_ARTIFACT_TYPES,
    SdtmCapability,
    context_from_record,
    lower_plan,
    plan_from_record,
)
from app.sdtm.specification_workbook import (
    parse_specification_xlsx,
    render_specification_xlsx,
)
from app.studies.service import StudyService
from app.transformation.contracts import Expression
from app.transformation.evaluator import evaluate_dataflow
from app.transformation.expression_validation import validate_expressions
from app.transformation.service import canonical_ir, ir_fingerprint, lineage
from app.validation.models import ValidationRun
from app.validation.routes import ValidationRunResponse

router = APIRouter(tags=["sdtm"])
studies = StudyService()
artifacts = ArtifactService()


class ContextExporter(Protocol):
    def context_snapshot(
        self, session: Session, aggregate_id: UUID, study_id: UUID
    ) -> dict[str, object]: ...

    def read_context_dataset(
        self,
        session: Session,
        storage: ObjectStorage,
        *,
        raw_id: UUID,
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


class SdtmArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_types: tuple[str, ...] = Field(min_length=1)
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: str = Field(pattern=r"^(python|r|sas)$")
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domains: tuple[str, ...] = ()
    limit: int = Field(default=100, ge=1, le=200)


class SdtmExecutionRequest(BaseModel):
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


def _handler(registry: ModuleRegistry) -> SdtmCapability:
    return cast(SdtmCapability, registry.require_handler("sdtm", ModuleCapability.DEPENDENCIES))


def _sdtm(session: Session, sdtm_id: UUID, principal: Principal) -> SdtmWorkbench:
    workbench = session.get(SdtmWorkbench, sdtm_id)
    if workbench is None:
        raise ProblemException(
            status_code=404,
            code="sdtm_not_found",
            title="SDTM workbench not found",
            detail="The SDTM workbench does not exist.",
        )
    studies.require_access(session, workbench.study_id, principal)
    return workbench


def _raw_context(
    session: Session, registry: ModuleRegistry, command: SdtmInputSelectionWrite, study_id: UUID
) -> dict[str, object]:
    provider = cast(
        ContextExporter, registry.require_handler("raw", ModuleCapability.CONTEXT_EXPORT)
    )
    context = provider.context_snapshot(session, command.raw_id, study_id)
    if context["raw_revision"] != command.raw_revision:
        raise _stale("raw_revision", "The selected Raw revision is no longer current.")
    if context["dependency_fingerprint"] != command.raw_dependency_fingerprint:
        raise _stale("raw_dependency_fingerprint", "The Raw dependency selection changed.")
    datasets = {
        str(item["code"]): cast(dict[str, object], item["source_file"])
        for item in cast(list[dict[str, object]], context["datasets"])
    }
    for selected in command.source_artifacts:
        source = datasets.get(selected.dataset_code)
        artifact = session.get(Artifact, selected.artifact_id)
        if (
            source is None
            or source["artifact_id"] != str(selected.artifact_id)
            or source["sha256"] != selected.checksum
            or artifact is None
            or artifact.study_id != study_id
            or artifact.sha256 != selected.checksum
            or artifact.status != "available"
        ):
            raise ProblemException(
                status_code=422,
                code="sdtm_raw_artifact_invalid",
                title="SDTM Raw input is invalid",
                detail="Every source artifact must match the exact selected Raw context.",
            )
    return context


def _selection_command(selection: SdtmInputSelection) -> SdtmInputSelectionWrite:
    payload = {
        key: value for key, value in selection.payload.items() if key != "raw_context_fingerprint"
    }
    return SdtmInputSelectionWrite.model_validate(payload)


@router.get("/sdtms/{sdtm_id}/input-selection", response_model=InputSelectionResponse)
def get_input_selection(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> InputSelectionResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    return InputSelectionResponse.model_validate(
        _handler(registry).current_input(session, workbench.id)
    )


@router.put("/sdtms/{sdtm_id}/input-selection", response_model=InputSelectionResponse)
def put_input_selection(
    sdtm_id: UUID,
    command: SdtmInputSelectionWrite,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> InputSelectionResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    context = _raw_context(session, registry, command, workbench.study_id)
    validation = session.get(ValidationRun, command.validation_run_id)
    if (
        validation is None
        or validation.study_id != workbench.study_id
        or validation.module_key != "raw"
        or validation.owner_id != command.raw_id
        or validation.status != "succeeded"
        or validation.input_manifest.get("raw_revision") != command.raw_revision
    ):
        raise ProblemException(
            status_code=422,
            code="sdtm_raw_validation_invalid",
            title="SDTM Raw validation is invalid",
            detail="Select a successful validation snapshot for the exact Raw revision.",
        )
    payload = command.model_dump(mode="json")
    payload["raw_context_fingerprint"] = fingerprint(context)
    record = session.scalar(
        select(SdtmInputSelection).where(SdtmInputSelection.aggregate_id == workbench.id)
    )
    if record is None:
        record = SdtmInputSelection(
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
    artifacts.mark_owner_stale(session, owner_type="sdtm_workbench", owner_id=workbench.id)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return InputSelectionResponse.model_validate(record)


@router.get("/sdtms/{sdtm_id}/raw-context")
def get_raw_context(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    workbench = _sdtm(session, sdtm_id, principal)
    selection = _handler(registry).current_input(session, workbench.id)
    command = _selection_command(selection)
    return _raw_context(session, registry, command, workbench.study_id)


@router.get("/sdtms/{sdtm_id}/specification", response_model=SpecificationResponse)
def get_specification(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> SpecificationResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    record = _handler(registry).latest_specification(session, workbench.id)
    if record is None:
        raise _missing("sdtm_specification_required", "SDTM Specification is not saved.")
    return SpecificationResponse.model_validate(record)


def _save_specification(
    session: Session,
    registry: ModuleRegistry,
    workbench: SdtmWorkbench,
    command: SdtmSpecification,
    principal: Principal,
) -> SdtmSpecificationRevision:
    current = _handler(registry).latest_specification(session, workbench.id)
    record = SdtmSpecificationRevision(
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        revision=1 if current is None else current.revision + 1,
        schema_version=command.schema_version,
        payload=command.model_dump(mode="json"),
        fingerprint=fingerprint(command.model_dump(mode="json")),
        created_by=principal.subject,
    )
    session.add(record)
    plan = _handler(registry).latest_plan(session, workbench.id)
    if plan is not None:
        plan.state = "misaligned"
    workbench.revision += 1
    artifacts.mark_owner_stale(session, owner_type="sdtm_workbench", owner_id=workbench.id)
    return record


@router.put("/sdtms/{sdtm_id}/specification", response_model=SpecificationResponse)
def put_specification(
    sdtm_id: UUID,
    command: SdtmSpecification,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SpecificationResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    record = _save_specification(session, registry, workbench, command, principal)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return SpecificationResponse.model_validate(record)


@router.post("/sdtms/{sdtm_id}/specification/import", response_model=SpecificationResponse)
async def import_specification(
    sdtm_id: UUID,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SpecificationResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    data = await request.body()
    request_fingerprint = hashlib.sha256(data).hexdigest()
    route = f"sdtms:{workbench.id}:specification-import"
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
        record = session.get(SdtmSpecificationRevision, existing.resource_id)
        if record is None:
            raise RuntimeError("idempotency record references a missing SDTM Specification")
        response.headers["ETag"] = etag_for_revision(workbench.revision)
        return SpecificationResponse.model_validate(record)
    require_matching_etag(if_match, workbench.revision)
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            command = SdtmSpecification.model_validate(json.loads(data))
        else:
            command = parse_specification_xlsx(data)
    except (BadZipFile, InvalidFileException, ValidationError, ValueError) as error:
        raise ProblemException(
            status_code=422,
            code="sdtm_specification_import_invalid",
            title="SDTM Specification import is invalid",
            detail=str(error),
        ) from error
    record = _save_specification(session, registry, workbench, command, principal)
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route=route,
            study_id=workbench.study_id,
            key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_type="sdtm_specification_revision",
            resource_id=record.id,
        )
    )
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return SpecificationResponse.model_validate(record)


@router.get("/sdtms/{sdtm_id}/specification/export")
def export_specification(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    export_format: Annotated[str, Query(alias="format", pattern=r"^(json|xlsx)$")] = "json",
) -> Response:
    record = get_specification(sdtm_id, session, registry, principal)
    if export_format == "json":
        return JSONResponse(content=record.payload)
    specification = SdtmSpecification.model_validate(record.payload)
    return Response(
        render_specification_xlsx(specification),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="sdtm-specification.xlsx"'},
    )


@router.get("/sdtms/{sdtm_id}/derivation-plan", response_model=PlanResponse)
def get_plan(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> PlanResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    record = _handler(registry).latest_plan(session, workbench.id)
    if record is None:
        raise _missing("sdtm_derivation_plan_required", "SDTM Derivation Plan is not saved.")
    return PlanResponse.model_validate(record)


@router.put("/sdtms/{sdtm_id}/derivation-plan", response_model=PlanResponse)
def put_plan(
    sdtm_id: UUID,
    command: SdtmDerivationPlan,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> PlanResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    handler = _handler(registry)
    specification = handler.latest_specification(session, workbench.id)
    selection = handler.current_input(session, workbench.id)
    if (
        specification is None
        or command.specification_revision != specification.revision
        or command.input_selection_revision != selection.revision
        or selection.state != "current"
    ):
        raise _stale("sdtm_plan_alignment", "Plan revisions do not match current inputs.")
    lower_plan(context_from_record(specification), command)
    current = handler.latest_plan(session, workbench.id)
    record = SdtmDerivationPlanRevision(
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
    artifacts.mark_owner_stale(session, owner_type="sdtm_workbench", owner_id=workbench.id)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return PlanResponse.model_validate(record)


def _plan_expressions(plan: SdtmDerivationPlan) -> list[tuple[str, Expression]]:
    """Collect every authored expression in a plan with a stable field path."""

    pairs: list[tuple[str, Expression]] = []
    for index, node in enumerate(plan.nodes):
        base = f"nodes[{index}]"
        if node.node_type == "filter":  # noqa: SIM114
            pairs.append((f"{base}.predicate", node.predicate))
        elif node.node_type == "assert":
            pairs.append((f"{base}.predicate", node.predicate))
        elif node.node_type == "derive":
            for name, expression in node.assignments.items():
                pairs.append((f"{base}.assignments.{name}", expression))
    return pairs


@router.post("/sdtms/{sdtm_id}/derivation-plan/validate")
def validate_plan(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    workbench = _sdtm(session, sdtm_id, principal)
    specification, _, plan = _handler(registry).require_aligned(session, workbench.id)
    plan_contract = plan_from_record(plan)
    internal = lower_plan(context_from_record(specification), plan_contract)
    issues = validate_expressions(
        _plan_expressions(plan_contract),
        module="sdtm",
        entity_type="sdtm_derivation_plan",
        entity_id=plan.id,
    )
    status_value = "invalid" if any(issue.severity == "error" for issue in issues) else "valid"
    return {
        "status": status_value,
        "ir_fingerprint": ir_fingerprint(internal),
        "issues": [issue.model_dump(mode="json") for issue in issues],
    }


@router.post("/sdtms/{sdtm_id}/derivation-plan/preview")
def preview_plan(
    sdtm_id: UUID,
    command: PreviewRequest,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    """Evaluate the aligned plan over exact selected Raw inputs with strict row bounds."""

    workbench = _sdtm(session, sdtm_id, principal)
    specification, selection, plan = _handler(registry).require_aligned(session, workbench.id)
    selected = _selection_command(selection)
    _raw_context(session, registry, selected, workbench.study_id)
    provider = cast(
        ContextExporter, registry.require_handler("raw", ModuleCapability.CONTEXT_EXPORT)
    )
    datasets = {
        source.dataset_code: provider.read_context_dataset(
            session,
            storage,
            raw_id=selected.raw_id,
            study_id=workbench.study_id,
            dataset_code=source.dataset_code,
            artifact_id=source.artifact_id,
            expected_checksum=source.checksum,
        )
        for source in selected.source_artifacts
    }
    internal = lower_plan(context_from_record(specification), plan_from_record(plan))
    outputs = evaluate_dataflow(internal, datasets, row_limit=command.limit)
    unknown = sorted(set(command.domains) - set(outputs))
    if unknown:
        raise ProblemException(
            status_code=422,
            code="sdtm_preview_domain_unknown",
            title="SDTM preview domain is unknown",
            detail=f"The plan did not produce: {', '.join(unknown)}.",
        )
    requested = command.domains or tuple(outputs)
    return {
        "schema_version": "1.0.0",
        "ir_fingerprint": ir_fingerprint(internal),
        "input_selection_revision": selection.revision,
        "specification_revision": specification.revision,
        "plan_revision": plan.revision,
        "limit": command.limit,
        "outputs": {name: outputs[name] for name in requested},
    }


@router.get("/sdtms/{sdtm_id}/lineage")
def get_lineage(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    workbench = _sdtm(session, sdtm_id, principal)
    specification, _, plan = _handler(registry).require_aligned(session, workbench.id)
    internal = lower_plan(context_from_record(specification), plan_from_record(plan))
    return {"ir_fingerprint": ir_fingerprint(internal), "outputs": lineage(internal)}


@router.post("/sdtms/{sdtm_id}/validate", response_model=ValidationRunResponse)
def validate_sdtm(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    specification, selection, plan = _handler(registry).require_aligned(session, workbench.id)
    internal = lower_plan(context_from_record(specification), plan_from_record(plan))
    acrf_annotations = tuple(
        session.scalars(
            select(SdtmAcrfAnnotation).where(
                SdtmAcrfAnnotation.sdtm_id == workbench.id,
                SdtmAcrfAnnotation.status != "deleted",
            )
        )
    )
    manifest = {
        "sdtm_revision": workbench.revision,
        "dependency_fingerprint": _handler(registry)
        .get_selection(session, workbench.id, workbench.study_id)
        .fingerprint,
        "input_selection_revision": selection.revision,
        "specification_revision": specification.revision,
        "specification_fingerprint": specification.fingerprint,
        "plan_revision": plan.revision,
        "plan_fingerprint": plan.fingerprint,
        "acrf_annotations": [
            {"id": str(item.id), "revision": item.revision, "fingerprint": item.fingerprint}
            for item in sorted(acrf_annotations, key=lambda item: str(item.id))
        ],
        "normalized_ir": canonical_ir(internal),
    }
    run = ValidationRun(
        study_id=workbench.study_id,
        module_key="sdtm",
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        status="succeeded",
        validator_name="sdtm-authoring-validator",
        validator_version="1.0.0",
        input_fingerprint=fingerprint(manifest),
        input_manifest=manifest,
        started_at=utc_now(),
        completed_at=utc_now(),
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
    workbench: SdtmWorkbench,
    artifact_types: tuple[str, ...],
    expected_input_fingerprint: str,
    response: Response,
    session: Session,
    registry: ModuleRegistry,
    principal: Principal,
    idempotency_key: str | None,
) -> ArtifactBuildResponse:
    unsupported = sorted(set(artifact_types) - set(SDTM_BUILD_ARTIFACT_TYPES))
    if unsupported:
        raise ProblemException(
            status_code=422,
            code="artifact_type_unsupported",
            title="Artifact type is unsupported",
            detail=f"Unsupported SDTM artifact types: {', '.join(unsupported)}",
        )
    return create_artifact_build(
        ArtifactBuildCreate(
            study_id=workbench.study_id,
            owner_type="sdtm_workbench",
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
    "/sdtms/{sdtm_id}/artifacts",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_sdtm_artifacts(
    sdtm_id: UUID,
    command: SdtmArtifactRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    workbench = _sdtm(session, sdtm_id, principal)
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
    "/sdtms/{sdtm_id}/compile",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def compile_sdtm(
    sdtm_id: UUID,
    command: CompileRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    return _build(
        workbench,
        (f"sdtm_program_{command.backend}",),
        command.expected_input_fingerprint,
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/sdtms/{sdtm_id}/execute",
    response_model=ExecutionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def execute_sdtm(
    sdtm_id: UUID,
    command: SdtmExecutionRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExecutionRunResponse:
    """Submit one exact SDTM execution through the shared immutable run service."""

    workbench = _sdtm(session, sdtm_id, principal)
    return create_execution_run(
        ExecutionRunCreate(
            study_id=workbench.study_id,
            module="sdtm",
            owner_type="sdtm_workbench",
            owner_id=workbench.id,
            language=command.language,
            program_artifact_id=command.program_artifact_id,
            input_artifact_ids=command.input_artifact_ids,
            validation_run_id=command.validation_run_id,
            input_selection_revision=command.input_selection_revision,
            source_specification_revision=command.source_specification_revision,
            source_plan_type="sdtm_derivation_plan",
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


def _stale(field: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=409,
        code="stale_input_fingerprint",
        title="SDTM input is stale",
        detail=detail,
        issues=[{"field_path": field}],
    )


def _missing(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=404, code=code, title="SDTM authored resource not found", detail=detail
    )
