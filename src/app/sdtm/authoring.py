"""SDTM mapping, code-workarea, run, output-selection, and readiness APIs."""

from datetime import datetime
from typing import Annotated, Any, Protocol, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import (
    get_application_settings,
    get_module_registry,
    get_object_storage,
    get_session,
)
from app.artifacts.models import Artifact
from app.artifacts.service import ArtifactService, store_bytes_object
from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.idempotency import IdempotencyRecord
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.config import Settings
from app.execution.jobs import Job
from app.execution.models import ExecutionRun
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry
from app.sdtm.contracts import (
    SdtmCodeWorkareaCreate,
    SdtmCodeWorkareaUpdate,
    SdtmDomain,
    SdtmDomainMappingWrite,
    SdtmOutputSelectionWrite,
    SdtmSpecification,
    SdtmVariableMappingWrite,
    SdtmWorkareaRunCreate,
)
from app.sdtm.models import (
    SdtmCodeRevision,
    SdtmCodeWorkarea,
    SdtmDependencySelection,
    SdtmDomainMappingRevision,
    SdtmDomainSourceSelection,
    SdtmImportedDomainRevision,
    SdtmInputSelection,
    SdtmOutputSelection,
    SdtmSpecificationRevision,
    SdtmVariableMappingRevision,
    SdtmWorkbench,
)
from app.studies.service import StudyService
from app.validation.models import ValidationRun

router = APIRouter(tags=["sdtm"])
studies = StudyService()
artifact_service = ArtifactService()


def _program_external_reference(
    *,
    workbench_id: UUID,
    workarea_id: UUID,
    code_revision: int,
    purpose: str,
    run_id: UUID,
) -> str:
    """Return the unique Platform reference owned by one immutable code run."""

    return (
        f"sdtm:{workbench_id}:workarea:{workarea_id}:revision:{code_revision}:"
        f"{purpose}-run:{run_id}:program"
    )


class _ContextExporter(Protocol):
    def context_snapshot(
        self, session: Session, aggregate_id: UUID, study_id: UUID
    ) -> dict[str, object]: ...


class MappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    domain: str
    revision: int
    specification_revision: int
    input_selection_revision: int | None = None
    domain_mapping_revision: int | None = None
    state: str
    alignment_reasons: tuple[str, ...]
    payload: dict[str, object]
    fingerprint: str
    created_by: str
    created_at: datetime


class MappingHeadPage(BaseModel):
    items: tuple[MappingResponse, ...]


class WorkareaResponse(BaseModel):
    id: UUID
    aggregate_id: UUID
    name: str
    domain: str
    language: str
    revision: int
    source: str
    specification_revision: int
    domain_mapping_revision: int
    variable_mapping_revision: int
    fingerprint: str
    archived_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class WorkareaPage(BaseModel):
    items: tuple[WorkareaResponse, ...]


class OutputSelectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    revision: int
    specification_revision: int
    state: str
    payload: dict[str, object]
    fingerprint: str
    updated_by: str
    updated_at: datetime


def _problem(code: str, title: str, detail: str, status_code: int = 422) -> ProblemException:
    return ProblemException(status_code=status_code, code=code, title=title, detail=detail)


def _workbench(session: Session, sdtm_id: UUID, principal: Principal) -> SdtmWorkbench:
    record = session.get(SdtmWorkbench, sdtm_id)
    if record is None:
        raise _problem(
            "sdtm_not_found", "SDTM workbench not found", "The workbench does not exist.", 404
        )
    studies.require_access(session, record.study_id, principal)
    return record


def _specification(
    session: Session, workbench: SdtmWorkbench
) -> tuple[SdtmSpecificationRevision, SdtmSpecification]:
    record = session.scalar(
        select(SdtmSpecificationRevision)
        .where(SdtmSpecificationRevision.aggregate_id == workbench.id)
        .order_by(SdtmSpecificationRevision.revision.desc())
        .limit(1)
    )
    if record is None:
        raise _problem(
            "sdtm_specification_required",
            "SDTM Specification required",
            "Save a Specification first.",
            409,
        )
    specification = SdtmSpecification.model_validate(record.payload)
    if specification.schema_version != "2.0.0":
        raise _problem(
            "sdtm_specification_upgrade_required",
            "Current Specification schema required",
            "Save an explicitly reviewed 2.0.0 Specification before authoring "
            "mappings or running code.",
            409,
        )
    return record, specification


def _input(session: Session, workbench: SdtmWorkbench) -> SdtmInputSelection:
    record = session.scalar(
        select(SdtmInputSelection).where(SdtmInputSelection.aggregate_id == workbench.id)
    )
    if record is None or record.state != "current":
        raise _problem(
            "sdtm_input_selection_required",
            "Input Selection required",
            "Select an exact Raw input first.",
            409,
        )
    return record


def _domain(specification: SdtmSpecification, code: str) -> SdtmDomain:
    value = next((item for item in specification.domains if item.code == code), None)
    if value is None:
        raise _problem(
            "sdtm_domain_unknown",
            "SDTM domain is unknown",
            f"Domain '{code}' is not declared.",
            404,
        )
    return value


