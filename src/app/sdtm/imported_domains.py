"""Acceptance of immutable externally produced SDTM XPT domain revisions."""

import hashlib
from datetime import datetime
from pathlib import PurePath
from typing import Annotated, Protocol, cast
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_object_storage, get_session
from app.artifacts.service import ArtifactService, store_bytes_object
from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.idempotency import IdempotencyRecord
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry
from app.sdtm.contracts import (
    SdtmImportedDomainCreate,
    SdtmImportedSchema,
    SdtmSpecification,
)
from app.sdtm.models import SdtmImportedDomainRevision, SdtmOutputSelection, SdtmWorkbench
from app.sdtm.service import SdtmCapability, context_from_record
from app.sdtm.xpt import inspect_xpt_v5
from app.studies.service import StudyService
from app.validation.contracts import IssueSeverity, ValidationIssue
from app.validation.models import ValidationRun

router = APIRouter(tags=["sdtm"])
studies = StudyService()
artifacts = ArtifactService()
_ISSUE_NAMESPACE = UUID("d5126ef5-0590-49fa-941d-2e56ed31b88b")


class _AdamConsumerStaleness(Protocol):
    def mark_sdtm_refresh(self, session: Session, sdtm_id: UUID) -> tuple[UUID, ...]: ...


class ImportedDomainResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    aggregate_id: UUID
    domain: str
    revision: int
    specification_revision: int
    source_file_id: UUID
    artifact_id: UUID
    validation_run_id: UUID
    selected_as_source: bool
    state: str
    alignment_state: str
    alignment_reasons: tuple[str, ...]
    extracted_schema: dict[str, object]
    issues: tuple[dict[str, object], ...]
    fingerprint: str
    created_by: str
    created_at: datetime

    @classmethod
    def from_record(
        cls, record: SdtmImportedDomainRevision, *, selected_as_source: bool
    ) -> "ImportedDomainResponse":
        return cls(
            id=record.id,
            aggregate_id=record.aggregate_id,
            domain=record.domain_code,
            revision=record.revision,
            specification_revision=record.specification_revision,
            source_file_id=record.source_file_id,
            artifact_id=record.artifact_id,
            validation_run_id=record.validation_run_id,
            selected_as_source=selected_as_source,
            state=record.state,
            alignment_state="current" if record.state == "aligned" else "alignment_required",
            alignment_reasons=tuple(record.alignment_reasons or ()),
            extracted_schema=record.extracted_schema,
            issues=tuple(record.issues),
            fingerprint=record.fingerprint,
            created_by=record.created_by,
            created_at=record.created_at,
        )


def _handler(registry: ModuleRegistry) -> SdtmCapability:
    return cast(SdtmCapability, registry.require_handler("sdtm", ModuleCapability.DEPENDENCIES))


def _workbench(session: Session, sdtm_id: UUID, principal: Principal) -> SdtmWorkbench:
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


def _issue(
    *,
    code: str,
    severity: IssueSeverity,
    message: str,
    suggestion: str,
    aggregate_id: UUID,
    domain_code: str,
    variable: str | None = None,
) -> ValidationIssue:
    key = f"{aggregate_id}:{domain_code}:{code}:{variable or ''}"
    return ValidationIssue(
        id=uuid5(_ISSUE_NAMESPACE, key),
        code=code,
        severity=severity,
        message=message,
        suggestion=suggestion,
        module="sdtm",
        entity_type="sdtm_imported_domain",
        entity_id=aggregate_id,
        dataset=domain_code,
        variable=variable,
    )


