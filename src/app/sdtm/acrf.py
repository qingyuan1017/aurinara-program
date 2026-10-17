"""Persisted aCRF annotations, exact typed links, and current coverage."""

from datetime import datetime
from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_object_storage, get_session
from app.artifacts.builds import ArtifactBuildCreate, ArtifactBuildResponse, create_artifact_build
from app.artifacts.models import Artifact, SourceFile
from app.artifacts.service import ArtifactService
from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.problems import ProblemException
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import DependencyCapability
from app.kernel.registry import ModuleRegistry
from app.sdtm.contracts import (
    AcrfAnnotationCreate,
    AcrfAnnotationPatch,
    AcrfLink,
    AcrfLinksWrite,
    AcrfRawVariableLink,
    AcrfRegion,
    AcrfSdtmVariableLink,
    SdtmSpecification,
)
from app.sdtm.models import (
    SdtmAcrfAnnotation,
    SdtmInputSelection,
    SdtmSpecificationRevision,
    SdtmWorkbench,
)
from app.studies.service import StudyService

router = APIRouter(tags=["sdtm-acrf"])
studies = StudyService()
artifacts = ArtifactService()
ACRF_DEPENDENT_ARTIFACT_TYPES = (
    "sdtm_acrf",
    "sdtm_define_xml_20",
    "sdtm_define_xml_21",
    "sdtm_csdrg_docx",
    "sdtm_csdrg_pdf",
)


class RawContextExporter(Protocol):
    def context_snapshot(
        self, session: Session, raw_id: UUID, study_id: UUID
    ) -> dict[str, object]: ...


class AcrfAnnotationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sdtm_id: UUID
    study_id: UUID
    source_pdf_artifact_id: UUID
    page_number: int
    region: AcrfRegion
    annotation_text: str | None
    links: tuple[AcrfLink, ...]
    question: str | None
    resolution: str | None
    status: str
    fingerprint: str
    revision: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class AcrfCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    specification_revision: int | None
    plan_revision: int | None
    annotation_count: int
    linked_annotation_count: int
    unlinked_annotation_ids: tuple[UUID, ...]
    uncovered_sdtm_variables: tuple[dict[str, str], ...]
    noncurrent_link_count: int


class AcrfArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


def _sdtm(session: Session, sdtm_id: UUID, principal: Principal) -> SdtmWorkbench:
    workbench = session.get(SdtmWorkbench, sdtm_id)
    if workbench is None:
        raise _not_found("sdtm_not_found", "The SDTM workbench does not exist.")
    studies.require_access(session, workbench.study_id, principal)
    return workbench


def _annotation(session: Session, annotation_id: UUID, principal: Principal) -> SdtmAcrfAnnotation:
    record = session.get(SdtmAcrfAnnotation, annotation_id)
    if record is None:
        raise _not_found("acrf_annotation_not_found", "The aCRF annotation does not exist.")
    studies.require_access(session, record.study_id, principal)
    return record


def _pdf_artifact(
    session: Session,
    storage: ObjectStorage,
    *,
    artifact_id: UUID,
    study_id: UUID,
    page_number: int,
) -> Artifact:
    artifact = session.get(Artifact, artifact_id)
    source = session.scalar(select(SourceFile).where(SourceFile.artifact_id == artifact_id))
    if (
        artifact is None
        or source is None
        or artifact.study_id != study_id
        or source.study_id != study_id
        or artifact.status != "available"
        or artifact.object_key is None
        or artifact.artifact_type != "source_file"
        or artifact.media_type != "application/pdf"
        or source.media_type != "application/pdf"
    ):
        raise _unprocessable(
            "acrf_source_pdf_invalid",
            "The aCRF source must be an available immutable PDF source artifact in this study.",
        )
    try:
        with storage.open(artifact.object_key) as stream:
            page_count = len(PdfReader(stream).pages)
    except (PdfReadError, OSError, ValueError) as error:
        raise _unprocessable(
            "acrf_source_pdf_invalid", "The aCRF source PDF cannot be read."
        ) from error
    if page_number > page_count:
        raise _unprocessable("acrf_page_invalid", "The annotation page is outside the source PDF.")
    return artifact


