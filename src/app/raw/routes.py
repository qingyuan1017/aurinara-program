"""Raw dataset, variable, preview, validation, and artifact APIs."""

import hashlib
from datetime import datetime
from typing import Annotated, cast
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_object_storage, get_session
from app.artifacts.builds import (
    ArtifactBuildCreate,
    ArtifactBuildResponse,
    create_artifact_build,
    resolve_build_fingerprint,
)
from app.artifacts.models import SourceFile
from app.artifacts.service import ArtifactService
from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.idempotency import IdempotencyRecord
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.config import Settings
from app.execution.jobs import Job
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry
from app.raw.contracts import (
    RawDatasetCreate,
    RawDatasetImportEntry,
    RawDatasetImportRequest,
    RawDatasetImportResponse,
    RawDatasetPatch,
    RawPhysicalSnapshot,
    RawPreviewRequest,
    RawVariablePatch,
    RawVariableWrite,
)
from app.raw.files import inspect_file, preview_rows
from app.raw.models import RawDataset, RawDatasetImport, RawVariable, RawWorkbench
from app.raw.service import (
    RAW_ARTIFACT_TYPES,
    RawCapability,
    binding_for,
    organize_source_repository,
    resolve_bulk_sources,
    stale_raw_consumers,
)
from app.reconciliation.routes import (
    ReconciliationCreate,
    ReconciliationInput,
    ReconciliationResponse,
    create_reconciliation,
)
from app.studies.service import StudyService
from app.validation.contracts import IssueSeverity, ValidationIssue
from app.validation.models import ValidationRun
from app.validation.routes import ValidationRunResponse

router = APIRouter(tags=["raw"])
studies = StudyService()
artifacts = ArtifactService()
ISSUE_NAMESPACE = UUID("ebdfc410-3adc-4f6a-aebc-59eb058e92fe")


class RawDatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    raw_id: UUID
    study_id: UUID
    code: str
    label: str
    description: str | None
    current_source_file_id: UUID
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime


class RawVariableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    dataset_id: UUID
    study_id: UUID
    name: str
    label: str | None
    physical_type: str | None
    length: int | None
    precision: int | None
    ordinal: int
    role: str | None
    description: str | None
    terminology_binding: dict[str, object] | None
    revision: int


class RawPreviewResponse(BaseModel):
    columns: tuple[str, ...]
    rows: tuple[dict[str, object | None], ...]
    offset: int
    limit: int
    total_rows: int


class RawInitializeResponse(BaseModel):
    physical_schema: RawPhysicalSnapshot
    variables: tuple[RawVariableResponse, ...]
    created: int
    filled: int


class RawArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_types: tuple[str, ...] = Field(min_length=1)
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class RawArtifactFingerprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_types: tuple[str, ...] = Field(min_length=1)


class RawArtifactFingerprintResponse(BaseModel):
    input_fingerprint: str


class RawReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_raw_revision: int = Field(ge=1)


class RawLatestValidationRunResponse(BaseModel):
    """Reference to the latest successful Raw validation run.

    Lets a consumer (the SDTM input selection) pin ``validation_run_id``
    without typing the opaque identifier. ``raw_revision`` is read from the
    run's own input manifest so the UI can confirm the run matches the pinned
    Raw revision; it is advisory and may be absent on older runs.
    """

    model_config = ConfigDict(extra="forbid")
    validation_run_id: UUID
    raw_revision: int | None = None
    completed_at: datetime | None = None
    input_fingerprint: str


def _handler(registry: ModuleRegistry) -> RawCapability:
    return cast(RawCapability, registry.require_handler("raw", ModuleCapability.DEPENDENCIES))


def _raw(
    session: Session, registry: ModuleRegistry, raw_id: UUID, principal: Principal
) -> RawWorkbench:
    raw = session.get(RawWorkbench, raw_id)
    if raw is None:
        raise _not_found("raw_not_found", "Raw workbench not found")
    studies.require_access(session, raw.study_id, principal)
    return raw


def _dataset(session: Session, dataset_id: UUID, principal: Principal) -> RawDataset:
    dataset = session.get(RawDataset, dataset_id)
    if dataset is None:
        raise _not_found("raw_dataset_not_found", "Raw dataset not found")
    studies.require_access(session, dataset.study_id, principal)
    return dataset


