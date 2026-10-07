"""Version-neutral SDTM Define metadata authoring and non-destructive initialization."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_session
from app.artifacts.builds import ArtifactBuildCreate, ArtifactBuildResponse, create_artifact_build
from app.artifacts.models import Artifact
from app.artifacts.service import ArtifactService
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.kernel.registry import ModuleRegistry
from app.reconciliation.routes import (
    ReconciliationCreate,
    ReconciliationInput,
    ReconciliationResponse,
    create_reconciliation,
)
from app.sdtm.contracts import (
    DefineDataset,
    DefineItem,
    DefineLeaf,
    DefineOrigin,
    SdtmDefineInitialize,
    SdtmDefineModel,
    SdtmSpecification,
    SdtmVariable,
)
from app.sdtm.define_xml import define_schema_fingerprint, render_define_xml
from app.sdtm.models import (
    SdtmAcrfAnnotation,
    SdtmDefineRevision,
    SdtmSpecificationRevision,
    SdtmWorkbench,
)
from app.studies.service import StudyService
from app.validation.models import ValidationRun
from app.validation.routes import ValidationRunResponse

router = APIRouter(tags=["sdtm-define"])
studies = StudyService()
artifacts = ArtifactService()
DEFINE_DEPENDENT_ARTIFACT_TYPES = (
    "sdtm_define_xml_20",
    "sdtm_define_xml_21",
    "sdtm_csdrg_docx",
    "sdtm_csdrg_pdf",
)


class DefineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    aggregate_id: UUID
    study_id: UUID
    revision: int
    schema_version: str
    specification_revision: int
    output_artifact_ids: list[str]
    payload: dict[str, object]
    fingerprint: str
    created_by: str
    created_at: datetime


class DefineReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    define_revision: int
    expected_define_fingerprint: str


class DefineArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    versions: tuple[Literal["2.0", "2.1"], ...] = Field(default=("2.0", "2.1"), min_length=1)

    @field_validator("versions")
    @classmethod
    def unique_versions(
        cls, value: tuple[Literal["2.0", "2.1"], ...]
    ) -> tuple[Literal["2.0", "2.1"], ...]:
        if len(value) != len(set(value)):
            raise ValueError("Define-XML versions must be unique")
        return value


def _workbench(session: Session, sdtm_id: UUID, principal: Principal) -> SdtmWorkbench:
    record = session.get(SdtmWorkbench, sdtm_id)
    if record is None:
        raise _not_found("sdtm_not_found", "The SDTM workbench does not exist.")
    studies.require_access(session, record.study_id, principal)
    return record


def _latest_define(session: Session, sdtm_id: UUID) -> SdtmDefineRevision | None:
    return session.scalar(
        select(SdtmDefineRevision)
        .where(SdtmDefineRevision.aggregate_id == sdtm_id)
        .order_by(SdtmDefineRevision.revision.desc())
    )


def _latest_specification(session: Session, sdtm_id: UUID) -> SdtmSpecificationRevision:
    record = session.scalar(
        select(SdtmSpecificationRevision)
        .where(SdtmSpecificationRevision.aggregate_id == sdtm_id)
        .order_by(SdtmSpecificationRevision.revision.desc())
    )
    if record is None:
        raise _conflict(
            "sdtm_specification_required", "Save the SDTM Specification before authoring Define."
        )
    return record


def _current_define_validation(
    session: Session,
    record: SdtmDefineRevision,
    specification_revision: int,
) -> ValidationRun | None:
    schema_fingerprints = {
        "2.0": define_schema_fingerprint("2.0"),
        "2.1": define_schema_fingerprint("2.1"),
    }
    run = session.scalar(
        select(ValidationRun)
        .where(
            ValidationRun.module_key == "sdtm",
            ValidationRun.owner_type == "sdtm_define",
            ValidationRun.owner_id == record.id,
            ValidationRun.status == "succeeded",
            ValidationRun.error_count == 0,
        )
        .order_by(ValidationRun.created_at.desc())
    )
    if run is None:
        return None
    manifest = run.input_manifest
    if (
        manifest.get("define_revision") != record.revision
        or manifest.get("define_fingerprint") != record.fingerprint
        or manifest.get("specification_revision") != specification_revision
        or manifest.get("output_artifact_ids") != record.output_artifact_ids
        or manifest.get("define_xml_schema_fingerprints") != schema_fingerprints
    ):
        return None
    return run


def _output_artifacts(
    session: Session,
    workbench: SdtmWorkbench,
    specification_revision: int,
    artifact_ids: tuple[UUID, ...],
) -> dict[str, Artifact]:
    outputs: dict[str, Artifact] = {}
    for artifact_id in artifact_ids:
        artifact = session.get(Artifact, artifact_id)
        dataset = artifact.manifest.get("dataset") if artifact is not None else None
        if (
            artifact is None
            or artifact.study_id != workbench.study_id
            or artifact.module_key != "sdtm"
            or artifact.owner_type != "sdtm_workbench"
            or artifact.owner_id != workbench.id
            or artifact.artifact_type != "sdtm_dataset_xpt"
            or artifact.status != "available"
            or artifact.source_specification_revision != specification_revision
            or not isinstance(dataset, str)
        ):
            raise _unprocessable(
                "define_output_artifact_invalid",
                "Every Define output must be an available exact SDTM XPT for this Specification.",
            )
        if dataset in outputs:
            raise _unprocessable(
                "define_output_artifact_duplicate",
                "Select at most one XPT artifact for each SDTM dataset.",
            )
        outputs[dataset] = artifact
    return outputs


def _origin(variable: SdtmVariable) -> DefineOrigin:
    allowed = {"Assigned", "Collected", "Derived", "Predecessor", "Protocol"}
    origin_type = variable.origin if variable.origin in allowed else None
    if origin_type is None:
        origin_type = "Derived" if variable.derived else "Assigned"
    return DefineOrigin(origin_type=origin_type, description=variable.origin)


def _item(domain: str, variable: SdtmVariable) -> DefineItem:
    return DefineItem(
        oid=f"IT.{domain}.{variable.name}",
        name=variable.name,
        label=variable.label,
        data_type="text" if variable.data_type == "character" else "float",
        length=variable.length,
        role=variable.role,
        mandatory=variable.core == "Req",
        origin=_origin(variable),
    )


def _initialize_model(
    current: SdtmDefineModel | None,
    command: SdtmDefineInitialize,
    specification_record: SdtmSpecificationRevision,
    outputs: dict[str, Artifact],
) -> SdtmDefineModel:
    specification = SdtmSpecification.model_validate(specification_record.payload)
    leaves = list(current.leaves if current is not None else ())
    leaf_by_dataset = {
        leaf.id.removeprefix("LF."): leaf for leaf in leaves if leaf.id.startswith("LF.")
    }
    datasets = {item.name: item for item in (current.datasets if current is not None else ())}
    for domain in specification.domains:
        artifact = outputs.get(domain.code)
        leaf = leaf_by_dataset.get(domain.code)
        if artifact is not None and leaf is None:
            leaf = DefineLeaf(
                id=f"LF.{domain.code}",
                title=domain.label,
                href=domain.expected_output_name,
                artifact_id=artifact.id,
                checksum=artifact.sha256,
            )
            leaves.append(leaf)
        existing = datasets.get(domain.code)
        if existing is None:
            datasets[domain.code] = DefineDataset(
                oid=f"IG.{domain.code}",
                name=domain.code,
                label=domain.label,
                dataset_class=domain.domain_class,
                structure=domain.structure,
                leaf_id=leaf.id if leaf is not None else None,
                items=tuple(_item(domain.code, variable) for variable in domain.variables),
            )
            continue
        existing_names = {item.name for item in existing.items}
        additions = tuple(
            _item(domain.code, variable)
            for variable in domain.variables
            if variable.name not in existing_names
        )
        changes: dict[str, object] = {}
        if additions:
            changes["items"] = (*existing.items, *additions)
        if existing.leaf_id is None and leaf is not None:
            changes["leaf_id"] = leaf.id
        if changes:
            datasets[domain.code] = existing.model_copy(update=changes)
    values = {
        "schema_version": "1.0.0",
        "specification_revision": specification_record.revision,
        "study_oid": current.study_oid if current else command.study_oid,
        "metadata_version_oid": (
            current.metadata_version_oid if current else command.metadata_version_oid
        ),
        "name": current.name if current else command.name,
        "description": current.description if current else command.description,
        "standard_name": current.standard_name if current else command.standard_name,
        "standard_version": current.standard_version if current else command.standard_version,
        "output_artifact_ids": command.output_artifact_ids,
        "datasets": tuple(datasets[name] for name in sorted(datasets)),
        "leaves": tuple(sorted(leaves, key=lambda item: item.id)),
        "document_references": current.document_references if current else (),
        "codelists": current.codelists if current else (),
        "methods": current.methods if current else (),
        "comments": current.comments if current else (),
    }
    return SdtmDefineModel.model_validate(values)


def _validate_external_references(
    session: Session,
    workbench: SdtmWorkbench,
    model: SdtmDefineModel,
    outputs: dict[str, Artifact],
) -> None:
    selected_outputs = {artifact.id: artifact for artifact in outputs.values()}
    for leaf in model.leaves:
        if leaf.artifact_id is None:
            continue
        artifact = selected_outputs.get(leaf.artifact_id)
        if artifact is None or leaf.checksum != artifact.sha256:
            raise _unprocessable(
                "define_leaf_artifact_invalid",
                "Define leaves must resolve to an exact selected XPT artifact and checksum.",
            )
    for document in model.document_references:
        if document.source_artifact_id is None:
            continue
        artifact = session.get(Artifact, document.source_artifact_id)
        if (
            artifact is None
            or artifact.study_id != workbench.study_id
            or artifact.status != "available"
        ):
            raise _unprocessable(
                "define_document_reference_invalid",
                "Define document references must resolve to available artifacts in this study.",
            )
    for dataset in model.datasets:
        for item in dataset.items:
            for annotation_id in item.origin.acrf_annotation_ids:
                annotation = session.get(SdtmAcrfAnnotation, annotation_id)
                if (
                    annotation is None
                    or annotation.sdtm_id != workbench.id
                    or annotation.status == "deleted"
                ):
                    raise _unprocessable(
                        "define_acrf_reference_unresolved",
                        (
                            "Define aCRF references must resolve to active annotations in this "
                            "workbench."
                        ),
                    )


def _save(
    session: Session,
    workbench: SdtmWorkbench,
    model: SdtmDefineModel,
    principal: Principal,
) -> SdtmDefineRevision:
    current = _latest_define(session, workbench.id)
    payload = model.model_dump(mode="json")
    record = SdtmDefineRevision(
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        revision=1 if current is None else current.revision + 1,
        schema_version=model.schema_version,
        specification_revision=model.specification_revision,
        output_artifact_ids=[str(item) for item in model.output_artifact_ids],
        payload=payload,
        fingerprint=fingerprint(payload),
        created_by=principal.subject,
    )
    session.add(record)
    workbench.revision += 1
    artifacts.mark_owner_stale(
        session,
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        artifact_types=DEFINE_DEPENDENT_ARTIFACT_TYPES,
    )
    return record


@router.get("/sdtms/{sdtm_id}/define", response_model=DefineResponse)
def get_define(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> DefineResponse:
    workbench = _workbench(session, sdtm_id, principal)
    record = _latest_define(session, workbench.id)
    if record is None:
        raise _not_found("sdtm_define_not_found", "SDTM Define metadata has not been saved.")
    return DefineResponse.model_validate(record)


@router.put("/sdtms/{sdtm_id}/define", response_model=DefineResponse)
def put_define(
    sdtm_id: UUID,
    command: SdtmDefineModel,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DefineResponse:
    workbench = _workbench(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    specification = _latest_specification(session, workbench.id)
    if command.specification_revision != specification.revision:
        raise _conflict(
            "define_specification_misaligned",
            "Define must bind the current exact SDTM Specification revision.",
        )
    outputs = _output_artifacts(
        session, workbench, specification.revision, command.output_artifact_ids
    )
    _validate_external_references(session, workbench, command, outputs)
    record = _save(session, workbench, command, principal)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return DefineResponse.model_validate(record)


@router.post("/sdtms/{sdtm_id}/define/initialize", response_model=DefineResponse)
def initialize_define(
    sdtm_id: UUID,
    command: SdtmDefineInitialize,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DefineResponse:
    workbench = _workbench(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    current_record = _latest_define(session, workbench.id)
    current_revision = current_record.revision if current_record else None
    if command.expected_define_revision != current_revision:
        raise _conflict(
            "define_revision_mismatch",
            "The expected Define revision does not match the current saved revision.",
        )
    current = SdtmDefineModel.model_validate(current_record.payload) if current_record else None
    if (
        current is not None
        and current.output_artifact_ids
        and (current.output_artifact_ids != command.output_artifact_ids)
    ):
        raise _conflict(
            "define_output_selection_conflict",
            "Initialization cannot replace an existing exact output selection; use PUT.",
        )
    specification = _latest_specification(session, workbench.id)
    outputs = _output_artifacts(
        session, workbench, specification.revision, command.output_artifact_ids
    )
    model = _initialize_model(current, command, specification, outputs)
    _validate_external_references(session, workbench, model, outputs)
    record = _save(session, workbench, model, principal)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return DefineResponse.model_validate(record)


@router.post("/sdtms/{sdtm_id}/define/validate", response_model=ValidationRunResponse)
def validate_define(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    workbench = _workbench(session, sdtm_id, principal)
    record = _latest_define(session, workbench.id)
    if record is None:
        raise _not_found("sdtm_define_not_found", "SDTM Define metadata has not been saved.")
    specification_record = _latest_specification(session, workbench.id)
    model = SdtmDefineModel.model_validate(record.payload)
    specification = SdtmSpecification.model_validate(specification_record.payload)
    issues: list[dict[str, object]] = []
    if model.specification_revision != specification_record.revision:
        issues.append(_issue("define_specification_misaligned", "specification_revision"))
    defined = {(dataset.name, item.name) for dataset in model.datasets for item in dataset.items}
    required = {
        (domain.code, variable.name)
        for domain in specification.domains
        for variable in domain.variables
    }
    for domain, variable in sorted(required - defined):
        issues.append(
            _issue(
                "define_item_missing",
                f"datasets[{domain}].items[{variable}]",
                dataset=domain,
                variable=variable,
            )
        )
    _output_artifacts(session, workbench, specification_record.revision, model.output_artifact_ids)
    for dataset in model.datasets:
        for item in dataset.items:
            for annotation_id in item.origin.acrf_annotation_ids:
                annotation = session.get(SdtmAcrfAnnotation, annotation_id)
                if (
                    annotation is None
                    or annotation.sdtm_id != workbench.id
                    or annotation.status == "deleted"
                ):
                    issues.append(
                        _issue(
                            "define_acrf_reference_unresolved",
                            f"datasets[{dataset.name}].items[{item.name}].origin",
                            dataset=dataset.name,
                            variable=item.name,
                        )
                    )
    schema_fingerprints = {
        "2.0": define_schema_fingerprint("2.0"),
        "2.1": define_schema_fingerprint("2.1"),
    }
    for version in ("2.0", "2.1"):
        try:
            render_define_xml(model, version)
        except ProblemException:
            issues.append(
                _issue(
                    f"define_xml_{version.replace('.', '')}_invalid",
                    "payload",
                )
            )
    manifest = {
        "sdtm_revision": workbench.revision,
        "define_revision": record.revision,
        "define_fingerprint": record.fingerprint,
        "specification_revision": specification_record.revision,
        "output_artifact_ids": record.output_artifact_ids,
        "define_xml_schema_fingerprints": schema_fingerprints,
    }
    run = ValidationRun(
        study_id=workbench.study_id,
        module_key="sdtm",
        owner_type="sdtm_define",
        owner_id=record.id,
        status="succeeded",
        validator_name="sdtm-define-model-validator",
        validator_version="1.1.0",
        input_fingerprint=fingerprint(manifest),
        input_manifest=manifest,
        started_at=utc_now(),
        completed_at=utc_now(),
        error_count=len(issues),
        warning_count=0,
        info_count=0,
        issues=issues,
        report_artifact_ids=[],
        created_by=principal.subject,
    )
    session.add(run)
    session.commit()
    return ValidationRunResponse.model_validate(run)


@router.get("/sdtms/{sdtm_id}/define/render")
def render_define(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    version: Literal["2.0", "2.1"] = "2.1",
) -> Response:
    """Render one validated revision through a locally pinned Define XSD."""

    workbench = _workbench(session, sdtm_id, principal)
    record = _latest_define(session, workbench.id)
    if record is None:
        raise _not_found("sdtm_define_not_found", "SDTM Define metadata has not been saved.")
    specification = _latest_specification(session, workbench.id)
    if _current_define_validation(session, record, specification.revision) is None:
        raise _conflict(
            "successful_validation_required",
            "Validate the current Define revision against both pinned XSD versions first.",
        )
    data = render_define_xml(SdtmDefineModel.model_validate(record.payload), version)
    return Response(
        content=data,
        media_type="application/xml",
        headers={"Content-Disposition": f'inline; filename="define-{version}.xml"'},
    )


@router.post(
    "/sdtms/{sdtm_id}/define/artifacts",
    response_model=ArtifactBuildResponse,
    status_code=202,
)
def create_define_artifacts(
    sdtm_id: UUID,
    command: DefineArtifactRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    """Queue immutable Define-XML 2.0 and/or 2.1 artifacts from one authored model."""

    workbench = _workbench(session, sdtm_id, principal)
    artifact_types = tuple(
        "sdtm_define_xml_20" if version == "2.0" else "sdtm_define_xml_21"
        for version in command.versions
    )
    return create_artifact_build(
        ArtifactBuildCreate(
            study_id=workbench.study_id,
            owner_type="sdtm_workbench",
            owner_id=workbench.id,
            artifact_types=artifact_types,
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
    "/sdtms/{sdtm_id}/define/reconcile",
    response_model=ReconciliationResponse,
    status_code=202,
)
def reconcile_define(
    sdtm_id: UUID,
    command: DefineReconcileRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReconciliationResponse:
    workbench = _workbench(session, sdtm_id, principal)
    define = session.scalar(
        select(SdtmDefineRevision).where(
            SdtmDefineRevision.aggregate_id == workbench.id,
            SdtmDefineRevision.revision == command.define_revision,
        )
    )
    if define is None or define.fingerprint != command.expected_define_fingerprint:
        raise _conflict(
            "stale_define_reconciliation_input",
            "The selected exact Define revision or fingerprint does not match.",
        )
    inputs = [
        ReconciliationInput(
            entity_type="sdtm_define", entity_id=define.id, revision=define.revision
        )
    ]
    for artifact_id in define.output_artifact_ids:
        artifact = session.get(Artifact, UUID(artifact_id))
        if artifact is None:
            raise _unprocessable(
                "define_output_artifact_invalid", "A selected Define XPT artifact is missing."
            )
        inputs.append(ReconciliationInput(artifact_id=artifact.id, checksum=artifact.sha256))
    annotations = session.scalars(
        select(SdtmAcrfAnnotation).where(
            SdtmAcrfAnnotation.sdtm_id == workbench.id,
            SdtmAcrfAnnotation.status != "deleted",
        )
    )
    inputs.extend(
        ReconciliationInput(
            entity_type="sdtm_acrf_annotation",
            entity_id=annotation.id,
            revision=annotation.revision,
        )
        for annotation in annotations
    )
    request = ReconciliationCreate(
        study_id=workbench.study_id,
        reconciliation_type="sdtm_define_outputs",
        reconciliation_version="1.0.0",
        inputs=tuple(inputs),
        expected_input_fingerprint="0" * 64,
    )
    request_payload = request.model_dump(mode="json", exclude={"expected_input_fingerprint"})
    request.expected_input_fingerprint = fingerprint(request_payload)
    return create_reconciliation(request, response, session, registry, principal, idempotency_key)


def _issue(
    code: str,
    field_path: str,
    *,
    dataset: str | None = None,
    variable: str | None = None,
) -> dict[str, object]:
    return {
        "id": f"{code}:{field_path}",
        "code": code,
        "severity": "error",
        "message": "Define metadata does not match its exact authored inputs.",
        "suggestion": "Initialize missing factual structures or correct the authored reference.",
        "module": "sdtm",
        "entity_type": "sdtm_define",
        "entity_id": None,
        "field_path": field_path,
        "dataset": dataset,
        "variable": variable,
        "artifact_id": None,
    }


def _not_found(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=404, code=code, title="Define resource not found", detail=detail
    )


def _unprocessable(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=422, code=code, title="Define content is invalid", detail=detail
    )


def _conflict(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=409, code=code, title="Define state conflict", detail=detail
    )