def _validate_links(
    session: Session,
    registry: ModuleRegistry,
    workbench: SdtmWorkbench,
    links: tuple[AcrfLink, ...],
) -> None:
    raw_ids = {item.raw_variable_id for item in links if isinstance(item, AcrfRawVariableLink)}
    selected_raw_ids: set[UUID] | None = None
    if raw_ids:
        resolver = cast(
            DependencyCapability,
            registry.require_handler("raw", ModuleCapability.ENTITY_RESOLUTION),
        )
        if any(
            resolver.resolve_entity(session, "raw_variable", item) != workbench.study_id
            for item in raw_ids
        ):
            raise _unprocessable(
                "acrf_raw_variable_unresolved",
                "Every Raw-variable link must resolve through Raw in this study.",
            )
        selection = session.scalar(
            select(SdtmInputSelection).where(SdtmInputSelection.aggregate_id == workbench.id)
        )
        if selection is None or selection.state != "current":
            raise _unprocessable(
                "acrf_input_selection_required",
                "Select a current exact Raw context before linking Raw variables.",
            )
        raw_id = UUID(str(selection.payload["raw_id"]))
        provider = cast(
            RawContextExporter,
            registry.require_handler("raw", ModuleCapability.CONTEXT_EXPORT),
        )
        context = provider.context_snapshot(session, raw_id, workbench.study_id)
        selected_raw_ids = {
            UUID(str(variable["id"]))
            for dataset in cast(list[dict[str, object]], context["datasets"])
            for variable in cast(list[dict[str, object]], dataset["variables"])
        }
        if not raw_ids <= selected_raw_ids:
            raise _unprocessable(
                "acrf_raw_variable_not_selected",
                (
                    "Raw-variable links must belong to the SDTM workbench's exact selected "
                    "Raw context."
                ),
            )

    for link in links:
        if isinstance(link, AcrfSdtmVariableLink):
            specification_record = session.scalar(
                select(SdtmSpecificationRevision).where(
                    SdtmSpecificationRevision.aggregate_id == workbench.id,
                    SdtmSpecificationRevision.revision == link.specification_revision,
                )
            )
            if specification_record is None:
                raise _unprocessable(
                    "acrf_sdtm_variable_unresolved",
                    "An SDTM-variable link references an unavailable Specification revision.",
                )
            specification = SdtmSpecification.model_validate(specification_record.payload)
            variables = {
                (domain.code, variable.name)
                for domain in specification.domains
                for variable in domain.variables
            }
            if (link.domain, link.variable) not in variables:
                raise _unprocessable(
                    "acrf_sdtm_variable_unresolved",
                    "Every SDTM-variable link must resolve in its exact Specification revision.",
                )


def _payload(record: SdtmAcrfAnnotation) -> dict[str, object]:
    return {
        "source_pdf_artifact_id": str(record.source_pdf_artifact_id),
        "page_number": record.page_number,
        "region": record.region,
        "annotation_text": record.annotation_text,
        "links": record.links,
        "question": record.question,
        "resolution": record.resolution,
        "status": record.status,
    }


def _touch(session: Session, workbench: SdtmWorkbench, annotation: SdtmAcrfAnnotation) -> None:
    annotation.fingerprint = fingerprint(_payload(annotation))
    annotation.revision += 1
    workbench.revision += 1
    artifacts.mark_owner_stale(
        session,
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        artifact_types=ACRF_DEPENDENT_ARTIFACT_TYPES,
    )


