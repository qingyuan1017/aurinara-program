"""Versioned manual ADRG authoring over exact ADaM evidence."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adam.contracts import (
    AdamAdrgInitialize,
    AdamAdrgModel,
    AdamDefineModel,
    AdrgDatasetFact,
    AdrgExecutionFact,
    AdrgNarrativeSection,
)
from app.adam.models import (
    AdamAdrgRevision,
    AdamDefineRevision,
    AdamDerivationPlanRevision,
    AdamInputSelection,
    AdamSpecificationRevision,
    AdamWorkbench,
)
from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_session
from app.artifacts.builds import ArtifactBuildCreate, ArtifactBuildResponse, create_artifact_build
from app.artifacts.models import Artifact
from app.artifacts.service import ArtifactService
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.execution.models import ExecutionRun
from app.kernel.registry import ModuleRegistry
from app.reconciliation.models import ReconciliationRun
from app.studies.service import StudyService
from app.validation.models import ValidationRun
from app.validation.routes import ValidationRunResponse

router = APIRouter(tags=["adam-adrg"])
studies = StudyService()
artifacts = ArtifactService()
ADRG_ARTIFACT_TYPES = ("adam_adrg_docx", "adam_adrg_pdf")
REQUIRED_NARRATIVE_SECTIONS = (
    ("study_data_overview", "Study Data Overview"),
    ("standards", "Standards and Versions"),
    ("analysis_datasets", "Analysis Datasets"),
    ("analysis_variables", "Analysis Variables"),
    ("data_dependencies", "Data Dependencies"),
    ("important_derivations", "Important Derivations"),
    ("conformance_issues", "Conformance Issues"),
    ("submission_programs", "Submission Programs"),
    ("reviewer_guidance", "Reviewer Guidance"),
)


class AdrgResponse(BaseModel):
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


class AdrgArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_types: tuple[str, ...] = ADRG_ARTIFACT_TYPES

    @field_validator("artifact_types")
    @classmethod
    def supported(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)) or not set(value) <= set(ADRG_ARTIFACT_TYPES):
            raise ValueError("artifact_types must contain unique supported ADRG types")
        return value


def _problem(status_code: int, code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=status_code,
        code=code,
        title="ADRG request cannot be completed",
        detail=detail,
    )


def _workbench(session: Session, adam_id: UUID, principal: Principal) -> AdamWorkbench:
    record = session.get(AdamWorkbench, adam_id)
    if record is None:
        raise _problem(404, "adam_not_found", "The ADaM workbench does not exist.")
    studies.require_access(session, record.study_id, principal)
    return record


def _latest(session: Session, adam_id: UUID) -> AdamAdrgRevision | None:
    return session.scalar(
        select(AdamAdrgRevision)
        .where(AdamAdrgRevision.aggregate_id == adam_id)
        .order_by(AdamAdrgRevision.revision.desc())
    )


def _define(session: Session, workbench: AdamWorkbench, revision: int) -> AdamDefineRevision:
    record = session.scalar(
        select(AdamDefineRevision).where(
            AdamDefineRevision.aggregate_id == workbench.id,
            AdamDefineRevision.revision == revision,
        )
    )
    current = session.scalar(
        select(AdamDefineRevision)
        .where(AdamDefineRevision.aggregate_id == workbench.id)
        .order_by(AdamDefineRevision.revision.desc())
    )
    if record is None or current is None or current.id != record.id:
        raise _problem(409, "adrg_define_misaligned", "ADRG must bind current ADaM Define.")
    return record


def _reconciliation(
    session: Session,
    workbench: AdamWorkbench,
    define: AdamDefineRevision,
    run_id: UUID,
) -> ReconciliationRun:
    run = session.get(ReconciliationRun, run_id)
    define_input = any(
        item.get("entity_type") == "adam_define"
        and item.get("entity_id") == str(define.id)
        and int(str(item.get("revision", 0))) == define.revision
        for item in (run.inputs if run is not None else [])
    )
    checksums = {
        str(item.get("artifact_id")): str(item.get("checksum"))
        for item in (run.inputs if run is not None else [])
        if item.get("artifact_id") is not None
    }
    expected: dict[str, str] = {}
    for value in define.output_artifact_ids:
        artifact = session.get(Artifact, UUID(value))
        if artifact is not None:
            expected[str(artifact.id)] = artifact.sha256
    if (
        run is None
        or run.study_id != workbench.study_id
        or run.reconciliation_type != "adam_define_outputs"
        or run.status != "succeeded"
        or run.error_count != 0
        or not define_input
        or checksums != expected
    ):
        raise _problem(
            409,
            "successful_adrg_reconciliation_required",
            "Use zero-error reconciliation for this exact Define and output set.",
        )
    return run


def _facts(
    session: Session, define: AdamDefineRevision
) -> tuple[tuple[AdrgDatasetFact, ...], tuple[AdrgExecutionFact, ...]]:
    model = AdamDefineModel.model_validate(define.payload)
    datasets = {item.code: item for item in model.datasets}
    dataset_facts: list[AdrgDatasetFact] = []
    runs: dict[UUID, ExecutionRun] = {}
    for value in define.output_artifact_ids:
        artifact = session.get(Artifact, UUID(value))
        manifest = artifact.manifest if artifact is not None else {}
        code = manifest.get("dataset")
        dataset = datasets.get(str(code))
        variables = manifest.get("variables")
        if (
            artifact is None
            or dataset is None
            or artifact.status != "available"
            or artifact.artifact_type != "adam_dataset_xpt"
            or artifact.execution_run_id is None
            or not isinstance(manifest.get("row_count"), int)
            or not isinstance(variables, list)
            or not variables
        ):
            raise _problem(
                422, "adrg_output_evidence_invalid", "ADRG requires exact ADaM XPT evidence."
            )
        run = session.get(ExecutionRun, artifact.execution_run_id)
        if run is None or run.status != "succeeded" or run.module_key != "adam":
            raise _problem(
                422,
                "adrg_execution_evidence_invalid",
                "ADRG outputs require successful ADaM execution.",
            )
        runs[run.id] = run
        dataset_facts.append(
            AdrgDatasetFact(
                dataset=dataset.code,
                label=dataset.label,
                structure=dataset.structure,
                xpt_artifact_id=artifact.id,
                checksum=artifact.sha256,
                row_count=int(str(manifest["row_count"])),
                variable_count=len(variables),
            )
        )
    execution_facts: list[AdrgExecutionFact] = []
    for run in sorted(runs.values(), key=lambda item: str(item.id)):
        program = session.get(Artifact, run.program_artifact_id)
        if program is None or program.status != "available":
            raise _problem(
                422, "adrg_program_evidence_invalid", "ADRG execution program is unavailable."
            )
        execution_facts.append(
            AdrgExecutionFact(
                execution_run_id=run.id,
                language=run.language,
                program_artifact_id=program.id,
                program_checksum=program.sha256,
                output_artifact_ids=tuple(UUID(value) for value in run.output_artifact_ids),
            )
        )
    return tuple(sorted(dataset_facts, key=lambda item: item.dataset)), tuple(execution_facts)


def _current_inputs(session: Session, workbench: AdamWorkbench, model: AdamAdrgModel) -> None:
    define = _define(session, workbench, model.define_revision)
    selection = session.scalar(
        select(AdamInputSelection).where(AdamInputSelection.aggregate_id == workbench.id)
    )
    specification = session.scalar(
        select(AdamSpecificationRevision)
        .where(AdamSpecificationRevision.aggregate_id == workbench.id)
        .order_by(AdamSpecificationRevision.revision.desc())
    )
    plan = session.scalar(
        select(AdamDerivationPlanRevision)
        .where(AdamDerivationPlanRevision.aggregate_id == workbench.id)
        .order_by(AdamDerivationPlanRevision.revision.desc())
    )
    if (
        selection is None
        or specification is None
        or plan is None
        or model.input_selection_revision != selection.revision
        or model.specification_revision != specification.revision
        or model.plan_revision != plan.revision
        or define.input_selection_revision != selection.revision
        or define.specification_revision != specification.revision
    ):
        raise _problem(409, "adrg_authoring_misaligned", "ADRG authoring revisions are stale.")
    _reconciliation(session, workbench, define, model.reconciliation_run_id)
    dataset_facts, execution_facts = _facts(session, define)
    if model.dataset_facts != dataset_facts or model.execution_facts != execution_facts:
        raise _problem(422, "adrg_factual_content_mismatch", "Refresh ADRG facts with initialize.")


def _save(
    session: Session, workbench: AdamWorkbench, model: AdamAdrgModel, principal: Principal
) -> AdamAdrgRevision:
    current = _latest(session, workbench.id)
    payload = model.model_dump(mode="json")
    record = AdamAdrgRevision(
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
        owner_type="adam_workbench",
        owner_id=workbench.id,
        artifact_types=ADRG_ARTIFACT_TYPES,
    )
    return record


@router.get("/adams/{adam_id}/adrg", response_model=AdrgResponse)
def get_adrg(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AdrgResponse:
    workbench = _workbench(session, adam_id, principal)
    record = _latest(session, workbench.id)
    if record is None:
        raise _problem(404, "adam_adrg_not_found", "ADRG content is not saved.")
    return AdrgResponse.model_validate(record)


@router.put("/adams/{adam_id}/adrg", response_model=AdrgResponse)
def put_adrg(
    adam_id: UUID,
    command: AdamAdrgModel,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AdrgResponse:
    workbench = _workbench(session, adam_id, principal)
    require_matching_etag(if_match, workbench.revision)
    _current_inputs(session, workbench, command)
    record = _save(session, workbench, command, principal)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return AdrgResponse.model_validate(record)


@router.post("/adams/{adam_id}/adrg/initialize", response_model=AdrgResponse)
def initialize_adrg(
    adam_id: UUID,
    command: AdamAdrgInitialize,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AdrgResponse:
    workbench = _workbench(session, adam_id, principal)
    require_matching_etag(if_match, workbench.revision)
    current_record = _latest(session, workbench.id)
    if command.expected_adrg_revision != (current_record.revision if current_record else None):
        raise _problem(409, "adrg_revision_mismatch", "Expected ADRG revision is stale.")
    define = _define(session, workbench, command.define_revision)
    _reconciliation(session, workbench, define, command.reconciliation_run_id)
    current = AdamAdrgModel.model_validate(current_record.payload) if current_record else None
    sections = {item.section_id: item for item in (current.narrative_sections if current else ())}
    for section_id, heading in REQUIRED_NARRATIVE_SECTIONS:
        sections.setdefault(
            section_id, AdrgNarrativeSection(section_id=section_id, heading=heading)
        )
    datasets, executions = _facts(session, define)
    plan = session.scalar(
        select(AdamDerivationPlanRevision)
        .where(AdamDerivationPlanRevision.aggregate_id == workbench.id)
        .order_by(AdamDerivationPlanRevision.revision.desc())
    )
    if plan is None:
        raise _problem(409, "adrg_plan_required", "Current ADaM Derivation Plan is required.")
    model = AdamAdrgModel(
        title=current.title if current else command.title,
        version=current.version if current else command.version,
        specification_revision=define.specification_revision,
        input_selection_revision=define.input_selection_revision,
        plan_revision=plan.revision,
        define_revision=define.revision,
        reconciliation_run_id=command.reconciliation_run_id,
        output_artifact_ids=tuple(UUID(value) for value in define.output_artifact_ids),
        dataset_facts=datasets,
        execution_facts=executions,
        narrative_sections=tuple(sections.values()),
    )
    _current_inputs(session, workbench, model)
    record = _save(session, workbench, model, principal)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return AdrgResponse.model_validate(record)


@router.post("/adams/{adam_id}/adrg/validate", response_model=ValidationRunResponse)
def validate_adrg(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    workbench = _workbench(session, adam_id, principal)
    record = _latest(session, workbench.id)
    if record is None:
        raise _problem(404, "adam_adrg_not_found", "ADRG content is not saved.")
    model = AdamAdrgModel.model_validate(record.payload)
    _current_inputs(session, workbench, model)
    authored = {item.section_id for item in model.narrative_sections if item.paragraphs}
    required = {item[0] for item in REQUIRED_NARRATIVE_SECTIONS}
    issues = [_issue(item) for item in sorted(required - authored)]
    manifest = {
        "adrg_revision": record.revision,
        "adrg_fingerprint": record.fingerprint,
        "specification_revision": model.specification_revision,
        "input_selection_revision": model.input_selection_revision,
        "plan_revision": model.plan_revision,
        "define_revision": model.define_revision,
        "reconciliation_run_id": str(model.reconciliation_run_id),
        "output_artifact_ids": [str(item) for item in model.output_artifact_ids],
    }
    now = utc_now()
    run = ValidationRun(
        study_id=workbench.study_id,
        module_key="adam",
        owner_type="adam_adrg",
        owner_id=record.id,
        status="succeeded",
        validator_name="adam-adrg-validator",
        validator_version="1.0.0",
        input_fingerprint=fingerprint(manifest),
        input_manifest=manifest,
        started_at=now,
        completed_at=now,
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
    "/adams/{adam_id}/adrg/artifacts",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_adrg_artifacts(
    adam_id: UUID,
    command: AdrgArtifactRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    workbench = _workbench(session, adam_id, principal)
    return create_artifact_build(
        ArtifactBuildCreate(
            study_id=workbench.study_id,
            owner_type="adam_workbench",
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


def _issue(section_id: str) -> dict[str, object]:
    return {
        "id": f"ADAM_ADRG_REQUIRED_SECTION_MISSING:{section_id}",
        "code": "ADAM_ADRG_REQUIRED_SECTION_MISSING",
        "severity": "error",
        "message": "A required manually authored ADRG section is missing.",
        "suggestion": "Author the required narrative and validate a new revision.",
        "module": "adam",
        "entity_type": "adam_adrg",
        "entity_id": None,
        "field_path": f"narrative_sections[{section_id}]",
        "dataset": None,
        "variable": None,
        "artifact_id": None,
    }