def _compatibility_issues(
    aggregate_id: UUID,
    specification: SdtmSpecification,
    imported: SdtmImportedSchema,
) -> tuple[ValidationIssue, ...]:
    domain = next(item for item in specification.domains if item.code == imported.domain_code)
    declared = {item.name: item for item in domain.variables}
    observed = {item.name: item for item in imported.variables}
    issues: list[ValidationIssue] = []
    for variable in imported.variables:
        expected = declared.get(variable.name)
        if expected is None:
            issues.append(
                _issue(
                    code="sdtm_import_variable_not_in_specification",
                    severity=IssueSeverity.WARNING,
                    message=(
                        f"Imported variable {domain.code}.{variable.name} is not declared in "
                        "the current Specification."
                    ),
                    suggestion=(
                        "Review the extracted metadata and add the variable with its manually "
                        "maintained clinical attributes when it belongs in the Specification."
                    ),
                    aggregate_id=aggregate_id,
                    domain_code=domain.code,
                    variable=variable.name,
                )
            )
            continue
        if expected.data_type != variable.data_type:
            issues.append(
                _issue(
                    code="sdtm_import_variable_type_mismatch",
                    severity=IssueSeverity.ERROR,
                    message=(
                        f"Imported {domain.code}.{variable.name} is {variable.data_type}, but "
                        f"the Specification declares {expected.data_type}."
                    ),
                    suggestion="Correct the dataset or the manually reviewed Specification.",
                    aggregate_id=aggregate_id,
                    domain_code=domain.code,
                    variable=variable.name,
                )
            )
        if (
            variable.data_type == "character"
            and expected.length is not None
            and variable.length is not None
            and variable.length > expected.length
        ):
            issues.append(
                _issue(
                    code="sdtm_import_variable_length_exceeds_specification",
                    severity=IssueSeverity.ERROR,
                    message=(
                        f"Imported {domain.code}.{variable.name} has width {variable.length}, "
                        f"which exceeds the declared length {expected.length}."
                    ),
                    suggestion="Correct the dataset or increase the reviewed declared length.",
                    aggregate_id=aggregate_id,
                    domain_code=domain.code,
                    variable=variable.name,
                )
            )
        if variable.label and variable.label != expected.label:
            issues.append(
                _issue(
                    code="sdtm_import_variable_label_differs",
                    severity=IssueSeverity.INFO,
                    message=(
                        f"Imported {domain.code}.{variable.name} label differs from the "
                        "maintained Specification label."
                    ),
                    suggestion="Review the extracted label; the import does not overwrite it.",
                    aggregate_id=aggregate_id,
                    domain_code=domain.code,
                    variable=variable.name,
                )
            )
    for expected_variable in domain.variables:
        if expected_variable.name not in observed:
            issues.append(
                _issue(
                    code="sdtm_import_specification_variable_missing",
                    severity=IssueSeverity.WARNING,
                    message=(
                        f"Specification variable {domain.code}."
                        f"{expected_variable.name} is absent from the imported dataset."
                    ),
                    suggestion="Confirm whether the variable is expected for this dataset.",
                    aggregate_id=aggregate_id,
                    domain_code=domain.code,
                    variable=expected_variable.name,
                )
            )
    return tuple(issues)