@router.get("/sdtms/{sdtm_id}/acrf/annotations", response_model=list[AcrfAnnotationResponse])
def list_annotations(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[AcrfAnnotationResponse]:
    workbench = _sdtm(session, sdtm_id, principal)
    records = session.scalars(
        select(SdtmAcrfAnnotation)
        .where(
            SdtmAcrfAnnotation.sdtm_id == workbench.id,
            SdtmAcrfAnnotation.status.notin_(("deleted", "retired")),
        )
        .order_by(SdtmAcrfAnnotation.page_number, SdtmAcrfAnnotation.id)
    )
    return [AcrfAnnotationResponse.model_validate(item) for item in records]


@router.post(
    "/sdtms/{sdtm_id}/acrf/annotations",
    response_model=AcrfAnnotationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_annotation(
    sdtm_id: UUID,
    command: AcrfAnnotationCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AcrfAnnotationResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    require_matching_etag(if_match, workbench.revision)
    _pdf_artifact(
        session,
        storage,
        artifact_id=command.source_pdf_artifact_id,
        study_id=workbench.study_id,
        page_number=command.page_number,
    )
    _validate_links(session, registry, workbench, command.links)
    values = command.model_dump(mode="json")
    record = SdtmAcrfAnnotation(
        sdtm_id=workbench.id,
        study_id=workbench.study_id,
        source_pdf_artifact_id=command.source_pdf_artifact_id,
        page_number=command.page_number,
        region=values["region"],
        annotation_text=command.annotation_text,
        links=cast(list[dict[str, object]], values["links"]),
        question=command.question,
        resolution=command.resolution,
        status=command.status,
        fingerprint=fingerprint(values),
        created_by=principal.subject,
    )
    session.add(record)
    workbench.revision += 1
    artifacts.mark_owner_stale(
        session,
        owner_type="sdtm_workbench",
        owner_id=workbench.id,
        artifact_types=ACRF_DEPENDENT_ARTIFACT_TYPES,
    )
    session.commit()
    response.headers["ETag"] = etag_for_revision(record.revision)
    response.headers["X-Aggregate-ETag"] = etag_for_revision(workbench.revision)
    return AcrfAnnotationResponse.model_validate(record)


@router.get("/acrf-annotations/{annotation_id}", response_model=AcrfAnnotationResponse)
def get_annotation(
    annotation_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AcrfAnnotationResponse:
    record = _annotation(session, annotation_id, principal)
    response.headers["ETag"] = etag_for_revision(record.revision)
    return AcrfAnnotationResponse.model_validate(record)


@router.patch("/acrf-annotations/{annotation_id}", response_model=AcrfAnnotationResponse)
def patch_annotation(
    annotation_id: UUID,
    command: AcrfAnnotationPatch,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AcrfAnnotationResponse:
    record = _annotation(session, annotation_id, principal)
    if record.status == "deleted":
        raise _conflict("acrf_annotation_deleted", "A deleted annotation cannot be edited.")
    require_matching_etag(if_match, record.revision)
    workbench = cast(SdtmWorkbench, session.get(SdtmWorkbench, record.sdtm_id))
    values = command.model_dump(exclude_unset=True, mode="json")
    page_number = cast(int, values.get("page_number", record.page_number))
    _pdf_artifact(
        session,
        storage,
        artifact_id=record.source_pdf_artifact_id,
        study_id=record.study_id,
        page_number=page_number,
    )
    for field_name, value in values.items():
        setattr(record, field_name, value)
    _touch(session, workbench, record)
    session.commit()
    response.headers["ETag"] = etag_for_revision(record.revision)
    response.headers["X-Aggregate-ETag"] = etag_for_revision(workbench.revision)
    return AcrfAnnotationResponse.model_validate(record)


@router.delete("/acrf-annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_annotation(
    annotation_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    record = _annotation(session, annotation_id, principal)
    if record.status == "deleted":
        return
    require_matching_etag(if_match, record.revision)
    workbench = cast(SdtmWorkbench, session.get(SdtmWorkbench, record.sdtm_id))
    record.status = "deleted"
    _touch(session, workbench, record)
    session.commit()
    response.headers["ETag"] = etag_for_revision(record.revision)
    response.headers["X-Aggregate-ETag"] = etag_for_revision(workbench.revision)


@router.post("/acrf-annotations/{annotation_id}/links", response_model=AcrfAnnotationResponse)
def write_links(
    annotation_id: UUID,
    command: AcrfLinksWrite,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AcrfAnnotationResponse:
    record = _annotation(session, annotation_id, principal)
    if record.status == "deleted":
        raise _conflict("acrf_annotation_deleted", "A deleted annotation cannot be edited.")
    require_matching_etag(if_match, record.revision)
    workbench = cast(SdtmWorkbench, session.get(SdtmWorkbench, record.sdtm_id))
    existing = tuple(_parse_link(item) for item in record.links)
    if command.operation == "replace":
        combined = command.links
    else:
        by_value = {item.model_dump_json(): item for item in (*existing, *command.links)}
        combined = tuple(by_value[key] for key in sorted(by_value))
    _validate_links(session, registry, workbench, combined)
    record.links = [item.model_dump(mode="json") for item in combined]
    _touch(session, workbench, record)
    session.commit()
    response.headers["ETag"] = etag_for_revision(record.revision)
    response.headers["X-Aggregate-ETag"] = etag_for_revision(workbench.revision)
    return AcrfAnnotationResponse.model_validate(record)


@router.get("/sdtms/{sdtm_id}/acrf/coverage", response_model=AcrfCoverageResponse)
def get_coverage(
    sdtm_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AcrfCoverageResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    specification_record = session.scalar(
        select(SdtmSpecificationRevision)
        .where(SdtmSpecificationRevision.aggregate_id == workbench.id)
        .order_by(SdtmSpecificationRevision.revision.desc())
    )
    annotations = tuple(
        session.scalars(
            select(SdtmAcrfAnnotation).where(
                SdtmAcrfAnnotation.sdtm_id == workbench.id,
                SdtmAcrfAnnotation.status.notin_(("deleted", "retired")),
            )
        )
    )
    current_targets: set[tuple[str, str]] = set()
    all_targets: set[tuple[str, str]] = set()
    if specification_record is not None:
        specification = SdtmSpecification.model_validate(specification_record.payload)
        all_targets = {
            (domain.code, variable.name)
            for domain in specification.domains
            for variable in domain.variables
        }
    noncurrent = 0
    for annotation in annotations:
        for link in (_parse_link(item) for item in annotation.links):
            if isinstance(link, AcrfSdtmVariableLink):
                if (
                    specification_record is not None
                    and link.specification_revision == specification_record.revision
                ):
                    current_targets.add((link.domain, link.variable))
                else:
                    noncurrent += 1
    unlinked = tuple(item.id for item in annotations if not item.links)
    return AcrfCoverageResponse(
        specification_revision=(specification_record.revision if specification_record else None),
        plan_revision=None,
        annotation_count=len(annotations),
        linked_annotation_count=len(annotations) - len(unlinked),
        unlinked_annotation_ids=unlinked,
        uncovered_sdtm_variables=tuple(
            {"domain": domain, "variable": variable}
            for domain, variable in sorted(all_targets - current_targets)
        ),
        noncurrent_link_count=noncurrent,
    )


@router.post(
    "/sdtms/{sdtm_id}/acrf/artifacts",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_acrf_artifact(
    sdtm_id: UUID,
    command: AcrfArtifactRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    workbench = _sdtm(session, sdtm_id, principal)
    return create_artifact_build(
        ArtifactBuildCreate(
            study_id=workbench.study_id,
            owner_type="sdtm_workbench",
            owner_id=workbench.id,
            artifact_types=("sdtm_acrf",),
            expected_input_fingerprint=command.expected_input_fingerprint,
            options={},
        ),
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


def _parse_link(value: dict[str, object]) -> AcrfLink:
    target_type = value.get("target_type")
    if target_type == "sdtm_variable":
        return AcrfSdtmVariableLink.model_validate(value)
    if target_type == "raw_variable":
        return AcrfRawVariableLink.model_validate(value)
    raise _unprocessable(
        "acrf_link_type_invalid",
        "aCRF links may target only exact SDTM-variable rows or selected Raw variables.",
    )


def _not_found(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=404, code=code, title="aCRF resource not found", detail=detail
    )


def _unprocessable(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=422, code=code, title="aCRF content is invalid", detail=detail
    )


def _conflict(code: str, detail: str) -> ProblemException:
    return ProblemException(status_code=409, code=code, title="aCRF state conflict", detail=detail)