def _variable(session: Session, variable_id: UUID, principal: Principal) -> RawVariable:
    variable = session.get(RawVariable, variable_id)
    if variable is None:
        raise _not_found("raw_variable_not_found", "Raw variable not found")
    studies.require_access(session, variable.study_id, principal)
    return variable


def _source(session: Session, source_file_id: UUID, study_id: UUID) -> SourceFile:
    """Resolve one study-owned source file, preserving single-dataset HTTP behavior.

    Shares resolution with the bulk path via ``resolve_bulk_sources`` and raises
    ``422 raw_source_file_invalid`` when it reports a missing or foreign source.
    """

    entry = RawDatasetImportEntry(code="X", label="x", source_file_id=source_file_id)
    _, issues = resolve_bulk_sources(session, study_id=study_id, entries=[entry])
    if issues:
        raise ProblemException(
            status_code=422,
            code="raw_source_file_invalid",
            title="Raw source file is invalid",
            detail="The immutable source file does not exist in this study.",
        )
    source = session.get(SourceFile, source_file_id)
    assert source is not None  # resolve_bulk_sources reported no issue
    return source


def _stale(session: Session, registry: ModuleRegistry, raw: RawWorkbench) -> None:
    stale_raw_consumers(session, registry, raw)


@router.patch("/raw/{raw_id}", response_model=dict[str, object])
def patch_raw(
    raw_id: UUID,
    command: dict[str, str],
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, object]:
    raw = _raw(session, registry, raw_id, principal)
    require_matching_etag(if_match, raw.revision)
    unknown = set(command) - {"name", "status"}
    if unknown or ("status" in command and command["status"] not in {"draft", "active", "retired"}):
        raise ProblemException(
            status_code=422,
            code="raw_patch_invalid",
            title="Raw workbench patch is invalid",
            detail="Only name and a supported status may be changed.",
        )
    if "name" in command:
        raw.name = command["name"]
    if "status" in command:
        raw.status = command["status"]
    raw.revision += 1
    _stale(session, registry, raw)
    session.commit()
    response.headers["ETag"] = etag_for_revision(raw.revision)
    return {
        "id": raw.id,
        "study_id": raw.study_id,
        "code": raw.code,
        "name": raw.name,
        "status": raw.status,
        "revision": raw.revision,
    }