@router.get(
    "/sdtms/{sdtm_id}/domains/{domain_code}/imported-dataset",
    response_model=ImportedDomainResponse,
)
def get_imported_domain(
    sdtm_id: UUID,
    domain_code: str,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ImportedDomainResponse:
    domain_code = domain_code.upper()
    workbench = _workbench(session, sdtm_id, principal)
    record = _handler(registry).latest_imported_domain(session, workbench.id, domain_code)
    if record is None:
        raise ProblemException(
            status_code=404,
            code="sdtm_imported_domain_not_found",
            title="Imported SDTM domain not found",
            detail=f"Domain '{domain_code}' has no imported dataset revision.",
        )
    source = _handler(registry).domain_source(session, workbench.id, domain_code)
    return ImportedDomainResponse.from_record(
        record,
        selected_as_source=(
            source is not None
            and source.source_type == "imported_dataset"
            and source.source_revision == record.revision
        ),
    )


@router.post(
    "/sdtms/{sdtm_id}/domains/{domain_code}/imported-dataset",
    response_model=ImportedDomainResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_domain(
    sdtm_id: UUID,
    domain_code: str,
    command: SdtmImportedDomainCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ImportedDomainResponse:
    """Accept one external XPT as the exact current provider for an SDTM domain."""

    domain_code = domain_code.upper()
    workbench = _workbench(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    if not idempotency_key:
        raise ProblemException(
            status_code=400,
            code="idempotency_key_required",
            title="Idempotency-Key is required",
            detail="Supply an Idempotency-Key header for an imported SDTM dataset.",
        )
    route = f"sdtms:{workbench.id}:domains:{domain_code}:imported-dataset"
    request_fingerprint = fingerprint(command.model_dump(mode="json"))
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
                detail="The key is already bound to a different SDTM import request.",
            )
        prior = session.get(SdtmImportedDomainRevision, existing.resource_id)
        if prior is None:
            raise RuntimeError("idempotency record references a missing SDTM import")
        response.headers["ETag"] = etag_for_revision(workbench.revision)
        prior_source_selection = _handler(registry).domain_source(
            session, workbench.id, domain_code
        )
        return ImportedDomainResponse.from_record(
            prior,
            selected_as_source=(
                prior_source_selection is not None
                and prior_source_selection.source_type == "imported_dataset"
                and prior_source_selection.source_revision == prior.revision
            ),
        )

    handler = _handler(registry)
    specification_record = handler.latest_specification(session, workbench.id)
    if specification_record is None:
        raise ProblemException(
            status_code=409,
            code="sdtm_specification_required",
            title="SDTM Specification is required",
            detail="Save a Specification before importing an SDTM dataset.",
        )
    specification = context_from_record(specification_record)
    specification_domain = next(
        (domain for domain in specification.domains if domain.code == domain_code), None
    )
    if specification_domain is None:
        raise ProblemException(
            status_code=404,
            code="sdtm_domain_unknown",
            title="SDTM domain is unknown",
            detail=f"Domain '{domain_code}' is not declared in the current Specification.",
        )
    if command.specification_revision != specification_record.revision:
        raise ProblemException(
            status_code=409,
            code="sdtm_import_specification_changed",
            title="SDTM Specification changed",
            detail="Reload the current Specification before importing the dataset.",
        )
    source_file = artifacts.require_source_file(session, command.source_file_id, principal)
    if source_file.study_id != workbench.study_id:
        raise ProblemException(
            status_code=422,
            code="sdtm_import_study_mismatch",
            title="Imported SDTM source belongs to another study",
            detail="Select a source file owned by the SDTM workbench study.",
        )
    if PurePath(source_file.filename).suffix.lower() != ".xpt":
        raise ProblemException(
            status_code=422,
            code="sdtm_import_format_unsupported",
            title="Imported SDTM format is unsupported",
            detail="Direct SDTM imports currently require a SAS XPORT v5 .xpt file.",
        )
    if source_file.sha256 != command.expected_sha256:
        raise ProblemException(
            status_code=409,
            code="sdtm_import_source_changed",
            title="Imported SDTM source changed",
            detail="The selected immutable source checksum does not match the request.",
        )
    if source_file.object_key is None:
        raise ProblemException(
            status_code=503,
            code="sdtm_import_source_unavailable",
            title="Imported SDTM source is unavailable",
            detail="Server-side import currently requires locally readable immutable bytes.",
        )
    with storage.open(source_file.object_key) as stream:
        data = stream.read()
    if hashlib.sha256(data).hexdigest() != source_file.sha256:
        raise ProblemException(
            status_code=409,
            code="sdtm_import_checksum_mismatch",
            title="Imported SDTM checksum does not match",
            detail="The immutable source bytes do not match the recorded checksum.",
        )
    extracted = inspect_xpt_v5(data, domain_code)
    issues = _compatibility_issues(workbench.id, specification, extracted)
    errors = [issue for issue in issues if issue.severity == IssueSeverity.ERROR]
    if errors:
        raise ProblemException(
            status_code=422,
            code="sdtm_import_specification_incompatible",
            title="Imported SDTM dataset is incompatible with the Specification",
            detail="Correct the dataset or the reviewed Specification before importing it.",
            issues=[issue.model_dump(mode="json") for issue in issues],
        )

    # Serialize the provider switch only after the immutable source has been inspected.
    session.execute(
        select(SdtmWorkbench.id).where(SdtmWorkbench.id == workbench.id).with_for_update()
    )
    session.refresh(workbench)
    require_matching_etag(if_match, workbench.revision)
    current_specification = handler.latest_specification(session, workbench.id)
    if (
        current_specification is None
        or current_specification.revision != specification_record.revision
    ):
        raise ProblemException(
            status_code=409,
            code="sdtm_import_specification_changed",
            title="SDTM Specification changed",
            detail="Reload the current Specification before importing the dataset.",
        )
    current = handler.latest_imported_domain(session, workbench.id, domain_code)
    import_revision = 1 if current is None else current.revision + 1
    imported_id = uuid4()
    validation_id = uuid4()
    import_fingerprint = fingerprint(
        {
            "domain_code": domain_code,
            "source_file_id": str(source_file.id),
            "source_sha256": source_file.sha256,
            "specification_revision": specification_record.revision,
            "specification_fingerprint": specification_record.fingerprint,
            "extracted_schema": extracted.model_dump(mode="json"),
        }
    )
    stored = store_bytes_object(
        storage,
        data,
        "application/x-sas-xport",
        study_id=workbench.study_id,
        external_reference=f"sdtm-import:{imported_id}",
    )
    dependency = handler.get_selection(session, workbench.id, workbench.study_id)
    now = utc_now()
    validation = ValidationRun(
        id=validation_id,
        study_id=workbench.study_id,
        module_key="sdtm",
        owner_type="sdtm_imported_domain",
        owner_id=imported_id,
        status="succeeded",
        validator_name="sdtm-imported-xpt",
        validator_version="1.0.0",
        input_fingerprint=import_fingerprint,
        input_manifest={
            "schema_version": "1.0.0",
            "domain_code": domain_code,
            "source_file_id": str(source_file.id),
            "source_sha256": source_file.sha256,
            "specification_revision": specification_record.revision,
        },
        started_at=now,
        completed_at=now,
        error_count=0,
        warning_count=sum(issue.severity == IssueSeverity.WARNING for issue in issues),
        info_count=sum(issue.severity == IssueSeverity.INFO for issue in issues),
        issues=[issue.model_dump(mode="json") for issue in issues],
        report_artifact_ids=[],
        created_by=principal.subject,
    )
    session.add(validation)
    session.flush()
    artifact = artifacts.record_artifact(
        session,
        stored=stored,
        study_id=workbench.study_id,
        module_key="sdtm",
        artifact_type="sdtm_dataset_xpt",
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        filename=f"{domain_code.lower()}.xpt",
        media_type="application/x-sas-xport",
        manifest={
            "schema_version": "1.0.0",
            "format": "SAS XPORT",
            "format_version": 5,
            "dataset": domain_code,
            "label": specification_domain.label,
            "row_count": extracted.row_count,
            "variables": [variable.model_dump(mode="json") for variable in extracted.variables],
            "origin": "external_import",
            "imported_domain_id": str(imported_id),
            "import_revision": import_revision,
            "source_file_id": str(source_file.id),
            "source_sha256": source_file.sha256,
            "extracted_schema": extracted.model_dump(mode="json"),
            "sha256": source_file.sha256,
        },
        input_fingerprint=import_fingerprint,
        dependency_selection_revision=dependency.revision,
        dependency_fingerprint=dependency.fingerprint,
        source_specification_revision=specification_record.revision,
        source_specification_fingerprint=specification_record.fingerprint,
        source_plan_type="sdtm_imported_domain",
        source_plan_revision=import_revision,
        generator_name="external-sdtm-import",
        generator_version="1.0.0",
        validation_run_id=validation.id,
        created_by=principal.subject,
    )
    record = SdtmImportedDomainRevision(
        id=imported_id,
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        domain_code=domain_code,
        revision=import_revision,
        specification_revision=specification_record.revision,
        source_file_id=source_file.id,
        artifact_id=artifact.id,
        validation_run_id=validation.id,
        state="aligned",
        alignment_reasons=[],
        extracted_schema=extracted.model_dump(mode="json"),
        issues=[issue.model_dump(mode="json") for issue in issues],
        fingerprint=import_fingerprint,
        created_by=principal.subject,
    )
    session.add(record)
    handler.select_domain_source(
        session,
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        domain_code=domain_code,
        source_type="imported_dataset",
        source_revision=record.revision,
        source_fingerprint=record.fingerprint,
        updated_by=principal.subject,
    )
    output_selection = session.scalar(
        select(SdtmOutputSelection).where(SdtmOutputSelection.aggregate_id == workbench.id)
    )
    if output_selection is not None:
        output_selection.state = "stale"
    artifacts.mark_owner_stale(
        session,
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        exclude_artifact_ids=tuple(
            imported.artifact_id
            for imported in handler.selected_imported_domains(session, workbench.id).values()
            if imported.state == "aligned"
        ),
    )
    consumer = cast(
        _AdamConsumerStaleness,
        registry.require_handler("adam", ModuleCapability.STALENESS),
    )
    for adam_id in consumer.mark_sdtm_refresh(session, workbench.id):
        artifacts.mark_owner_stale(session, owner_type="adam_workbench", owner_id=adam_id)
    workbench.revision += 1
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route=route,
            study_id=workbench.study_id,
            key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_type="sdtm_imported_domain_revision",
            resource_id=record.id,
        )
    )
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    response.headers["Location"] = (
        f"/api/v1/sdtms/{workbench.id}/domains/{domain_code}/imported-dataset"
    )
    return ImportedDomainResponse.from_record(record, selected_as_source=True)