def _mapping_response(
    record: SdtmDomainMappingRevision | SdtmVariableMappingRevision,
) -> MappingResponse:
    return MappingResponse(
        id=record.id,
        domain=record.domain_code,
        revision=record.revision,
        specification_revision=record.specification_revision,
        input_selection_revision=(
            record.input_selection_revision
            if isinstance(record, SdtmDomainMappingRevision)
            else None
        ),
        domain_mapping_revision=(
            record.domain_mapping_revision
            if isinstance(record, SdtmVariableMappingRevision)
            else None
        ),
        state=record.state,
        alignment_reasons=tuple(record.alignment_reasons or ()),
        payload=record.payload,
        fingerprint=record.fingerprint,
        created_by=record.created_by,
        created_at=record.created_at,
    )


def _head(session: Session, model: Any, aggregate_id: UUID, domain: str) -> Any:
    return session.scalar(
        select(model)
        .where(model.aggregate_id == aggregate_id, model.domain_code == domain)
        .order_by(model.revision.desc())
        .limit(1)
    )


def _all_heads(session: Session, model: Any, aggregate_id: UUID) -> dict[str, Any]:
    records: Any = session.scalars(
        select(model)
        .where(model.aggregate_id == aggregate_id)
        .order_by(model.domain_code, model.revision.desc())
    )
    heads: dict[str, Any] = {}
    for record in records:
        heads.setdefault(record.domain_code, record)
    return heads


def _validate_cycle(
    session: Session, aggregate_id: UUID, domain: str, upstream: tuple[str, ...]
) -> None:
    graph = {
        code: tuple(cast(list[str], head.payload.get("upstream_domains", [])))
        for code, head in _all_heads(session, SdtmDomainMappingRevision, aggregate_id).items()
    }
    graph[domain] = upstream
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise _problem(
                "sdtm_domain_dependency_cycle",
                "SDTM domain dependency cycle",
                "Upstream SDTM domains must form an acyclic graph.",
            )
        if node in visited:
            return
        visiting.add(node)
        for target in graph.get(node, ()):
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for code in graph:
        visit(code)


def _raw_context(
    session: Session,
    registry: ModuleRegistry,
    workbench: SdtmWorkbench,
    selection: SdtmInputSelection,
) -> dict[str, object]:
    raw_id = UUID(str(selection.payload["raw_id"]))
    provider = cast(
        _ContextExporter, registry.require_handler("raw", ModuleCapability.CONTEXT_EXPORT)
    )
    return provider.context_snapshot(session, raw_id, workbench.study_id)


def _mark_output_stale(session: Session, aggregate_id: UUID) -> None:
    selection = session.scalar(
        select(SdtmOutputSelection).where(SdtmOutputSelection.aggregate_id == aggregate_id)
    )
    if selection is not None:
        selection.state = "stale"
    artifact_service.mark_owner_stale(session, owner_type="sdtm_workbench", owner_id=aggregate_id)


