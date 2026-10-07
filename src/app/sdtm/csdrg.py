"""Versioned manual cSDRG authoring over exact SDTM evidence."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
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
from app.reconciliation.models import ReconciliationRun
from app.sdtm.contracts import (
    CsdrgDatasetFact,
    CsdrgNarrativeSection,
    SdtmCsdrgInitialize,
    SdtmCsdrgModel,
    SdtmDefineModel,
)
from app.sdtm.models import (
    SdtmCsdrgRevision,
    SdtmDefineRevision,
    SdtmSpecificationRevision,
    SdtmWorkbench,
)
from app.studies.service import StudyService
from app.validation.models import ValidationRun
from app.validation.routes import ValidationRunResponse

router = APIRouter(tags=["sdtm-csdrg"])
studies = StudyService()
artifacts = ArtifactService()
CSDRG_ARTIFACT_TYPES = ("sdtm_csdrg_docx", "sdtm_csdrg_pdf")
REQUIRED_NARRATIVE_SECTIONS = (
    ("study_data_overview", "Study Data Overview"),
    ("standards_and_versions", "Standards and Versions"),
    ("trial_design", "Trial Design"),
    ("domain_notes", "Domain Notes"),
    ("conformance_issues", "Conformance Issues"),
    ("sponsor_defined_domains", "Sponsor-Defined Domains"),
    ("controlled_terminology", "Controlled Terminology"),
    ("data_dependencies", "Data Dependencies"),
    ("reviewer_guidance", "Reviewer Guidance"),
)


class CsdrgResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    aggregate_id: UUID
    study_id: UUID
    revision: int
    schema_version: str
    specification_revision: int
    define_revision: int
    reconciliation_run_id: UUID
    payload: dict[str, object]
    fingerprint: str
    created_by: str
    created_at: datetime


class CsdrgArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_types: tuple[str, ...] = CSDRG_ARTIFACT_TYPES

    @field_validator("artifact_types")
    @classmethod
    def valid_artifact_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if (
            not value
            or len(value) != len(set(value))
            or not set(value) <= set(CSDRG_ARTIFACT_TYPES)
        ):
            raise ValueError("artifact_types must contain unique supported cSDRG artifact types")
        return value


def _workbench(session: Session, sdtm_id: UUID, principal: Principal) -> SdtmWorkbench:
    record = session.get(SdtmWorkbench, sdtm_id)
    if record is None:
        raise _problem(404, "sdtm_not_found", "The SDTM workbench does not exist.")
    studies.require_access(session, record.study_id, principal)
    return record


def _latest_csdrg(session: Session, sdtm_id: UUID) -> SdtmCsdrgRevision | None:
    return session.scalar(
        select(SdtmCsdrgRevision)
        .where(SdtmCsdrgRevision.aggregate_id == sdtm_id)
        .order_by(SdtmCsdrgRevision.revision.desc())
    )


def _define(session: Session, workbench: SdtmWorkbench, define_revision: int) -> SdtmDefineRevision:
    record = session.scalar(
        select(SdtmDefineRevision).where(
            SdtmDefineRevision.aggregate_id == workbench.id,
            SdtmDefineRevision.revision == define_revision,
        )
    )
    if record is None:
        raise _problem(409, "csdrg_define_misaligned", "Select an existing Define revision.")
    current = session.scalar(
        select(SdtmDefineRevision)
        .where(SdtmDefineRevision.aggregate_id == workbench.id)
        .order_by(SdtmDefineRevision.revision.desc())
    )
    if current is None or current.id != record.id:
        raise _problem(
            409, "csdrg_define_misaligned", "cSDRG must bind the current Define revision."
        )
    return record


def _reconciliation(
    session: Session,
    workbench: SdtmWorkbench,
    define: SdtmDefineRevision,
    reconciliation_run_id: UUID,
) -> ReconciliationRun:
    run = session.get(ReconciliationRun, reconciliation_run_id)
    define_input = any(
        item.get("entity_type") == "sdtm_define"
        and item.get("entity_id") == str(define.id)
        and int(str(item.get("revision", 0))) == define.revision
        for item in (run.inputs if run is not None else [])
    )
    selected_checksums = {
        str(item.get("artifact_id")): str(item.get("checksum"))
        for item in (run.inputs if run is not None else [])
        if item.get("artifact_id") is not None
    }
    expected_checksums: dict[str, str] = {}
    for artifact_id in define.output_artifact_ids:
        artifact = session.get(Artifact, UUID(artifact_id))
        if artifact is not None:
            expected_checksums[str(artifact.id)] = artifact.sha256
    if (
        run is None
        or run.study_id != workbench.study_id
        or run.reconciliation_type != "sdtm_define_outputs"
        or run.status != "succeeded"
        or run.error_count != 0
        or not define_input
        or selected_checksums != expected_checksums
    ):
        raise _problem(
            409,
            "successful_csdrg_reconciliation_required",
            "Use a successful zero-error reconciliation for this exact Define and output set.",
        )
    return run


def _facts(session: Session, define: SdtmDefineRevision) -> tuple[CsdrgDatasetFact, ...]:
    model = SdtmDefineModel.model_validate(define.payload)
    leaves = {item.id: item for item in model.leaves}
    result: list[CsdrgDatasetFact] = []
    for dataset in sorted(model.datasets, key=lambda item: item.name):
        leaf = leaves.get(dataset.leaf_id or "")
        if leaf is None or leaf.artifact_id is None:
            raise _problem(
                422, "csdrg_define_leaf_missing", "Every cSDRG dataset needs an XPT leaf."
            )
        artifact = session.get(Artifact, leaf.artifact_id)
        manifest = artifact.manifest if artifact is not None else {}
        variables = manifest.get("variables")
        if (
            artifact is None
            or str(artifact.id) not in define.output_artifact_ids
            or artifact.status != "available"
            or artifact.sha256 != leaf.checksum
            or artifact.artifact_type != "sdtm_dataset_xpt"
            or manifest.get("dataset") != dataset.name
            or not isinstance(manifest.get("row_count"), int)
            or not isinstance(variables, list)
            or not variables
        ):
            raise _problem(
                422,
                "csdrg_output_evidence_invalid",
                "cSDRG factual rows require available exact reconciled XPT evidence.",
            )
        result.append(
            CsdrgDatasetFact(
                dataset=dataset.name,
                label=dataset.label,
                structure=dataset.structure,
                xpt_artifact_id=artifact.id,
                checksum=artifact.sha256,
                row_count=int(str(manifest["row_count"])),
                variable_count=len(variables),
            )
        )
    return tuple(result)


def _require_current_inputs(
    session: Session, workbench: SdtmWorkbench, model: SdtmCsdrgModel
) -> tuple[SdtmDefineRevision, ReconciliationRun, tuple[CsdrgDatasetFact, ...]]:
    define = _define(session, workbench, model.define_revision)
    specification = session.scalar(
        select(SdtmSpecificationRevision)
        .where(SdtmSpecificationRevision.aggregate_id == workbench.id)
        .order_by(SdtmSpecificationRevision.revision.desc())
    )
    if specification is None or model.specification_revision != specification.revision:
        raise _problem(
            409,
            "csdrg_specification_misaligned",
            "cSDRG must bind the current Specification.",
        )
    if define.specification_revision != specification.revision:
        raise _problem(
            409,
            "csdrg_define_misaligned",
            "Current Define is not aligned to the Specification.",
        )
    run = _reconciliation(session, workbench, define, model.reconciliation_run_id)
    facts = _facts(session, define)
    if model.output_artifact_ids != tuple(UUID(item) for item in define.output_artifact_ids):
        raise _problem(
            422, "csdrg_output_selection_mismatch", "cSDRG output IDs must match Define."
        )
    if model.dataset_facts != facts:
        raise _problem(
            422,
            "csdrg_factual_content_mismatch",
            (
                "Refresh factual structures with initialize; only narrative content is "
                "manually edited."
            ),
        )
    return define, run, facts


def _save(
    session: Session,
    workbench: SdtmWorkbench,
    model: SdtmCsdrgModel,
    principal: Principal,
) -> SdtmCsdrgRevision:
    current = _latest_csdrg(session, workbench.id)
    payload = model.model_dump(mode="json")
    record = SdtmCsdrgRevision(
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        revision=1 if current is None else current.revision + 1,
        schema_version=model.schema_version,
        specification_revision=model.specification_revision,
        define_revision=model.define_revision,
        reconciliation_run_id=model.reconciliation_run_id,
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
        artifact_types=CSDRG_ARTIFACT_TYPES,
    )
    return record


@router.get("/sdtms/{sdtm_id}/csdrg", response_model=CsdrgResponse)
def get_csdrg(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> CsdrgResponse:
    workbench = _workbench(session, sdtm_id, principal)
    record = _latest_csdrg(session, workbench.id)
    if record is None:
        raise _problem(404, "sdtm_csdrg_not_found", "cSDRG content has not been saved.")
    return CsdrgResponse.model_validate(record)


@router.put("/sdtms/{sdtm_id}/csdrg", response_model=CsdrgResponse)
def put_csdrg(
    sdtm_id: UUID,
    command: SdtmCsdrgModel,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CsdrgResponse:
    workbench = _workbench(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    _require_current_inputs(session, workbench, command)
    record = _save(session, workbench, command, principal)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return CsdrgResponse.model_validate(record)


@router.post("/sdtms/{sdtm_id}/csdrg/initialize", response_model=CsdrgResponse)
def initialize_csdrg(
    sdtm_id: UUID,
    command: SdtmCsdrgInitialize,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CsdrgResponse:
    workbench = _workbench(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    current_record = _latest_csdrg(session, workbench.id)
    current_revision = current_record.revision if current_record else None
    if command.expected_csdrg_revision != current_revision:
        raise _problem(409, "csdrg_revision_mismatch", "Expected cSDRG revision is stale.")
    define = _define(session, workbench, command.define_revision)
    _reconciliation(session, workbench, define, command.reconciliation_run_id)
    current = SdtmCsdrgModel.model_validate(current_record.payload) if current_record else None
    existing_sections = {
        item.section_id: item for item in (current.narrative_sections if current else ())
    }
    for section_id, heading in REQUIRED_NARRATIVE_SECTIONS:
        if section_id not in existing_sections:
            existing_sections[section_id] = CsdrgNarrativeSection(
                section_id=section_id, heading=heading
            )
    model = SdtmCsdrgModel(
        title=current.title if current else command.title,
        version=current.version if current else command.version,
        specification_revision=define.specification_revision,
        define_revision=define.revision,
        reconciliation_run_id=command.reconciliation_run_id,
        output_artifact_ids=tuple(UUID(item) for item in define.output_artifact_ids),
        dataset_facts=_facts(session, define),
        narrative_sections=tuple(existing_sections.values()),
    )
    record = _save(session, workbench, model, principal)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return CsdrgResponse.model_validate(record)


@router.post("/sdtms/{sdtm_id}/csdrg/validate", response_model=ValidationRunResponse)
def validate_csdrg(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    workbench = _workbench(session, sdtm_id, principal)
    record = _latest_csdrg(session, workbench.id)
    if record is None:
        raise _problem(404, "sdtm_csdrg_not_found", "cSDRG content has not been saved.")
    model = SdtmCsdrgModel.model_validate(record.payload)
    _require_current_inputs(session, workbench, model)
    authored = {item.section_id for item in model.narrative_sections if item.paragraphs}
    required_ids = {section_id for section_id, _ in REQUIRED_NARRATIVE_SECTIONS}
    issues = [
        _issue("SDTM_CSDRG_REQUIRED_SECTION_MISSING", f"narrative_sections[{section_id}]")
        for section_id in sorted(required_ids - authored)
    ]
    manifest = {
        "csdrg_revision": record.revision,
        "csdrg_fingerprint": record.fingerprint,
        "specification_revision": record.specification_revision,
        "define_revision": record.define_revision,
        "reconciliation_run_id": str(record.reconciliation_run_id),
        "output_artifact_ids": [str(item) for item in model.output_artifact_ids],
    }
    run = ValidationRun(
        study_id=workbench.study_id,
        module_key="sdtm",
        owner_type="sdtm_csdrg",
        owner_id=record.id,
        status="succeeded",
        validator_name="sdtm-csdrg-validator",
        validator_version="1.0.0",
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


@router.post(
    "/sdtms/{sdtm_id}/csdrg/artifacts",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_csdrg_artifacts(
    sdtm_id: UUID,
    command: CsdrgArtifactRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    workbench = _workbench(session, sdtm_id, principal)
    return create_artifact_build(
        ArtifactBuildCreate(
            study_id=workbench.study_id,
            owner_type="sdtm_workbench",
            owner_id=workbench.id,
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


def _issue(code: str, field_path: str) -> dict[str, object]:
    return {
        "id": f"{code}:{field_path}",
        "code": code,
        "severity": "error",
        "message": "A required manually authored cSDRG narrative section is missing.",
        "suggestion": "Author the required narrative section and validate a new revision.",
        "module": "sdtm",
        "entity_type": "sdtm_csdrg",
        "entity_id": None,
        "field_path": field_path,
        "dataset": None,
        "variable": None,
        "artifact_id": None,
    }


def _problem(status_code: int, code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=status_code, code=code, title="cSDRG request cannot be completed", detail=detail
    )