@router.post(
    "/raw/{raw_id}/datasets",
    response_model=RawDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset(
    raw_id: UUID,
    command: RawDatasetCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RawDatasetResponse:
    raw = _raw(session, registry, raw_id, principal)
    source = _source(session, command.source_file_id, raw.study_id)
    with storage.open(source.object_key) as stream:
        inspect_file(stream, source.filename)
    dataset = RawDataset(
        raw_id=raw.id,
        study_id=raw.study_id,
        code=command.code,
        label=command.label,
        description=command.description,
        current_source_file_id=source.id,
    )
    session.add(dataset)
    session.flush()
    session.add(binding_for(dataset, source, created_by=principal.subject))
    organize_source_repository(session, source)
    raw.revision += 1
    _stale(session, registry, raw)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="duplicate_raw_dataset_code",
            title="Raw dataset code already exists",
            detail="Dataset codes are unique within a Raw workbench.",
        ) from error
    response.headers["ETag"] = etag_for_revision(dataset.revision)
    return RawDatasetResponse.model_validate(dataset)


@router.get("/raw/{raw_id}/datasets", response_model=list[RawDatasetResponse])
def list_datasets(
    raw_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[RawDatasetResponse]:
    raw = _raw(session, registry, raw_id, principal)
    return [
        RawDatasetResponse.model_validate(item)
        for item in session.scalars(
            select(RawDataset).where(RawDataset.raw_id == raw.id).order_by(RawDataset.code)
        )
    ]


@router.get("/raw-datasets/{dataset_id}", response_model=RawDatasetResponse)
def get_dataset(
    dataset_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RawDatasetResponse:
    dataset = _dataset(session, dataset_id, principal)
    response.headers["ETag"] = etag_for_revision(dataset.revision)
    return RawDatasetResponse.model_validate(dataset)


@router.patch("/raw-datasets/{dataset_id}", response_model=RawDatasetResponse)
def patch_dataset(
    dataset_id: UUID,
    command: RawDatasetPatch,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> RawDatasetResponse:
    dataset = _dataset(session, dataset_id, principal)
    require_matching_etag(if_match, dataset.revision)
    raw = cast(RawWorkbench, session.get(RawWorkbench, dataset.raw_id))
    values = command.model_dump(exclude_unset=True)
    source_id = values.pop("source_file_id", None)
    dataset.revision += 1
    previous_source: SourceFile | None = None
    if source_id is not None and source_id != dataset.current_source_file_id:
        previous_source = _source(session, dataset.current_source_file_id, dataset.study_id)
        source = _source(session, source_id, dataset.study_id)
        with storage.open(source.object_key) as stream:
            inspect_file(stream, source.filename)
        dataset.current_source_file_id = source.id
        session.add(binding_for(dataset, source, created_by=principal.subject))
        session.flush()
        organize_source_repository(session, source)
        organize_source_repository(session, previous_source)
    for name, value in values.items():
        setattr(dataset, name, value)
    raw.revision += 1
    _stale(session, registry, raw)
    session.commit()
    response.headers["ETag"] = etag_for_revision(dataset.revision)
    return RawDatasetResponse.model_validate(dataset)


@router.delete("/raw-datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def retire_dataset(
    dataset_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    dataset = _dataset(session, dataset_id, principal)
    require_matching_etag(if_match, dataset.revision)
    raw = cast(RawWorkbench, session.get(RawWorkbench, dataset.raw_id))
    dataset.status = "retired"
    dataset.revision += 1
    session.flush()
    organize_source_repository(
        session,
        _source(session, dataset.current_source_file_id, dataset.study_id),
    )
    raw.revision += 1
    _stale(session, registry, raw)
    session.commit()


@router.get("/raw-datasets/{dataset_id}/variables", response_model=list[RawVariableResponse])
def list_variables(
    dataset_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[RawVariableResponse]:
    dataset = _dataset(session, dataset_id, principal)
    return [
        RawVariableResponse.model_validate(item)
        for item in session.scalars(
            select(RawVariable)
            .where(RawVariable.dataset_id == dataset.id)
            .order_by(RawVariable.ordinal)
        )
    ]


@router.post(
    "/raw-datasets/{dataset_id}/variables",
    response_model=RawVariableResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_variable(
    dataset_id: UUID,
    command: RawVariableWrite,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RawVariableResponse:
    dataset = _dataset(session, dataset_id, principal)
    variable = RawVariable(
        dataset_id=dataset.id,
        study_id=dataset.study_id,
        **command.model_dump(mode="json"),
    )
    session.add(variable)
    raw = cast(RawWorkbench, session.get(RawWorkbench, dataset.raw_id))
    dataset.revision += 1
    raw.revision += 1
    _stale(session, registry, raw)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="duplicate_raw_variable",
            title="Raw variable conflicts",
            detail="Variable names and ordinals are unique within a dataset.",
        ) from error
    response.headers["ETag"] = etag_for_revision(variable.revision)
    return RawVariableResponse.model_validate(variable)


@router.get("/raw-variables/{variable_id}", response_model=RawVariableResponse)
def get_variable(
    variable_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RawVariableResponse:
    variable = _variable(session, variable_id, principal)
    response.headers["ETag"] = etag_for_revision(variable.revision)
    return RawVariableResponse.model_validate(variable)


@router.patch("/raw-variables/{variable_id}", response_model=RawVariableResponse)
def patch_variable(
    variable_id: UUID,
    command: RawVariablePatch,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> RawVariableResponse:
    variable = _variable(session, variable_id, principal)
    require_matching_etag(if_match, variable.revision)
    dataset = cast(RawDataset, session.get(RawDataset, variable.dataset_id))
    raw = cast(RawWorkbench, session.get(RawWorkbench, dataset.raw_id))
    for name, value in command.model_dump(exclude_unset=True, mode="json").items():
        setattr(variable, name, value)
    variable.revision += 1
    dataset.revision += 1
    raw.revision += 1
    _stale(session, registry, raw)
    session.commit()
    response.headers["ETag"] = etag_for_revision(variable.revision)
    return RawVariableResponse.model_validate(variable)


@router.delete("/raw-variables/{variable_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_variable(
    variable_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    variable = _variable(session, variable_id, principal)
    require_matching_etag(if_match, variable.revision)
    dataset = cast(RawDataset, session.get(RawDataset, variable.dataset_id))
    raw = cast(RawWorkbench, session.get(RawWorkbench, dataset.raw_id))
    session.delete(variable)
    dataset.revision += 1
    raw.revision += 1
    _stale(session, registry, raw)
    session.commit()


@router.post(
    "/raw-datasets/{dataset_id}/variables/initialize", response_model=RawInitializeResponse
)
def initialize_variables(
    dataset_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RawInitializeResponse:
    dataset = _dataset(session, dataset_id, principal)
    source = _source(session, dataset.current_source_file_id, dataset.study_id)
    with storage.open(source.object_key) as stream:
        physical = inspect_file(stream, source.filename)
    existing = {
        item.name: item
        for item in session.scalars(select(RawVariable).where(RawVariable.dataset_id == dataset.id))
    }
    created = 0
    filled = 0
    for column in physical.columns:
        variable = existing.get(column.name)
        if variable is None:
            variable = RawVariable(
                dataset_id=dataset.id,
                study_id=dataset.study_id,
                name=column.name,
                physical_type=column.physical_type,
                length=column.length,
                precision=column.precision,
                ordinal=column.ordinal,
            )
            session.add(variable)
            existing[column.name] = variable
            created += 1
        else:
            variable_filled = False
            for name in ("physical_type", "length", "precision"):
                if getattr(variable, name) is None and getattr(column, name) is not None:
                    setattr(variable, name, getattr(column, name))
                    filled += 1
                    variable_filled = True
            if variable_filled:
                variable.revision += 1
    if created or filled:
        raw = cast(RawWorkbench, session.get(RawWorkbench, dataset.raw_id))
        dataset.revision += 1
        raw.revision += 1
        _stale(session, registry, raw)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="raw_initialization_conflict",
            title="Raw initialization conflicts with maintained metadata",
            detail="A physical column conflicts with a maintained variable ordinal.",
        ) from error
    values = tuple(
        RawVariableResponse.model_validate(item)
        for item in session.scalars(
            select(RawVariable)
            .where(RawVariable.dataset_id == dataset.id)
            .order_by(RawVariable.ordinal)
        )
    )
    return RawInitializeResponse(
        physical_schema=physical, variables=values, created=created, filled=filled
    )


@router.post("/raw-datasets/{dataset_id}/preview", response_model=RawPreviewResponse)
def preview_dataset(
    dataset_id: UUID,
    command: RawPreviewRequest,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RawPreviewResponse:
    dataset = _dataset(session, dataset_id, principal)
    source = _source(session, dataset.current_source_file_id, dataset.study_id)
    with storage.open(source.object_key) as stream:
        columns, rows, total = preview_rows(
            stream, source.filename, command.columns, command.offset, command.limit
        )
    return RawPreviewResponse(
        columns=columns,
        rows=rows,
        offset=command.offset,
        limit=command.limit,
        total_rows=total,
    )


def _issue(
    code: str,
    message: str,
    raw_id: UUID,
    *,
    dataset: str | None = None,
    variable: str | None = None,
    field_path: str | None = None,
) -> ValidationIssue:
    key = f"{raw_id}:{code}:{dataset}:{variable}:{field_path}"
    return ValidationIssue(
        id=uuid5(ISSUE_NAMESPACE, key),
        code=code,
        severity=IssueSeverity.ERROR,
        message=message,
        suggestion="Correct the source binding or maintained Raw metadata and revalidate.",
        module="raw",
        entity_type="raw_workbench",
        entity_id=raw_id,
        field_path=field_path,
        dataset=dataset,
        variable=variable,
    )


@router.post("/raw/{raw_id}/validate", response_model=ValidationRunResponse)
def validate_raw(
    raw_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    raw = _raw(session, registry, raw_id, principal)
    handler = _handler(registry)
    selection = handler.get_selection(session, raw.id, raw.study_id)
    issues: list[ValidationIssue] = []
    datasets = tuple(
        session.scalars(
            select(RawDataset).where(RawDataset.raw_id == raw.id, RawDataset.status == "active")
        )
    )
    if not datasets:
        issues.append(
            _issue("raw_dataset_required", "At least one active dataset is required.", raw.id)
        )
    for dataset in datasets:
        source = _source(session, dataset.current_source_file_id, dataset.study_id)
        digest = hashlib.sha256()
        with storage.open(source.object_key) as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != source.sha256:
            issues.append(
                _issue(
                    "raw_source_checksum_mismatch",
                    "The bound source bytes do not match their immutable checksum.",
                    raw.id,
                    dataset=dataset.code,
                )
            )
            continue
        try:
            with storage.open(source.object_key) as stream:
                physical = inspect_file(stream, source.filename)
        except ProblemException as error:
            issues.append(_issue(error.code, error.detail, raw.id, dataset=dataset.code))
            continue
        physical_by_name = {column.name: column for column in physical.columns}
        variables = tuple(
            session.scalars(select(RawVariable).where(RawVariable.dataset_id == dataset.id))
        )
        maintained = {item.name: item for item in variables}
        for name, column in physical_by_name.items():
            variable = maintained.get(name)
            if variable is None:
                issues.append(
                    _issue(
                        "raw_variable_missing",
                        "A physical column has no maintained variable metadata.",
                        raw.id,
                        dataset=dataset.code,
                        variable=name,
                    )
                )
            elif variable.physical_type is None:
                issues.append(
                    _issue(
                        "raw_variable_type_missing",
                        "Variable physical type is not maintained.",
                        raw.id,
                        dataset=dataset.code,
                        variable=name,
                        field_path="physical_type",
                    )
                )
            elif variable.physical_type != column.physical_type:
                issues.append(
                    _issue(
                        "raw_variable_type_mismatch",
                        f"Maintained type '{variable.physical_type}' differs from observed "
                        f"type '{column.physical_type}'.",
                        raw.id,
                        dataset=dataset.code,
                        variable=name,
                        field_path="physical_type",
                    )
                )
        for variable in variables:
            if variable.name not in physical_by_name:
                issues.append(
                    _issue(
                        "raw_variable_not_in_source",
                        "Maintained variable is absent from the bound source file.",
                        raw.id,
                        dataset=dataset.code,
                        variable=variable.name,
                    )
                )
    context = handler.context_snapshot(session, raw.id, raw.study_id)
    snapshot = {
        **context,
        "dependency_selection": selection.model_dump(mode="json"),
    }
    run = ValidationRun(
        study_id=raw.study_id,
        module_key="raw",
        owner_type="raw_workbench",
        owner_id=raw.id,
        status="failed" if issues else "succeeded",
        validator_name="raw-physical-schema-validator",
        validator_version="1.0.0",
        input_fingerprint=fingerprint(snapshot),
        input_manifest=snapshot,
        started_at=utc_now(),
        completed_at=utc_now(),
        error_count=len(issues),
        warning_count=0,
        info_count=0,
        issues=[item.model_dump(mode="json") for item in issues],
        report_artifact_ids=[],
        failure={"code": "raw_validation_failed"} if issues else None,
        created_by=principal.subject,
    )
    session.add(run)
    session.commit()
    return ValidationRunResponse.model_validate(run)


@router.get(
    "/raw/{raw_id}/latest-validation-run",
    response_model=RawLatestValidationRunResponse,
)
def get_latest_validation_run(
    raw_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RawLatestValidationRunResponse:
    """Return the latest successful Raw validation-run reference.

    Read-only; persists nothing. Resolves the newest ``succeeded`` validation
    run owned by this Raw workbench so a consumer can pin ``validation_run_id``
    without typing it. Returns ``404 raw_validation_run_not_found`` when the
    workbench has no successful run yet, prompting the user to run and pass
    validation first.
    """

    raw = _raw(session, registry, raw_id, principal)
    run = session.scalars(
        select(ValidationRun)
        .where(
            ValidationRun.module_key == "raw",
            ValidationRun.owner_type == "raw_workbench",
            ValidationRun.owner_id == raw.id,
            ValidationRun.status == "succeeded",
        )
        .order_by(
            ValidationRun.completed_at.desc(),
            ValidationRun.started_at.desc(),
            ValidationRun.id.desc(),
        )
        .limit(1)
    ).first()
    if run is None:
        raise _not_found(
            "raw_validation_run_not_found",
            "No successful Raw validation run exists for this workbench.",
        )
    return _latest_validation_run_response(run)


def _latest_validation_run_response(run: ValidationRun) -> RawLatestValidationRunResponse:
    """Map a resolved succeeded Raw validation run to its reference response.

    ``raw_revision`` is read from the run's input manifest; it is advisory and
    becomes ``None`` when the manifest predates the field or holds a non-integer
    value, so the UI never pins a bogus revision.
    """

    raw_revision = run.input_manifest.get("raw_revision")
    return RawLatestValidationRunResponse(
        validation_run_id=run.id,
        raw_revision=_manifest_raw_revision(raw_revision),
        completed_at=run.completed_at,
        input_fingerprint=run.input_fingerprint,
    )


def _manifest_raw_revision(value: object) -> int | None:
    """Coerce a manifest ``raw_revision`` to an int, or ``None`` when absent.

    Booleans are rejected (``bool`` is an ``int`` subclass) so a stray ``True``
    never becomes revision ``1``; any non-integer value is treated as absent so
    the UI shows the run without pinning a bogus revision.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


@router.post(
    "/raw/{raw_id}/reconcile",
    response_model=ReconciliationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reconcile_raw_source_schema(
    raw_id: UUID,
    command: RawReconcileRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReconciliationResponse:
    """Queue an immutable comparison of maintained metadata and exact source bytes."""

    raw = _raw(session, registry, raw_id, principal)
    if raw.revision != command.expected_raw_revision:
        raise ProblemException(
            status_code=409,
            code="stale_raw_reconciliation_input",
            title="Raw reconciliation input is stale",
            detail="The expected Raw revision is not current.",
        )
    context = _handler(registry).context_snapshot(session, raw.id, raw.study_id)
    inputs = [
        ReconciliationInput(entity_type="raw_workbench", entity_id=raw.id, revision=raw.revision)
    ]
    for dataset in cast(list[dict[str, object]], context["datasets"]):
        source = cast(dict[str, object], dataset["source_file"])
        inputs.append(
            ReconciliationInput(
                artifact_id=UUID(str(source["artifact_id"])),
                checksum=str(source["sha256"]),
            )
        )
    request = ReconciliationCreate(
        study_id=raw.study_id,
        reconciliation_type="raw_source_schema",
        reconciliation_version="1.0.0",
        inputs=tuple(inputs),
        expected_input_fingerprint="0" * 64,
    )
    request_payload = request.model_dump(mode="json", exclude={"expected_input_fingerprint"})
    request.expected_input_fingerprint = fingerprint(request_payload)
    return create_reconciliation(request, response, session, registry, principal, idempotency_key)


@router.post(
    "/raw/{raw_id}/artifacts/fingerprint",
    response_model=RawArtifactFingerprintResponse,
)
def preview_raw_artifact_fingerprint(
    raw_id: UUID,
    command: RawArtifactFingerprintRequest,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RawArtifactFingerprintResponse:
    """Return the exact resolved build-input fingerprint for a Raw build.

    Read-only preview that reuses the same resolution and canonicalization as
    the build endpoint so the returned value is accepted as
    ``expected_input_fingerprint`` by ``POST /raw/{raw_id}/artifacts``.
    """

    raw = _raw(session, registry, raw_id, principal)
    unsupported = sorted(set(command.artifact_types) - set(RAW_ARTIFACT_TYPES))
    if unsupported:
        raise ProblemException(
            status_code=422,
            code="artifact_type_unsupported",
            title="Artifact type is unsupported",
            detail=f"Unsupported Raw artifact types: {', '.join(unsupported)}",
        )
    input_fingerprint, _, _, _ = resolve_build_fingerprint(
        session,
        registry,
        study_id=raw.study_id,
        owner_type="raw_workbench",
        owner_id=raw.id,
        artifact_types=command.artifact_types,
        options={},
    )
    return RawArtifactFingerprintResponse(input_fingerprint=input_fingerprint)


@router.post(
    "/raw/{raw_id}/artifacts",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_raw_artifacts(
    raw_id: UUID,
    command: RawArtifactRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    raw = _raw(session, registry, raw_id, principal)
    unsupported = sorted(set(command.artifact_types) - set(RAW_ARTIFACT_TYPES))
    if unsupported:
        raise ProblemException(
            status_code=422,
            code="artifact_type_unsupported",
            title="Artifact type is unsupported",
            detail=f"Unsupported Raw artifact types: {', '.join(unsupported)}",
        )
    return create_artifact_build(
        ArtifactBuildCreate(
            study_id=raw.study_id,
            owner_type="raw_workbench",
            owner_id=raw.id,
            artifact_types=command.artifact_types,
            expected_input_fingerprint=command.expected_input_fingerprint,
            options={},
        ),
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


@router.post(
    "/raw/{raw_id}/datasets/import",
    response_model=RawDatasetImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_dataset_import(
    raw_id: UUID,
    command: RawDatasetImportRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RawDatasetImportResponse:
    """Enqueue an asynchronous JSON-array bulk dataset import."""

    raw = _raw(session, registry, raw_id, principal)
    if not idempotency_key:
        raise ProblemException(
            status_code=400,
            code="idempotency_key_required",
            title="Idempotency-Key is required",
            detail="Supply an Idempotency-Key header.",
        )
    settings: Settings = request.app.state.settings
    input_fingerprint = fingerprint(command.model_dump(mode="json"))
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.subject == principal.subject,
            IdempotencyRecord.route == "raw-dataset-import",
            IdempotencyRecord.study_id == raw.study_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != input_fingerprint:
            raise ProblemException(
                status_code=409,
                code="idempotency_key_reused",
                title="Idempotency key was reused",
                detail="The key is already bound to a different bulk import request.",
            )
        prior = session.get(RawDatasetImport, existing.resource_id)
        if prior is None:
            raise RuntimeError("idempotency record references a missing raw dataset import")
        return RawDatasetImportResponse.model_validate(prior)
    record = RawDatasetImport(
        raw_id=raw.id,
        study_id=raw.study_id,
        schema_version=command.schema_version,
        entries=[entry.model_dump(mode="json") for entry in command.entries],
        input_fingerprint=input_fingerprint,
        entry_count=len(command.entries),
        created_by=principal.subject,
    )
    session.add(record)
    session.flush()
    payload: dict[str, object] = {"import_id": str(record.id)}
    if command.expected_raw_revision is not None:
        payload["expected_raw_revision"] = command.expected_raw_revision
    session.add(
        Job(
            operation_id=record.id,
            job_type="raw_dataset_import",
            payload=payload,
            max_attempts=settings.job_max_attempts,
        )
    )
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route="raw-dataset-import",
            study_id=raw.study_id,
            key=idempotency_key,
            request_fingerprint=input_fingerprint,
            resource_type="raw_dataset_import",
            resource_id=record.id,
        )
    )
    session.commit()
    response.headers["Location"] = f"/api/v1/raw-dataset-imports/{record.id}"
    return RawDatasetImportResponse.model_validate(record)


def _require_import(session: Session, import_id: UUID, principal: Principal) -> RawDatasetImport:
    record = session.get(RawDatasetImport, import_id)
    if record is None:
        raise _not_found("raw_dataset_import_not_found", "Raw dataset import not found")
    studies.require_access(session, record.study_id, principal)
    return record


@router.get(
    "/raw-dataset-imports/{import_id}",
    response_model=RawDatasetImportResponse,
)
def get_dataset_import(
    import_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RawDatasetImportResponse:
    return RawDatasetImportResponse.model_validate(_require_import(session, import_id, principal))


@router.post(
    "/raw-dataset-imports/{import_id}/cancel",
    response_model=RawDatasetImportResponse,
)
def cancel_dataset_import(
    import_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> RawDatasetImportResponse:
    record = _require_import(session, import_id, principal)
    if record.status not in {"queued", "running"}:
        raise ProblemException(
            status_code=409,
            code="invalid_lifecycle_transition",
            title="Import cannot be cancelled",
            detail="Only queued or running imports can be cancelled.",
        )
    record.status = "cancelled"
    record.completed_at = utc_now()
    job = session.scalar(select(Job).where(Job.operation_id == record.id))
    if job is not None:
        job.cancellation_requested_at = utc_now()
    session.commit()
    return RawDatasetImportResponse.model_validate(record)


def _not_found(code: str, title: str) -> ProblemException:
    return ProblemException(status_code=404, code=code, title=title, detail=title)