@router.get("/sdtms/{sdtm_id}/domain-mappings", response_model=MappingHeadPage)
def list_domain_mappings(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> MappingHeadPage:
    workbench = _workbench(session, sdtm_id, principal)
    return MappingHeadPage(
        items=tuple(
            _mapping_response(item)
            for item in _all_heads(session, SdtmDomainMappingRevision, workbench.id).values()
        )
    )


@router.get("/sdtms/{sdtm_id}/domains/{domain}/domain-mapping", response_model=MappingResponse)
def get_domain_mapping(
    sdtm_id: UUID,
    domain: str,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> MappingResponse:
    workbench = _workbench(session, sdtm_id, principal)
    record = _head(session, SdtmDomainMappingRevision, workbench.id, domain)
    if record is None:
        raise _problem(
            "sdtm_domain_mapping_required",
            "Domain Mapping required",
            "No Domain Mapping has been saved.",
            404,
        )
    response.headers["ETag"] = etag_for_revision(record.revision)
    return _mapping_response(record)


@router.put("/sdtms/{sdtm_id}/domains/{domain}/domain-mapping", response_model=MappingResponse)
def put_domain_mapping(
    sdtm_id: UUID,
    domain: str,
    command: SdtmDomainMappingWrite,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> MappingResponse:
    workbench = _workbench(session, sdtm_id, principal)
    spec_record, specification = _specification(session, workbench)
    input_record = _input(session, workbench)
    _domain(specification, domain)
    if domain in command.upstream_domains:
        raise _problem(
            "sdtm_domain_mapping_self_reference",
            "Invalid upstream domain",
            "A domain cannot read itself.",
        )
    known_domains = {item.code for item in specification.domains}
    if not set(command.upstream_domains) <= known_domains:
        raise _problem(
            "sdtm_domain_mapping_upstream_unknown",
            "Unknown upstream domain",
            "Every upstream domain must be declared by the Specification.",
        )
    context = _raw_context(session, registry, workbench, input_record)
    raw_codes = {str(item["code"]) for item in cast(list[dict[str, object]], context["datasets"])}
    selected_codes = {
        str(item["dataset_code"])
        for item in cast(list[dict[str, object]], input_record.payload["source_artifacts"])
    }
    if not set(command.raw_datasets) <= raw_codes & selected_codes:
        raise _problem(
            "sdtm_domain_mapping_raw_unknown",
            "Raw dataset is not selected",
            "Every Raw dataset must belong to the exact current Raw selection.",
        )
    _validate_cycle(session, workbench.id, domain, command.upstream_domains)
    prior = _head(session, SdtmDomainMappingRevision, workbench.id, domain)
    require_matching_etag(if_match, workbench.revision)
    revision = (prior.revision + 1) if prior else 1
    payload = command.model_dump(mode="json")
    record = SdtmDomainMappingRevision(
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        domain_code=domain,
        revision=revision,
        specification_revision=spec_record.revision,
        input_selection_revision=input_record.revision,
        state="aligned",
        payload=payload,
        fingerprint=fingerprint(payload),
        created_by=principal.subject,
    )
    session.add(record)
    variable = _head(session, SdtmVariableMappingRevision, workbench.id, domain)
    if variable is not None and variable.state == "aligned":
        variable.state = "misaligned"
        variable.alignment_reasons = ["domain_mapping_changed"]
    source = session.scalar(
        select(SdtmDomainSourceSelection).where(
            SdtmDomainSourceSelection.aggregate_id == workbench.id,
            SdtmDomainSourceSelection.domain_code == domain,
        )
    )
    if source is None:
        source = SdtmDomainSourceSelection(
            aggregate_id=workbench.id,
            study_id=workbench.study_id,
            domain_code=domain,
            revision=1,
            source_type="generated",
            source_revision=revision,
            fingerprint=record.fingerprint,
            updated_by=principal.subject,
        )
        session.add(source)
    else:
        source.revision += 1
        source.source_type = "generated"
        source.source_revision = revision
        source.fingerprint = record.fingerprint
        source.updated_by = principal.subject
    _mark_output_stale(session, workbench.id)
    workbench.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return _mapping_response(record)


@router.get("/sdtms/{sdtm_id}/domains/{domain}/variable-mapping", response_model=MappingResponse)
def get_variable_mapping(
    sdtm_id: UUID,
    domain: str,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> MappingResponse:
    workbench = _workbench(session, sdtm_id, principal)
    record = _head(session, SdtmVariableMappingRevision, workbench.id, domain)
    if record is None:
        raise _problem(
            "sdtm_variable_mapping_required",
            "Variable Mapping required",
            "No Variable Mapping has been saved.",
            404,
        )
    response.headers["ETag"] = etag_for_revision(record.revision)
    return _mapping_response(record)


@router.put("/sdtms/{sdtm_id}/domains/{domain}/variable-mapping", response_model=MappingResponse)
def put_variable_mapping(
    sdtm_id: UUID,
    domain: str,
    command: SdtmVariableMappingWrite,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> MappingResponse:
    workbench = _workbench(session, sdtm_id, principal)
    spec_record, specification = _specification(session, workbench)
    target = _domain(specification, domain)
    mapping = _head(session, SdtmDomainMappingRevision, workbench.id, domain)
    if mapping is None or mapping.state != "aligned":
        raise _problem(
            "sdtm_domain_mapping_alignment_required",
            "Domain Mapping alignment required",
            "Save a current Domain Mapping first.",
            409,
        )
    target_variables = {item.name for item in target.variables}
    contexts = {item.id for item in target.value_contexts}
    raw_allowed = set(cast(list[str], mapping.payload.get("raw_datasets", [])))
    sdtm_allowed = set(cast(list[str], mapping.payload.get("upstream_domains", [])))
    raw_context = _raw_context(session, registry, workbench, _input(session, workbench))
    raw_variables = {
        (str(dataset["code"]), str(variable["name"]))
        for dataset in cast(list[dict[str, object]], raw_context["datasets"])
        for variable in cast(list[dict[str, object]], dataset["variables"])
    }
    sdtm_variables = {
        (item.code, variable.name) for item in specification.domains for variable in item.variables
    }
    for cell in command.cells:
        if cell.target_variable not in target_variables or (
            cell.context_id is not None and cell.context_id not in contexts
        ):
            raise _problem(
                "sdtm_variable_mapping_target_invalid",
                "Variable Mapping target is invalid",
                "Every target row and context column must be declared by the current "
                "Specification.",
            )
        for source in cell.sources:
            allowed = raw_allowed if source.source_type == "raw" else sdtm_allowed
            known = raw_variables if source.source_type == "raw" else sdtm_variables
            if source.dataset not in allowed or (source.dataset, source.variable) not in known:
                raise _problem(
                    "sdtm_variable_mapping_source_invalid",
                    "Variable Mapping source is invalid",
                    "Every qualified source must be declared by the current Domain Mapping "
                    "and source metadata.",
                )
    prior = _head(session, SdtmVariableMappingRevision, workbench.id, domain)
    require_matching_etag(if_match, workbench.revision)
    revision = (prior.revision + 1) if prior else 1
    payload = command.model_dump(mode="json")
    record = SdtmVariableMappingRevision(
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        domain_code=domain,
        revision=revision,
        specification_revision=spec_record.revision,
        domain_mapping_revision=mapping.revision,
        state="aligned",
        payload=payload,
        fingerprint=fingerprint(payload),
        created_by=principal.subject,
    )
    session.add(record)
    _mark_output_stale(session, workbench.id)
    workbench.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return _mapping_response(record)


def _workarea_response(session: Session, record: SdtmCodeWorkarea) -> WorkareaResponse:
    revision = session.scalar(
        select(SdtmCodeRevision).where(
            SdtmCodeRevision.workarea_id == record.id, SdtmCodeRevision.revision == record.revision
        )
    )
    if revision is None:
        raise RuntimeError("workarea current revision is missing")
    return WorkareaResponse(
        id=record.id,
        aggregate_id=record.aggregate_id,
        name=record.name,
        domain=record.domain_code,
        language=record.language,
        revision=record.revision,
        source=revision.source,
        specification_revision=revision.specification_revision,
        domain_mapping_revision=revision.domain_mapping_revision,
        variable_mapping_revision=revision.variable_mapping_revision,
        fingerprint=revision.fingerprint,
        archived_at=record.archived_at,
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _mapping_pins(
    session: Session, workbench: SdtmWorkbench, domain: str
) -> tuple[SdtmSpecificationRevision, SdtmDomainMappingRevision, SdtmVariableMappingRevision]:
    spec, specification = _specification(session, workbench)
    _domain(specification, domain)
    dm = _head(session, SdtmDomainMappingRevision, workbench.id, domain)
    vm = _head(session, SdtmVariableMappingRevision, workbench.id, domain)
    if (
        dm is None
        or dm.state != "aligned"
        or vm is None
        or vm.state != "aligned"
        or vm.domain_mapping_revision != dm.revision
    ):
        raise _problem(
            "sdtm_mapping_alignment_required",
            "Current mappings required",
            "Save aligned Domain and Variable Mappings before saving code.",
            409,
        )
    return spec, dm, vm


@router.get("/sdtms/{sdtm_id}/code-workareas", response_model=WorkareaPage)
def list_workareas(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> WorkareaPage:
    workbench = _workbench(session, sdtm_id, principal)
    rows = session.scalars(
        select(SdtmCodeWorkarea)
        .where(SdtmCodeWorkarea.aggregate_id == workbench.id)
        .order_by(SdtmCodeWorkarea.domain_code, SdtmCodeWorkarea.name)
    )
    return WorkareaPage(items=tuple(_workarea_response(session, item) for item in rows))


@router.post(
    "/sdtms/{sdtm_id}/code-workareas",
    response_model=WorkareaResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workarea(
    sdtm_id: UUID,
    command: SdtmCodeWorkareaCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> WorkareaResponse:
    workbench = _workbench(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    spec, dm, vm = _mapping_pins(session, workbench, command.domain)
    record = SdtmCodeWorkarea(
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        name=command.name,
        domain_code=command.domain,
        language=command.language,
        revision=1,
        created_by=principal.subject,
    )
    session.add(record)
    session.flush()
    revision = SdtmCodeRevision(
        workarea_id=record.id,
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        revision=1,
        specification_revision=spec.revision,
        domain_mapping_revision=dm.revision,
        variable_mapping_revision=vm.revision,
        source=command.source,
        fingerprint=fingerprint(
            {"source": command.source, "pins": [spec.revision, dm.revision, vm.revision]}
        ),
        created_by=principal.subject,
    )
    session.add(revision)
    workbench.revision += 1
    try:
        session.commit()
    except IntegrityError as error:
        raise _problem(
            "sdtm_workarea_name_duplicate",
            "Code Workarea name already exists",
            "Choose a unique workarea name.",
            409,
        ) from error
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return _workarea_response(session, record)


@router.get("/sdtms/{sdtm_id}/code-workareas/{workarea_id}", response_model=WorkareaResponse)
def get_workarea(
    sdtm_id: UUID,
    workarea_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> WorkareaResponse:
    workbench = _workbench(session, sdtm_id, principal)
    record = session.get(SdtmCodeWorkarea, workarea_id)
    if record is None or record.aggregate_id != workbench.id:
        raise _problem(
            "sdtm_workarea_not_found",
            "Code Workarea not found",
            "The workarea does not exist.",
            404,
        )
    response.headers["ETag"] = etag_for_revision(record.revision)
    return _workarea_response(session, record)


@router.put("/sdtms/{sdtm_id}/code-workareas/{workarea_id}", response_model=WorkareaResponse)
def update_workarea(
    sdtm_id: UUID,
    workarea_id: UUID,
    command: SdtmCodeWorkareaUpdate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> WorkareaResponse:
    workbench = _workbench(session, sdtm_id, principal)
    record = session.get(SdtmCodeWorkarea, workarea_id)
    if record is None or record.aggregate_id != workbench.id or record.archived_at is not None:
        raise _problem(
            "sdtm_workarea_not_found",
            "Code Workarea not found",
            "The active workarea does not exist.",
            404,
        )
    require_matching_etag(if_match, workbench.revision)
    spec, dm, vm = _mapping_pins(session, workbench, record.domain_code)
    record.revision += 1
    record.name = command.name
    revision = SdtmCodeRevision(
        workarea_id=record.id,
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        revision=record.revision,
        specification_revision=spec.revision,
        domain_mapping_revision=dm.revision,
        variable_mapping_revision=vm.revision,
        source=command.source,
        fingerprint=fingerprint(
            {"source": command.source, "pins": [spec.revision, dm.revision, vm.revision]}
        ),
        created_by=principal.subject,
    )
    session.add(revision)
    workbench.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return _workarea_response(session, record)


@router.post(
    "/sdtms/{sdtm_id}/code-workareas/{workarea_id}/archive", response_model=WorkareaResponse
)
def archive_workarea(
    sdtm_id: UUID,
    workarea_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> WorkareaResponse:
    workbench = _workbench(session, sdtm_id, principal)
    record = session.get(SdtmCodeWorkarea, workarea_id)
    if record is None or record.aggregate_id != workbench.id:
        raise _problem(
            "sdtm_workarea_not_found",
            "Code Workarea not found",
            "The workarea does not exist.",
            404,
        )
    require_matching_etag(if_match, workbench.revision)
    record.archived_at = utc_now()
    workbench.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return _workarea_response(session, record)


def _create_run(
    *,
    purpose: str,
    workbench: SdtmWorkbench,
    workarea: SdtmCodeWorkarea,
    code: SdtmCodeRevision,
    command: SdtmWorkareaRunCreate,
    idempotency_key: str | None,
    response: Response,
    session: Session,
    storage: ObjectStorage,
    settings: Settings,
    principal: Principal,
) -> ExecutionRun:
    if not idempotency_key:
        raise _problem(
            "idempotency_key_required",
            "Idempotency-Key is required",
            "Supply an Idempotency-Key header.",
            400,
        )
    spec_record, specification = _specification(session, workbench)
    dm = _head(session, SdtmDomainMappingRevision, workbench.id, workarea.domain_code)
    vm = _head(session, SdtmVariableMappingRevision, workbench.id, workarea.domain_code)
    input_record = _input(session, workbench)
    if (
        dm is None
        or vm is None
        or dm.state != "aligned"
        or vm.state != "aligned"
        or (
            code.specification_revision,
            code.domain_mapping_revision,
            code.variable_mapping_revision,
        )
        != (spec_record.revision, dm.revision, vm.revision)
    ):
        raise _problem(
            "sdtm_workarea_alignment_required",
            "Code Workarea alignment required",
            "Save a new code revision against the current Specification and mappings.",
            409,
        )
    raw_by_code = {
        str(item["dataset_code"]): item
        for item in cast(list[dict[str, object]], input_record.payload["source_artifacts"])
    }
    inputs: list[dict[str, object]] = []
    for dataset in cast(list[str], dm.payload.get("raw_datasets", [])):
        selected = raw_by_code[dataset]
        inputs.append(
            {
                "artifact_id": str(selected["artifact_id"]),
                "dataset": dataset,
                "kind": "raw",
                "staged_path": f"inputs/raw/{dataset}.csv",
            }
        )
    requested_upstream = {item.domain: item.artifact_id for item in command.upstream_artifacts}
    required_upstream = set(cast(list[str], dm.payload.get("upstream_domains", [])))
    if set(requested_upstream) != required_upstream:
        raise _problem(
            "sdtm_upstream_selection_incomplete",
            "Exact upstream selection required",
            "Select one exact XPT artifact for every declared upstream domain.",
            409,
        )
    for domain, artifact_id in requested_upstream.items():
        artifact = session.get(Artifact, artifact_id)
        if (
            artifact is None
            or artifact.study_id != workbench.study_id
            or artifact.artifact_type != "sdtm_dataset_xpt"
            or artifact.status != "available"
            or artifact.manifest.get("dataset") != domain
        ):
            raise _problem(
                "sdtm_upstream_artifact_invalid",
                "Upstream XPT artifact is invalid",
                f"The selected artifact for {domain} is not an available exact SDTM XPT.",
            )
        inputs.append(
            {
                "artifact_id": str(artifact_id),
                "dataset": domain,
                "kind": "sdtm",
                "staged_path": f"inputs/sdtm/{domain}.csv",
            }
        )
    for item in inputs:
        artifact = session.get(Artifact, UUID(str(item["artifact_id"])))
        if (
            artifact is None
            or artifact.study_id != workbench.study_id
            or artifact.status != "available"
        ):
            raise _problem(
                "sdtm_run_input_invalid",
                "Run input is invalid",
                "Every input must be an available immutable artifact.",
            )
        item["sha256"] = artifact.sha256
        item["filename"] = artifact.filename
    request_fingerprint = fingerprint(
        {"purpose": purpose, "code_revision": str(code.id), "inputs": inputs}
    )
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.subject == principal.subject,
            IdempotencyRecord.route == f"sdtm-workarea-{purpose}",
            IdempotencyRecord.study_id == workbench.study_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise _problem(
                "idempotency_key_reused",
                "Idempotency key was reused",
                "The key is bound to different inputs.",
                409,
            )
        prior = session.get(ExecutionRun, existing.resource_id)
        if prior is None:
            raise RuntimeError("idempotency record references a missing run")
        response.headers["Location"] = f"/api/v1/sdtm-code-runs/{prior.id}"
        return prior
    run_id = uuid4()
    extension, media_type = {
        "python": ("py", "text/x-python"),
        "r": ("R", "text/x-r-source"),
        "sas": ("sas", "text/plain"),
    }[workarea.language]
    stored = store_bytes_object(
        storage,
        code.source.encode("utf-8"),
        media_type,
        study_id=workbench.study_id,
        external_reference=_program_external_reference(
            workbench_id=workbench.id,
            workarea_id=workarea.id,
            code_revision=code.revision,
            purpose=purpose,
            run_id=run_id,
        ),
    )
    validation = ValidationRun(
        study_id=workbench.study_id,
        module_key="sdtm",
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        status="succeeded",
        validator_name="sdtm-code-readiness",
        validator_version="1.0.0",
        input_fingerprint=request_fingerprint,
        input_manifest={"workarea_id": str(workarea.id), "code_revision_id": str(code.id)},
        started_at=utc_now(),
        completed_at=utc_now(),
        created_by=principal.subject,
    )
    session.add(validation)
    session.flush()
    program_manifest: dict[str, object] = {
        "schema_version": "1.0.0",
        "purpose": purpose,
        "workarea": {
            "id": str(workarea.id),
            "revision": code.revision,
            "code_revision_id": str(code.id),
            "domain": workarea.domain_code,
            "language": workarea.language,
        },
        "specification": {
            "revision": spec_record.revision,
            "fingerprint": spec_record.fingerprint,
            "payload": spec_record.payload,
        },
        "domain_mapping": {"revision": dm.revision, "payload": dm.payload},
        "variable_mapping": {"revision": vm.revision, "payload": vm.payload},
        "output_domain": workarea.domain_code,
        "upstream_artifacts": {key: str(value) for key, value in requested_upstream.items()},
        "input_selection": {
            "revision": input_record.revision,
            "payload": {
                "source_artifacts": [
                    {"artifact_id": item["artifact_id"], "dataset_code": item["dataset"]}
                    for item in inputs
                ]
            },
        },
    }
    dependency = session.scalar(
        select(SdtmDependencySelection).where(SdtmDependencySelection.aggregate_id == workbench.id)
    )
    program = artifact_service.record_artifact(
        session,
        stored=stored,
        study_id=workbench.study_id,
        module_key="sdtm",
        artifact_type=f"sdtm_program_{workarea.language}",
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        filename=f"{workarea.domain_code.lower()}-{workarea.name}.{extension}",
        media_type=media_type,
        manifest=program_manifest,
        input_fingerprint=request_fingerprint,
        dependency_selection_revision=dependency.revision if dependency else None,
        dependency_fingerprint=dependency.fingerprint if dependency else None,
        generator_name="sdtm-code-workarea",
        generator_version="1.0.0",
        created_by=principal.subject,
        validation_run_id=validation.id,
        input_selection_revision=input_record.revision,
        source_specification_revision=spec_record.revision,
        source_specification_fingerprint=spec_record.fingerprint,
        source_plan_type="sdtm_code_revision",
        source_plan_revision=code.revision,
        compiler_fingerprint=code.fingerprint,
    )
    if purpose == "test" or (purpose == "generation" and workarea.language != "sas"):
        program.status = "internal"
    terminal_sas = workarea.language == "sas" and settings.sas_runner_adapter is None
    manifest = {
        "schema_version": "1.0.0",
        "purpose": purpose,
        "program": {"artifact_id": str(program.id), "sha256": program.sha256},
        "inputs": inputs,
        "source_specification": program_manifest["specification"],
        "output_domain": workarea.domain_code,
        "upstream_artifacts": program_manifest["upstream_artifacts"],
    }
    run = ExecutionRun(
        id=run_id,
        study_id=workbench.study_id,
        module_key="sdtm",
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        language=workarea.language,
        program_artifact_id=program.id,
        input_artifact_ids=[str(item["artifact_id"]) for item in inputs],
        validation_run_id=validation.id,
        input_selection_revision=input_record.revision,
        source_specification_revision=spec_record.revision,
        source_plan_type="sdtm_code_revision",
        source_plan_revision=code.revision,
        compiler_fingerprint=code.fingerprint,
        input_fingerprint=request_fingerprint,
        limits={
            "cpu": settings.execution_cpu_limit,
            "memory_mb": settings.execution_memory_mb,
            "runtime_seconds": settings.execution_timeout_seconds,
            "output_bytes": settings.execution_output_limit_bytes,
        },
        manifest=manifest,
        status="failed" if terminal_sas else "queued",
        failure={"code": "runner_not_configured", "detail": "No external SAS runner is configured."}
        if terminal_sas
        else None,
        completed_at=utc_now() if terminal_sas else None,
        created_by=principal.subject,
    )
    session.add(run)
    session.flush()
    if not terminal_sas:
        session.add(
            Job(
                operation_id=run.id,
                job_type="execution",
                payload={"run_id": str(run.id)},
                max_attempts=settings.job_max_attempts,
            )
        )
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route=f"sdtm-workarea-{purpose}",
            study_id=workbench.study_id,
            key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_type="execution_run",
            resource_id=run.id,
        )
    )
    session.commit()
    response.headers["Location"] = f"/api/v1/sdtm-code-runs/{run.id}"
    return run


def _workarea_for_run(
    session: Session, workbench: SdtmWorkbench, workarea_id: UUID
) -> tuple[SdtmCodeWorkarea, SdtmCodeRevision]:
    workarea = session.get(SdtmCodeWorkarea, workarea_id)
    if (
        workarea is None
        or workarea.aggregate_id != workbench.id
        or workarea.archived_at is not None
    ):
        raise _problem(
            "sdtm_workarea_not_found",
            "Code Workarea not found",
            "The active workarea does not exist.",
            404,
        )
    code = session.scalar(
        select(SdtmCodeRevision).where(
            SdtmCodeRevision.workarea_id == workarea.id,
            SdtmCodeRevision.revision == workarea.revision,
        )
    )
    if code is None:
        raise RuntimeError("workarea current revision is missing")
    return workarea, code


@router.post(
    "/sdtms/{sdtm_id}/code-workareas/{workarea_id}/test", status_code=status.HTTP_202_ACCEPTED
)
def test_workarea(
    sdtm_id: UUID,
    workarea_id: UUID,
    command: SdtmWorkareaRunCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    workbench = _workbench(session, sdtm_id, principal)
    workarea, code = _workarea_for_run(session, workbench, workarea_id)
    run = _create_run(
        purpose="test",
        workbench=workbench,
        workarea=workarea,
        code=code,
        command=command,
        idempotency_key=idempotency_key,
        response=response,
        session=session,
        storage=storage,
        settings=settings,
        principal=principal,
    )
    return {"id": run.id, "status": run.status, "purpose": "test"}


@router.post(
    "/sdtms/{sdtm_id}/code-workareas/{workarea_id}/generate", status_code=status.HTTP_202_ACCEPTED
)
def generate_workarea(
    sdtm_id: UUID,
    workarea_id: UUID,
    command: SdtmWorkareaRunCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    workbench = _workbench(session, sdtm_id, principal)
    workarea, code = _workarea_for_run(session, workbench, workarea_id)
    run = _create_run(
        purpose="generation",
        workbench=workbench,
        workarea=workarea,
        code=code,
        command=command,
        idempotency_key=idempotency_key,
        response=response,
        session=session,
        storage=storage,
        settings=settings,
        principal=principal,
    )
    return {"id": run.id, "status": run.status, "purpose": "generation"}


@router.get("/sdtm-code-runs/{run_id}")
def get_code_run(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    run = session.get(ExecutionRun, run_id)
    if run is None or run.module_key != "sdtm" or run.source_plan_type != "sdtm_code_revision":
        raise _problem(
            "sdtm_code_run_not_found", "Code run not found", "The run does not exist.", 404
        )
    studies.require_access(session, run.study_id, principal)
    return {
        "id": run.id,
        "purpose": run.manifest.get("purpose"),
        "status": run.status,
        "output_artifact_ids": run.output_artifact_ids,
        "failure": run.failure,
        "exit_code": run.exit_code,
        "preview": run.metrics.get("preview", []),
        "stdout": run.stdout,
        "stderr": run.stderr,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


@router.get("/sdtms/{sdtm_id}/output-selection", response_model=OutputSelectionResponse)
def get_output_selection(
    sdtm_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> OutputSelectionResponse:
    workbench = _workbench(session, sdtm_id, principal)
    record = session.scalar(
        select(SdtmOutputSelection).where(SdtmOutputSelection.aggregate_id == workbench.id)
    )
    if record is None:
        raise _problem(
            "sdtm_output_selection_required",
            "Output Selection required",
            "No exact all-domain output set has been saved.",
            404,
        )
    response.headers["ETag"] = etag_for_revision(record.revision)
    return OutputSelectionResponse.model_validate(record)


@router.put("/sdtms/{sdtm_id}/output-selection", response_model=OutputSelectionResponse)
def put_output_selection(
    sdtm_id: UUID,
    command: SdtmOutputSelectionWrite,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> OutputSelectionResponse:
    workbench = _workbench(session, sdtm_id, principal)
    spec_record, specification = _specification(session, workbench)
    if {item.domain for item in command.items} != {item.code for item in specification.domains}:
        raise _problem(
            "sdtm_output_selection_incomplete",
            "Output Selection is incomplete",
            "Select exactly one output for every Specification domain.",
            409,
        )
    selected_artifacts = {item.domain: item.xpt_artifact_id for item in command.items}
    for item in command.items:
        artifact = session.get(Artifact, item.xpt_artifact_id)
        if (
            artifact is None
            or artifact.study_id != workbench.study_id
            or artifact.artifact_type != "sdtm_dataset_xpt"
            or artifact.status != "available"
            or artifact.manifest.get("dataset") != item.domain
        ):
            raise _problem(
                "sdtm_output_artifact_invalid",
                "Output artifact is invalid",
                f"{item.domain} must select an available exact XPT artifact.",
            )
        if item.provider_type == "generation":
            run = session.get(ExecutionRun, item.provider_revision_id)
            if (
                run is None
                or run.status != "succeeded"
                or str(item.xpt_artifact_id) not in run.output_artifact_ids
                or run.manifest.get("purpose") != "generation"
                or run.source_specification_revision != spec_record.revision
            ):
                raise _problem(
                    "sdtm_generation_selection_invalid",
                    "Generation selection is invalid",
                    f"{item.domain} must reference a successful generation run.",
                )
            for upstream, artifact_id in cast(
                dict[str, str], run.manifest.get("upstream_artifacts", {})
            ).items():
                if selected_artifacts.get(upstream) != UUID(artifact_id):
                    raise _problem(
                        "sdtm_output_selection_incoherent",
                        "Output Selection is not coherent",
                        f"{item.domain} was generated from a different {upstream} XPT artifact.",
                        409,
                    )
        else:
            imported = session.get(SdtmImportedDomainRevision, item.provider_revision_id)
            if (
                imported is None
                or imported.aggregate_id != workbench.id
                or imported.state != "aligned"
                or imported.artifact_id != item.xpt_artifact_id
            ):
                raise _problem(
                    "sdtm_import_selection_invalid",
                    "Imported selection is invalid",
                    f"{item.domain} must reference an aligned imported revision.",
                )
    prior = session.scalar(
        select(SdtmOutputSelection).where(SdtmOutputSelection.aggregate_id == workbench.id)
    )
    require_matching_etag(if_match, workbench.revision)
    payload = command.model_dump(mode="json")
    if prior is not None and prior.payload != payload:
        for validation_run in session.scalars(
            select(ValidationRun).where(
                ValidationRun.module_key == "sdtm",
                ValidationRun.owner_id == workbench.id,
                ValidationRun.status == "succeeded",
                ValidationRun.input_manifest["output_selection_revision"].astext.isnot(None),
            )
        ):
            validation_run.status = "stale"
        artifact_service.mark_owner_stale(
            session,
            owner_type="sdtm_workbench",
            owner_id=workbench.id,
            artifact_types=(
                "sdtm_validation_report",
                "sdtm_validation_report_json",
                "sdtm_acrf",
                "sdtm_define_xml_20",
                "sdtm_define_xml_21",
                "sdtm_csdrg_docx",
                "sdtm_csdrg_pdf",
                "sdtm_declared_lineage_report",
                "sdtm_lineage_report",
                "sdtm_lineage_report_json",
            ),
        )
    if prior is None:
        prior = SdtmOutputSelection(
            aggregate_id=workbench.id,
            study_id=workbench.study_id,
            revision=1,
            specification_revision=spec_record.revision,
            state="current",
            payload=payload,
            fingerprint=fingerprint(payload),
            updated_by=principal.subject,
        )
        session.add(prior)
    else:
        prior.revision += 1
        prior.specification_revision = spec_record.revision
        prior.state = "current"
        prior.payload = payload
        prior.fingerprint = fingerprint(payload)
        prior.updated_by = principal.subject
    workbench.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return OutputSelectionResponse.model_validate(prior)


@router.get("/sdtms/{sdtm_id}/program-artifact-readiness")
def get_program_artifact_readiness(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    workbench = _workbench(session, sdtm_id, principal)
    _, specification = _specification(session, workbench)
    selection = session.scalar(
        select(SdtmOutputSelection).where(SdtmOutputSelection.aggregate_id == workbench.id)
    )
    selected = (
        {
            str(item["domain"]): item
            for item in cast(list[dict[str, object]], selection.payload.get("items", []))
        }
        if selection and selection.state == "current"
        else {}
    )
    domains = [
        {
            "domain": domain.code,
            "ready": domain.code in selected,
            "provider": selected.get(domain.code, {}).get("provider_type"),
        }
        for domain in specification.domains
    ]
    return {
        "ready": all(item["ready"] for item in domains),
        "output_selection_revision": selection.revision if selection else None,
        "domains": domains,
    }
