"""SDTM exact Raw input, Specification, validation, lineage, and artifact APIs."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Protocol, cast
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
    get_module_registry,
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
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry
from app.sdtm.contracts import (
    SdtmInputSelectionWrite,
    SdtmSpecification,
    SdtmSpecificationInitializationOptions,
    SdtmSpecificationInitialize,
)
from app.sdtm.models import (
    SdtmAcrfAnnotation,
    SdtmDomainMappingRevision,
    SdtmInputSelection,
    SdtmOutputSelection,
    SdtmSpecificationRevision,
    SdtmVariableMappingRevision,
    SdtmWorkbench,
)
from app.sdtm.service import (
    SDTM_BUILD_ARTIFACT_TYPES,
    SdtmCapability,
    context_from_record,
)
from app.sdtm.specification_workbook import (
    parse_specification_xlsx,
    render_specification_xlsx,
)
from app.sdtm.standard_specification import (
    initialize_specification_from_standard,
    standard_domain_options,
)
from app.standards.metadata_resolution import ResolvedStandardMetadata, resolve_standard_metadata
from app.studies.service import StudyService
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


class AdamConsumerStaleness(Protocol):
    def mark_sdtm_refresh(self, session: Session, sdtm_id: UUID) -> tuple[UUID, ...]: ...


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


class SdtmArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_types: tuple[str, ...] = Field(min_length=1)
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    domain_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9]{1,7}$")


def _handler(registry: ModuleRegistry) -> SdtmCapability:
    return cast(SdtmCapability, registry.require_handler("sdtm", ModuleCapability.DEPENDENCIES))


def _selected_sdtmig_metadata(
    session: Session,
    handler: SdtmCapability,
    workbench: SdtmWorkbench,
) -> ResolvedStandardMetadata:
    dependency_selection = handler.get_selection(session, workbench.id, workbench.study_id)
    selected = [item for item in dependency_selection.standards if item.purpose == "sdtm_ig"]
    if not selected:
        # Complete CDISC Library snapshots registered before the module-specific
        # purpose existed use the version's generic reference-metadata purpose.
        selected = [
            item for item in dependency_selection.standards if item.purpose == "reference_metadata"
        ]
    if len(selected) != 1:
        raise ProblemException(
            status_code=409,
            code="sdtm_industry_standard_required",
            title="An SDTM industry standard selection is required",
            detail=(
                "Select exactly one SDTM implementation-guide version for purpose "
                "sdtm_ig before initializing the Specification."
            ),
        )
    try:
        return resolve_standard_metadata(
            session,
            selected[0].standard_version_id,
            repository_root=Path(__file__).resolve().parents[3],
        )
    except ValueError as error:
        raise ProblemException(
            status_code=422,
            code="sdtm_industry_standard_unsupported",
            title="The selected SDTM industry standard cannot initialize a Specification",
            detail=str(error),
        ) from error


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


def _misalign_all_domain_plans(
    handler: SdtmCapability, session: Session, aggregate_id: UUID, reason: str
) -> None:
    """Misalign mapping heads for a Specification or Raw-selection change."""

    for model in cast(tuple[Any, ...], (SdtmDomainMappingRevision, SdtmVariableMappingRevision)):
        records: Any = session.scalars(
            select(model)
            .where(model.aggregate_id == aggregate_id)
            .order_by(model.domain_code, model.revision.desc())
        )
        seen: set[str] = set()
        for head in records:
            if head.domain_code in seen:
                continue
            seen.add(head.domain_code)
            if head.state == "aligned":
                head.state = "misaligned"
                head.alignment_reasons = sorted(set(head.alignment_reasons or ()) | {reason})
    output = session.scalar(
        select(SdtmOutputSelection).where(SdtmOutputSelection.aggregate_id == aggregate_id)
    )
    if output is not None:
        output.state = "stale"
    if reason == "specification_changed":
        for imported in handler.selected_imported_domains(session, aggregate_id).values():
            imported.state = "misaligned"
            imported.alignment_reasons = [reason]


def _stale_adam_consumers(session: Session, registry: ModuleRegistry, sdtm_id: UUID) -> None:
    consumer = cast(
        AdamConsumerStaleness,
        registry.require_handler("adam", ModuleCapability.STALENESS),
    )
    for adam_id in consumer.mark_sdtm_refresh(session, sdtm_id):
        artifacts.mark_owner_stale(session, owner_type="adam_workbench", owner_id=adam_id)


def _selected_import_artifact_ids(
    handler: SdtmCapability, session: Session, sdtm_id: UUID
) -> tuple[UUID, ...]:
    """Protect active imported inputs when unrelated SDTM evidence becomes stale."""

    return tuple(
        imported.artifact_id
        for imported in handler.selected_imported_domains(session, sdtm_id).values()
        if imported.state == "aligned"
    )


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
    _misalign_all_domain_plans(_handler(registry), session, workbench.id, "input_changed")
    workbench.revision += 1
    handler = _handler(registry)
    artifacts.mark_owner_stale(
        session,
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        exclude_artifact_ids=_selected_import_artifact_ids(handler, session, workbench.id),
    )
    _stale_adam_consumers(session, registry, workbench.id)
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
    if command.schema_version != "2.0.0":
        raise ProblemException(
            status_code=422,
            code="sdtm_specification_schema_outdated",
            title="Current SDTM Specification schema required",
            detail=(
                "Historical 1.0.0 Specifications remain readable, but a new save must use "
                "2.0.0 reusable value contexts."
            ),
        )
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
    _misalign_all_domain_plans(_handler(registry), session, workbench.id, "specification_changed")
    workbench.revision += 1
    artifacts.mark_owner_stale(
        session,
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
    )
    _stale_adam_consumers(session, registry, workbench.id)
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


@router.get(
    "/sdtms/{sdtm_id}/specification/initialization-options",
    response_model=SdtmSpecificationInitializationOptions,
)
def get_specification_initialization_options(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> SdtmSpecificationInitializationOptions:
    """List the concrete domains available from the exact selected SDTMIG."""

    workbench = _sdtm(session, sdtm_id, principal)
    metadata = _selected_sdtmig_metadata(session, _handler(registry), workbench)
    try:
        domains = standard_domain_options(metadata)
    except ValueError as error:
        raise ProblemException(
            status_code=422,
            code="sdtm_industry_standard_unsupported",
            title="The selected SDTM industry standard cannot initialize a Specification",
            detail=str(error),
        ) from error
    return SdtmSpecificationInitializationOptions(
        standard_version_id=metadata.version_id,
        domains=domains,
    )


@router.post(
    "/sdtms/{sdtm_id}/specification/initialize",
    response_model=SpecificationResponse,
)
def initialize_specification(
    sdtm_id: UUID,
    command: SdtmSpecificationInitialize,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SpecificationResponse:
    """Populate missing Specification structures from the exact selected SDTMIG."""

    workbench = _sdtm(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    handler = _handler(registry)
    current_record = handler.latest_specification(session, workbench.id)
    current = context_from_record(current_record) if current_record is not None else None
    try:
        metadata = _selected_sdtmig_metadata(session, handler, workbench)
        specification = initialize_specification_from_standard(
            metadata,
            current,
            domain_codes=command.domain_codes,
            core_variables_only=command.required_expected_only,
        )
    except ValueError as error:
        raise ProblemException(
            status_code=422,
            code="sdtm_industry_standard_unsupported",
            title="The selected SDTM industry standard cannot initialize a Specification",
            detail=str(error),
        ) from error
    record = _save_specification(session, registry, workbench, specification, principal)
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


def _require_domain(
    handler: SdtmCapability, session: Session, aggregate_id: UUID, domain_code: str
) -> SdtmSpecificationRevision:
    """Validate the path domain against the pattern and current Specification."""

    import re

    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,7}", domain_code):
        raise ProblemException(
            status_code=404,
            code="sdtm_domain_unknown",
            title="SDTM domain is unknown",
            detail=f"'{domain_code}' is not a valid domain code.",
        )
    specification = handler.latest_specification(session, aggregate_id)
    if specification is None:
        raise _missing("sdtm_specification_required", "SDTM Specification is not saved.")
    codes = {domain.code for domain in context_from_record(specification).domains}
    if domain_code not in codes:
        raise ProblemException(
            status_code=404,
            code="sdtm_domain_unknown",
            title="SDTM domain is unknown",
            detail=f"Domain '{domain_code}' is not declared in the current Specification.",
        )
    return specification


@router.get("/sdtms/{sdtm_id}/lineage")
def get_lineage(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    workbench = _sdtm(session, sdtm_id, principal)
    handler = _handler(registry)
    specification = handler.latest_specification(session, workbench.id)
    if specification is None:
        raise _missing("sdtm_specification_required", "SDTM Specification is not saved.")
    mappings = session.scalars(
        select(SdtmDomainMappingRevision)
        .where(SdtmDomainMappingRevision.aggregate_id == workbench.id)
        .order_by(SdtmDomainMappingRevision.domain_code, SdtmDomainMappingRevision.revision.desc())
    )
    variables = session.scalars(
        select(SdtmVariableMappingRevision)
        .where(SdtmVariableMappingRevision.aggregate_id == workbench.id)
        .order_by(
            SdtmVariableMappingRevision.domain_code, SdtmVariableMappingRevision.revision.desc()
        )
    )
    mapping_heads: dict[str, SdtmDomainMappingRevision] = {}
    variable_heads: dict[str, SdtmVariableMappingRevision] = {}
    for domain_mapping_row in mappings:
        mapping_heads.setdefault(domain_mapping_row.domain_code, domain_mapping_row)
    for variable_mapping_row in variables:
        variable_heads.setdefault(variable_mapping_row.domain_code, variable_mapping_row)
    domains: dict[str, object] = {}
    for code, mapping in sorted(mapping_heads.items()):
        variable = variable_heads.get(code)
        domains[code] = {
            "lineage_type": "author_maintained",
            "domain_mapping_revision": mapping.revision,
            "domain_mapping": mapping.payload,
            "variable_mapping_revision": variable.revision if variable else None,
            "variable_mapping": variable.payload if variable else {"cells": []},
        }
    return {
        "schema_version": "2.0.0",
        "lineage_type": "author_maintained",
        "inferred_from_program": False,
        "lineage_fingerprint": fingerprint(domains),
        "domains": domains,
    }


@router.post(
    "/sdtms/{sdtm_id}/domains/{domain_code}/validate",
    response_model=ValidationRunResponse,
)
def validate_sdtm_domain(
    sdtm_id: UUID,
    domain_code: str,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    """Per-domain validation run for authoring feedback and per-domain program builds."""

    workbench = _sdtm(session, sdtm_id, principal)
    handler = _handler(registry)
    specification = _require_domain(handler, session, workbench.id, domain_code)
    mapping = session.scalar(
        select(SdtmDomainMappingRevision)
        .where(
            SdtmDomainMappingRevision.aggregate_id == workbench.id,
            SdtmDomainMappingRevision.domain_code == domain_code,
        )
        .order_by(SdtmDomainMappingRevision.revision.desc())
    )
    variable = session.scalar(
        select(SdtmVariableMappingRevision)
        .where(
            SdtmVariableMappingRevision.aggregate_id == workbench.id,
            SdtmVariableMappingRevision.domain_code == domain_code,
        )
        .order_by(SdtmVariableMappingRevision.revision.desc())
    )
    if (
        mapping is None
        or variable is None
        or mapping.state != "aligned"
        or variable.state != "aligned"
    ):
        raise ProblemException(
            status_code=409,
            code="sdtm_mapping_alignment_required",
            title="Current mappings required",
            detail="Save aligned Domain and Variable Mappings before domain validation.",
        )
    manifest = {
        "sdtm_revision": workbench.revision,
        "dependency_fingerprint": handler.get_selection(
            session, workbench.id, workbench.study_id
        ).fingerprint,
        "input_selection_revision": mapping.input_selection_revision,
        "specification_revision": specification.revision,
        "specification_fingerprint": specification.fingerprint,
        "domain_code": domain_code,
        "domain_mapping_revision": mapping.revision,
        "domain_mapping_fingerprint": mapping.fingerprint,
        "variable_mapping_revision": variable.revision,
        "variable_mapping_fingerprint": variable.fingerprint,
        "lineage_type": "author_maintained",
    }
    run = ValidationRun(
        study_id=workbench.study_id,
        module_key="sdtm",
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        status="succeeded",
        validator_name="sdtm-authoring-validator",
        validator_version="2.0.0",
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


@router.post("/sdtms/{sdtm_id}/validate", response_model=ValidationRunResponse)
def validate_sdtm(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    handler = _handler(registry)
    specification = handler.latest_specification(session, workbench.id)
    if specification is None:
        raise _missing("sdtm_specification_required", "SDTM Specification is not saved.")
    selection = session.scalar(
        select(SdtmOutputSelection).where(SdtmOutputSelection.aggregate_id == workbench.id)
    )
    if (
        selection is None
        or selection.state != "current"
        or selection.specification_revision != specification.revision
    ):
        raise ProblemException(
            status_code=409,
            code="sdtm_output_selection_required",
            title="Current Output Selection required",
            detail="Select one coherent successful generation or import for every domain.",
        )
    acrf_annotations = tuple(
        session.scalars(
            select(SdtmAcrfAnnotation).where(
                SdtmAcrfAnnotation.sdtm_id == workbench.id,
                SdtmAcrfAnnotation.status.notin_(("deleted", "retired")),
            )
        )
    )
    manifest = {
        "sdtm_revision": workbench.revision,
        "dependency_fingerprint": handler.get_selection(
            session, workbench.id, workbench.study_id
        ).fingerprint,
        "specification_revision": specification.revision,
        "specification_fingerprint": specification.fingerprint,
        "output_selection_revision": selection.revision,
        "output_selection_fingerprint": selection.fingerprint,
        "outputs": selection.payload,
        "acrf_annotations": [
            {"id": str(item.id), "revision": item.revision, "fingerprint": item.fingerprint}
            for item in sorted(acrf_annotations, key=lambda item: str(item.id))
        ],
    }
    run = ValidationRun(
        study_id=workbench.study_id,
        module_key="sdtm",
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        status="succeeded",
        validator_name="sdtm-authoring-validator",
        validator_version="2.0.0",
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
    domain_code: str | None = None,
) -> ArtifactBuildResponse:
    unsupported = sorted(set(artifact_types) - set(SDTM_BUILD_ARTIFACT_TYPES))
    if unsupported:
        raise ProblemException(
            status_code=422,
            code="artifact_type_unsupported",
            title="Artifact type is unsupported",
            detail=f"Unsupported SDTM artifact types: {', '.join(unsupported)}",
        )
    options: dict[str, str | int | float | bool | None] = {}
    if domain_code is not None:
        options["domain_code"] = domain_code
    return create_artifact_build(
        ArtifactBuildCreate(
            study_id=workbench.study_id,
            owner_type="sdtm_workbench",
            owner_id=workbench.id,
            artifact_types=artifact_types,
            expected_input_fingerprint=expected_input_fingerprint,
            options=options,
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
        command.domain_code,
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
