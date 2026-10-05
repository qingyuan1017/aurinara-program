"""Documents REST API for authored content, Protocol evidence, validation, and builds."""

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_object_storage, get_session
from app.artifacts.builds import ArtifactBuildCreate, ArtifactBuildResponse, create_artifact_build
from app.artifacts.models import SourceFile
from app.artifacts.service import ArtifactService
from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.idempotency import IdempotencyRecord
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.documents.contracts import (
    WORKBOOK_DOCUMENT_TYPES,
    DocumentType,
    EvidenceRegion,
    UsdmDocument,
    WorkbookContentBase,
    validate_content,
)
from app.documents.models import (
    Document,
    DocumentContent,
    DocumentDependencySelection,
    ProtocolEvidence,
    ProtocolUsdmDocument,
)
from app.documents.rendering import render_xlsx, workbook_payload
from app.documents.service import (
    DocumentsCapability,
    document_input_snapshot,
    related_document_snapshot,
)
from app.documents.validation import validate_document
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import DependencySelectionInput, DependencySelectionResponse
from app.kernel.registry import ModuleRegistry
from app.studies.service import StudyService
from app.validation.models import ValidationRun
from app.validation.routes import ValidationRunResponse

router = APIRouter(tags=["documents"])
studies = StudyService()


class DocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    name: str = Field(min_length=1, max_length=255)
    document_type: DocumentType
    content_schema_version: Literal["1.0.0"] = "1.0.0"
    source_pdf_file_id: UUID | None = None
    related_document_ids: tuple[UUID, ...] = ()


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, pattern=r"^(draft|in_review|approved|retired)$")
    source_pdf_file_id: UUID | None = None
    related_document_ids: tuple[UUID, ...] | None = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    document_code: str
    name: str
    document_type: str
    status: str
    content_schema_version: str
    source_pdf_file_id: UUID | None
    related_document_ids: list[UUID]
    revision: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, value: Document) -> "DocumentResponse":
        return cls(
            id=value.id,
            study_id=value.study_id,
            document_code=value.code,
            name=value.name,
            document_type=value.document_type,
            status=value.status,
            content_schema_version=value.content_schema_version,
            source_pdf_file_id=value.source_pdf_file_id,
            related_document_ids=[UUID(item) for item in value.related_document_ids],
            revision=value.revision,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )


class ContentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    study_id: UUID
    revision: int
    schema_version: str
    payload: dict[str, object]
    fingerprint: str
    created_by: str
    created_at: datetime


class UsdmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    study_id: UUID
    revision: int
    schema_version: str
    usdm_version: str
    payload: dict[str, object]
    fingerprint: str
    created_by: str
    created_at: datetime


class EvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_pdf_file_id: UUID
    page_number: int = Field(ge=1)
    region: EvidenceRegion
    excerpt: str | None = Field(default=None, max_length=4000)
    linked_usdm_entity_ids: tuple[str, ...] = Field(min_length=1)
    question: str | None = Field(default=None, max_length=4000)
    resolution: str | None = Field(default=None, max_length=4000)
    status: str = Field(default="open", pattern=r"^(open|resolved)$")


class EvidencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_number: int | None = Field(default=None, ge=1)
    region: EvidenceRegion | None = None
    excerpt: str | None = Field(default=None, max_length=4000)
    linked_usdm_entity_ids: tuple[str, ...] | None = Field(default=None, min_length=1)
    question: str | None = Field(default=None, max_length=4000)
    resolution: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, pattern=r"^(open|resolved)$")


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    study_id: UUID
    source_pdf_file_id: UUID
    page_number: int
    region: dict[str, object]
    excerpt: str | None
    linked_usdm_entity_ids: list[str]
    question: str | None
    resolution: str | None
    status: str
    revision: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class ArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_types: tuple[str, ...] = Field(min_length=1)
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProtocolContextEntity(BaseModel):
    endpoint_id: UUID
    usdm_entity_id: str
    entity_type: str
    code: str | None
    name: str
    description: str | None


class ProtocolContextResponse(BaseModel):
    protocol_document_id: UUID
    protocol_document_revision: int
    usdm_revision: int
    usdm_fingerprint: str
    entities: tuple[ProtocolContextEntity, ...]


def _handler(registry: ModuleRegistry) -> DocumentsCapability:
    return cast(
        DocumentsCapability,
        registry.require_handler("documents", ModuleCapability.DEPENDENCIES),
    )


def _require(
    session: Session, registry: ModuleRegistry, document_id: UUID, principal: Principal
) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise _not_found("document_not_found", "Document not found")
    studies.require_access(session, document.study_id, principal)
    return document


def _require_protocol(document: Document) -> None:
    if document.document_type != DocumentType.PROTOCOL:
        raise ProblemException(
            status_code=409,
            code="invalid_document_type",
            title="Invalid document type",
            detail="This operation is available only for Protocol documents.",
        )


def _validate_related_documents(
    session: Session, study_id: UUID, document_ids: tuple[UUID, ...]
) -> None:
    if len(document_ids) != len(set(document_ids)):
        raise _unprocessable("duplicate_related_document", "Related document IDs must be unique.")
    for document_id in document_ids:
        record = session.get(Document, document_id)
        if record is None or record.study_id != study_id:
            raise _unprocessable(
                "related_document_invalid", "Every related document must exist in this study."
            )


def _validate_source_pdf(session: Session, study_id: UUID, source_file_id: UUID | None) -> None:
    if source_file_id is None:
        raise _unprocessable("protocol_source_pdf_required", "A Protocol requires a source PDF.")
    source = session.get(SourceFile, source_file_id)
    if source is None or source.study_id != study_id or source.media_type != "application/pdf":
        raise _unprocessable(
            "protocol_source_pdf_invalid",
            "The Protocol source must be an immutable PDF in the same study.",
        )


def _stale_document_evidence(session: Session, document: Document) -> None:
    ArtifactService().mark_owner_stale(session, owner_type="document", owner_id=document.id)
    for run in session.scalars(
        select(ValidationRun).where(
            ValidationRun.owner_type == "document",
            ValidationRun.owner_id == document.id,
            ValidationRun.status.in_(("succeeded", "failed")),
        )
    ):
        run.status = "stale"
    dependents = session.scalars(select(Document).where(Document.study_id == document.study_id))
    for dependent in dependents:
        if str(document.id) in dependent.related_document_ids:
            ArtifactService().mark_owner_stale(
                session, owner_type="document", owner_id=dependent.id
            )
            for run in session.scalars(
                select(ValidationRun).where(
                    ValidationRun.owner_type == "document",
                    ValidationRun.owner_id == dependent.id,
                    ValidationRun.status.in_(("succeeded", "failed")),
                )
            ):
                run.status = "stale"


@router.post(
    "/studies/{study_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    study_id: UUID,
    command: DocumentCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> DocumentResponse:
    studies.require_access(session, study_id, principal)
    _validate_related_documents(session, study_id, command.related_document_ids)
    if command.document_type == DocumentType.PROTOCOL:
        _validate_source_pdf(session, study_id, command.source_pdf_file_id)
    elif command.source_pdf_file_id is not None:
        raise _unprocessable(
            "source_pdf_not_applicable", "Only a Protocol may directly associate a source PDF."
        )
    document = Document(
        study_id=study_id,
        code=command.document_code,
        name=command.name,
        document_type=command.document_type.value,
        content_schema_version=command.content_schema_version,
        source_pdf_file_id=command.source_pdf_file_id,
        related_document_ids=[str(item) for item in command.related_document_ids],
    )
    session.add(document)
    session.flush()
    empty = DependencySelectionInput().model_dump(mode="json")
    session.add(
        DocumentDependencySelection(
            aggregate_id=document.id,
            study_id=study_id,
            revision=1,
            state="current",
            payload=empty,
            fingerprint=fingerprint(empty),
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="duplicate_natural_key",
            title="Document code already exists",
            detail="The document_code is already used in this study.",
        ) from error
    response.headers["ETag"] = etag_for_revision(document.revision)
    return DocumentResponse.from_record(document)


@router.get("/studies/{study_id}/documents", response_model=list[DocumentResponse])
def list_documents(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[DocumentResponse]:
    studies.require_access(session, study_id, principal)
    return [
        DocumentResponse.from_record(item)
        for item in session.scalars(
            select(Document)
            .where(Document.study_id == study_id)
            .order_by(Document.created_at.desc(), Document.id.desc())
        )
    ]


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> DocumentResponse:
    document = _require(session, registry, document_id, principal)
    response.headers["ETag"] = etag_for_revision(document.revision)
    return DocumentResponse.from_record(document)


@router.patch("/documents/{document_id}", response_model=DocumentResponse)
def patch_document(
    document_id: UUID,
    command: DocumentPatch,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DocumentResponse:
    document = _require(session, registry, document_id, principal)
    require_matching_etag(if_match, document.revision)
    values = command.model_dump(exclude_unset=True)
    if "related_document_ids" in values:
        related = cast(tuple[UUID, ...], command.related_document_ids)
        _validate_related_documents(session, document.study_id, related)
        values["related_document_ids"] = [str(item) for item in related]
    if "source_pdf_file_id" in values:
        _require_protocol(document)
        _validate_source_pdf(session, document.study_id, command.source_pdf_file_id)
    for field_name, value in values.items():
        setattr(document, field_name, value)
    document.revision += 1
    _stale_document_evidence(session, document)
    session.commit()
    response.headers["ETag"] = etag_for_revision(document.revision)
    return DocumentResponse.from_record(document)


@router.get("/documents/{document_id}/dependencies", response_model=DependencySelectionResponse)
def get_dependencies(
    document_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> DependencySelectionResponse:
    document = _require(session, registry, document_id, principal)
    return _handler(registry).get_selection(session, document.id, document.study_id)


@router.put("/documents/{document_id}/dependencies", response_model=DependencySelectionResponse)
def put_dependencies(
    document_id: UUID,
    command: DependencySelectionInput,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DependencySelectionResponse:
    document = _require(session, registry, document_id, principal)
    aggregate, selection = _handler(registry).replace_selection(
        session, document.id, document.study_id, command, if_match
    )
    _stale_document_evidence(session, document)
    session.commit()
    response.headers["ETag"] = etag_for_revision(aggregate.revision)
    return selection


@router.get("/documents/{document_id}/content", response_model=ContentResponse)
def get_content(
    document_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ContentResponse:
    document = _require(session, registry, document_id, principal)
    record = _handler(registry).latest_content(session, document.id)
    if record is None:
        raise _not_found("document_content_not_found", "Document content not found")
    return ContentResponse.model_validate(record)


@router.put("/documents/{document_id}/content", response_model=ContentResponse)
async def put_content(
    document_id: UUID,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ContentResponse:
    document = _require(session, registry, document_id, principal)
    require_matching_etag(if_match, document.revision)
    try:
        payload = await request.json()
        content = validate_content(document.document_type, payload)
    except (ValueError, ValidationError, json.JSONDecodeError) as error:
        raise _unprocessable("document_content_invalid", str(error)) from error
    return _save_content(session, document, content.model_dump(mode="json"), principal, response)


@router.post("/documents/{document_id}/content/import", response_model=ContentResponse)
async def import_content(
    document_id: UUID,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ContentResponse:
    document = _require(session, registry, document_id, principal)
    data = await request.body()
    route = f"documents:{document.id}:content-import"
    request_fingerprint = hashlib.sha256(data).hexdigest()
    existing = _idempotent_resource(
        session,
        document,
        principal,
        route,
        idempotency_key,
        request_fingerprint,
        DocumentContent,
    )
    if existing is not None:
        response.headers["ETag"] = etag_for_revision(document.revision)
        return ContentResponse.model_validate(existing)
    require_matching_etag(if_match, document.revision)
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            payload = json.loads(data)
        else:
            if DocumentType(document.document_type) not in WORKBOOK_DOCUMENT_TYPES:
                raise ValueError("XLSX import is available only for workbook document types")
            payload = workbook_payload(data)
        content = validate_content(document.document_type, payload)
    except (ValueError, ValidationError, json.JSONDecodeError) as error:
        raise _unprocessable("document_import_invalid", str(error)) from error
    return _save_content(
        session,
        document,
        content.model_dump(mode="json"),
        principal,
        response,
        idempotency=(route, cast(str, idempotency_key), request_fingerprint),
    )


@router.get("/documents/{document_id}/content/export")
def export_content(
    document_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    export_format: Annotated[str, Query(alias="format", pattern=r"^(json|xlsx)$")] = "json",
) -> Response:
    document = _require(session, registry, document_id, principal)
    record = _handler(registry).latest_content(session, document.id)
    if record is None:
        raise _not_found("document_content_not_found", "Document content not found")
    if export_format == "json":
        return JSONResponse(record.payload)
    content = validate_content(document.document_type, record.payload)
    if not hasattr(content, "rows"):
        raise _unprocessable("export_format_invalid", "This document type has no XLSX export.")
    return Response(
        render_xlsx(cast(WorkbookContentBase, content)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{document.code}.xlsx"'},
    )


def _save_content(
    session: Session,
    document: Document,
    payload: dict[str, object],
    principal: Principal,
    response: Response,
    idempotency: tuple[str, str, str] | None = None,
) -> ContentResponse:
    _validate_payload_document_references(session, document, payload)
    latest = session.scalar(
        select(DocumentContent.revision)
        .where(DocumentContent.document_id == document.id)
        .order_by(DocumentContent.revision.desc())
        .limit(1)
    )
    record = DocumentContent(
        document_id=document.id,
        study_id=document.study_id,
        revision=(latest or 0) + 1,
        schema_version=document.content_schema_version,
        payload=payload,
        fingerprint=fingerprint(payload),
        created_by=principal.subject,
    )
    session.add(record)
    session.flush()
    if idempotency is not None:
        route, key, request_fingerprint = idempotency
        session.add(
            IdempotencyRecord(
                subject=principal.subject,
                route=route,
                study_id=document.study_id,
                key=key,
                request_fingerprint=request_fingerprint,
                resource_type="document_content",
                resource_id=record.id,
            )
        )
    document.revision += 1
    _stale_document_evidence(session, document)
    session.commit()
    response.headers["ETag"] = etag_for_revision(document.revision)
    return ContentResponse.model_validate(record)


def _validate_payload_document_references(
    session: Session, document: Document, payload: dict[str, object]
) -> None:
    content = validate_content(document.document_type, payload)
    explicit = {UUID(item) for item in document.related_document_ids}
    references: set[UUID] = set()
    if hasattr(content, "related_records"):
        references.update(item.document_id for item in content.related_records)
    if hasattr(content, "rows"):
        references.update(
            item.related_document_id
            for item in content.rows
            if item.related_document_id is not None
        )
    if not references <= explicit:
        raise _unprocessable(
            "related_document_not_selected",
            "Content may reference only the aggregate's explicitly selected related documents.",
        )
    for document_id in references:
        related = session.get(Document, document_id)
        if related is None or related.study_id != document.study_id:
            raise _unprocessable(
                "related_document_invalid", "A content reference does not resolve in this study."
            )


@router.get("/documents/{document_id}/usdm", response_model=UsdmResponse)
def get_usdm(
    document_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> UsdmResponse:
    document = _require(session, registry, document_id, principal)
    _require_protocol(document)
    record = _handler(registry).latest_usdm(session, document.id)
    if record is None:
        raise _not_found("protocol_usdm_not_found", "Protocol USDM not found")
    return UsdmResponse.model_validate(record)


@router.put("/documents/{document_id}/usdm", response_model=UsdmResponse)
async def put_usdm(
    document_id: UUID,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> UsdmResponse:
    document = _require(session, registry, document_id, principal)
    _require_protocol(document)
    require_matching_etag(if_match, document.revision)
    try:
        usdm = UsdmDocument.model_validate(await request.json())
    except (ValueError, ValidationError, json.JSONDecodeError) as error:
        raise _unprocessable("protocol_usdm_invalid", str(error)) from error
    return _save_usdm(session, document, usdm, principal, response)


@router.post("/documents/{document_id}/usdm/import", response_model=UsdmResponse)
async def import_usdm(
    document_id: UUID,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> UsdmResponse:
    document = _require(session, registry, document_id, principal)
    _require_protocol(document)
    data = await request.body()
    route = f"documents:{document.id}:usdm-import"
    request_fingerprint = hashlib.sha256(data).hexdigest()
    existing = _idempotent_resource(
        session,
        document,
        principal,
        route,
        idempotency_key,
        request_fingerprint,
        ProtocolUsdmDocument,
    )
    if existing is not None:
        response.headers["ETag"] = etag_for_revision(document.revision)
        return UsdmResponse.model_validate(existing)
    require_matching_etag(if_match, document.revision)
    try:
        usdm = UsdmDocument.model_validate_json(data)
    except (ValueError, ValidationError) as error:
        raise _unprocessable("protocol_usdm_invalid", str(error)) from error
    return _save_usdm(
        session,
        document,
        usdm,
        principal,
        response,
        idempotency=(route, cast(str, idempotency_key), request_fingerprint),
    )


@router.get("/documents/{document_id}/usdm/export")
def export_usdm(
    document_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> JSONResponse:
    record = get_usdm(document_id, session, registry, principal)
    return JSONResponse(record.payload)


def _save_usdm(
    session: Session,
    document: Document,
    usdm: UsdmDocument,
    principal: Principal,
    response: Response,
    idempotency: tuple[str, str, str] | None = None,
) -> UsdmResponse:
    latest = session.scalar(
        select(ProtocolUsdmDocument.revision)
        .where(ProtocolUsdmDocument.document_id == document.id)
        .order_by(ProtocolUsdmDocument.revision.desc())
        .limit(1)
    )
    payload = usdm.model_dump(mode="json")
    record = ProtocolUsdmDocument(
        document_id=document.id,
        study_id=document.study_id,
        revision=(latest or 0) + 1,
        schema_version=usdm.schema_version,
        usdm_version=usdm.usdm_version,
        payload=payload,
        fingerprint=fingerprint(payload),
        created_by=principal.subject,
    )
    session.add(record)
    session.flush()
    if idempotency is not None:
        route, key, request_fingerprint = idempotency
        session.add(
            IdempotencyRecord(
                subject=principal.subject,
                route=route,
                study_id=document.study_id,
                key=key,
                request_fingerprint=request_fingerprint,
                resource_type="protocol_usdm_document",
                resource_id=record.id,
            )
        )
    document.revision += 1
    _stale_document_evidence(session, document)
    session.commit()
    response.headers["ETag"] = etag_for_revision(document.revision)
    return UsdmResponse.model_validate(record)


@router.get("/documents/{document_id}/evidence", response_model=list[EvidenceResponse])
def list_evidence(
    document_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[EvidenceResponse]:
    document = _require(session, registry, document_id, principal)
    _require_protocol(document)
    return [
        EvidenceResponse.model_validate(item)
        for item in session.scalars(
            select(ProtocolEvidence)
            .where(ProtocolEvidence.document_id == document.id)
            .order_by(ProtocolEvidence.page_number, ProtocolEvidence.id)
        )
    ]


@router.post(
    "/documents/{document_id}/evidence",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_evidence(
    document_id: UUID,
    command: EvidenceCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> EvidenceResponse:
    document = _require(session, registry, document_id, principal)
    _require_protocol(document)
    require_matching_etag(if_match, document.revision)
    _validate_evidence(session, storage, _handler(registry), document, command)
    item = ProtocolEvidence(
        document_id=document.id,
        study_id=document.study_id,
        source_pdf_file_id=command.source_pdf_file_id,
        page_number=command.page_number,
        region=command.region.model_dump(mode="json"),
        excerpt=command.excerpt,
        linked_usdm_entity_ids=list(command.linked_usdm_entity_ids),
        question=command.question,
        resolution=command.resolution,
        status=command.status,
        created_by=principal.subject,
    )
    session.add(item)
    document.revision += 1
    _stale_document_evidence(session, document)
    session.commit()
    response.headers["ETag"] = etag_for_revision(document.revision)
    return EvidenceResponse.model_validate(item)


def _require_evidence(
    session: Session, evidence_id: UUID, principal: Principal
) -> ProtocolEvidence:
    item = session.get(ProtocolEvidence, evidence_id)
    if item is None:
        raise _not_found("document_evidence_not_found", "Document evidence not found")
    studies.require_access(session, item.study_id, principal)
    return item


@router.get("/document-evidence/{evidence_id}", response_model=EvidenceResponse)
def get_evidence(
    evidence_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> EvidenceResponse:
    item = _require_evidence(session, evidence_id, principal)
    response.headers["ETag"] = etag_for_revision(item.revision)
    return EvidenceResponse.model_validate(item)


@router.patch("/document-evidence/{evidence_id}", response_model=EvidenceResponse)
def patch_evidence(
    evidence_id: UUID,
    command: EvidencePatch,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> EvidenceResponse:
    item = _require_evidence(session, evidence_id, principal)
    require_matching_etag(if_match, item.revision)
    document = cast(Document, session.get(Document, item.document_id))
    values = command.model_dump(exclude_unset=True, mode="json")
    merged = EvidenceCreate(
        source_pdf_file_id=item.source_pdf_file_id,
        page_number=cast(int, values.get("page_number", item.page_number)),
        region=values.get("region", item.region),
        excerpt=cast(str | None, values.get("excerpt", item.excerpt)),
        linked_usdm_entity_ids=values.get("linked_usdm_entity_ids", item.linked_usdm_entity_ids),
        question=cast(str | None, values.get("question", item.question)),
        resolution=cast(str | None, values.get("resolution", item.resolution)),
        status=cast(str, values.get("status", item.status)),
    )
    _validate_evidence(session, storage, _handler(registry), document, merged)
    for field_name, value in values.items():
        setattr(item, field_name, value)
    item.revision += 1
    document.revision += 1
    _stale_document_evidence(session, document)
    session.commit()
    response.headers["ETag"] = etag_for_revision(item.revision)
    return EvidenceResponse.model_validate(item)


@router.delete("/document-evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evidence(
    evidence_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    item = _require_evidence(session, evidence_id, principal)
    require_matching_etag(if_match, item.revision)
    document = cast(Document, session.get(Document, item.document_id))
    session.delete(item)
    document.revision += 1
    _stale_document_evidence(session, document)
    session.commit()


def _validate_evidence(
    session: Session,
    storage: ObjectStorage,
    handler: DocumentsCapability,
    document: Document,
    command: EvidenceCreate,
) -> None:
    if command.source_pdf_file_id != document.source_pdf_file_id:
        raise _unprocessable(
            "evidence_source_mismatch", "Evidence must use the Protocol's exact source PDF."
        )
    source = session.get(SourceFile, command.source_pdf_file_id)
    if source is None or source.study_id != document.study_id:
        raise _unprocessable("evidence_source_invalid", "Evidence source PDF is unavailable.")
    with storage.open(source.object_key) as stream:
        reader = PdfReader(stream)
        if command.page_number > len(reader.pages):
            raise _unprocessable(
                "evidence_page_invalid", "Evidence page is outside the source PDF."
            )
        page = reader.pages[command.page_number - 1]
        if (
            abs(float(page.mediabox.width) - command.region.page_width) > 0.5
            or abs(float(page.mediabox.height) - command.region.page_height) > 0.5
        ):
            raise _unprocessable(
                "evidence_page_dimensions_mismatch",
                "Evidence coordinates do not match the source PDF page dimensions.",
            )
    usdm_record = handler.latest_usdm(session, document.id)
    if usdm_record is None:
        raise _unprocessable("protocol_usdm_required", "Save USDM before linking evidence.")
    known = {item.id for item in UsdmDocument.model_validate(usdm_record.payload).entities}
    if not set(command.linked_usdm_entity_ids) <= known:
        raise _unprocessable(
            "evidence_entity_unresolved", "Every evidence link must resolve to saved USDM."
        )


@router.get("/documents/{document_id}/protocol-context", response_model=ProtocolContextResponse)
def get_protocol_context(
    document_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ProtocolContextResponse:
    sap = _require(session, registry, document_id, principal)
    if sap.document_type != DocumentType.SAP:
        raise ProblemException(
            status_code=409,
            code="invalid_document_type",
            title="Invalid document type",
            detail="Protocol context is available only for a Statistical Analysis Plan.",
        )
    protocols = [session.get(Document, UUID(item)) for item in sap.related_document_ids]
    protocol = next(
        (
            item
            for item in protocols
            if item is not None and item.document_type == DocumentType.PROTOCOL
        ),
        None,
    )
    if protocol is None:
        raise _unprocessable(
            "protocol_relationship_required", "Select an explicit related Protocol first."
        )
    record = _handler(registry).latest_usdm(session, protocol.id)
    if record is None:
        raise _unprocessable("protocol_usdm_required", "The selected Protocol has no saved USDM.")
    usdm = UsdmDocument.model_validate(record.payload)
    return ProtocolContextResponse(
        protocol_document_id=protocol.id,
        protocol_document_revision=protocol.revision,
        usdm_revision=record.revision,
        usdm_fingerprint=record.fingerprint,
        entities=tuple(
            ProtocolContextEntity(
                endpoint_id=_handler(registry).entity_endpoints(session, protocol)[index][1],
                usdm_entity_id=item.id,
                entity_type=item.entity_type,
                code=item.code,
                name=item.name,
                description=item.description,
            )
            for index, item in enumerate(
                entity
                for entity in usdm.entities
                if entity.entity_type in {"objective", "endpoint"}
            )
        ),
    )


@router.post(
    "/documents/{document_id}/validate",
    response_model=ValidationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def validate_document_endpoint(
    document_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    document = _require(session, registry, document_id, principal)
    handler = _handler(registry)
    selection = handler.get_selection(session, document.id, document.study_id)
    if selection.state != "current":
        raise ProblemException(
            status_code=409,
            code="dependency_refresh_required",
            title="Dependency refresh is required",
            detail="Refresh or reaffirm the exact dependency selection before validation.",
        )
    content_record = handler.latest_content(session, document.id)
    usdm_record = handler.latest_usdm(session, document.id)
    evidence = tuple(
        session.scalars(select(ProtocolEvidence).where(ProtocolEvidence.document_id == document.id))
    )
    content = (
        validate_content(document.document_type, content_record.payload) if content_record else None
    )
    usdm = UsdmDocument.model_validate(usdm_record.payload) if usdm_record else None
    protocol_ids: set[str] = set()
    if document.document_type == DocumentType.SAP:
        related_protocol = next(
            (
                related
                for related_id in document.related_document_ids
                if (related := session.get(Document, UUID(related_id))) is not None
                and related.document_type == DocumentType.PROTOCOL
            ),
            None,
        )
        if related_protocol is not None:
            related_usdm = handler.latest_usdm(session, related_protocol.id)
            if related_usdm is not None:
                protocol_ids = {
                    item.id for item in UsdmDocument.model_validate(related_usdm.payload).entities
                }
    issues = validate_document(
        document_id=document.id,
        content=content,
        usdm=usdm,
        evidence_entity_ids=(
            entity_id for item in evidence for entity_id in item.linked_usdm_entity_ids
        ),
        protocol_entity_ids=protocol_ids,
        related_document_ids=(UUID(item) for item in document.related_document_ids),
    )
    snapshot = document_input_snapshot(
        document,
        content_record,
        usdm_record,
        evidence,
        selection.fingerprint,
        related_document_snapshot(session, document, handler),
    )
    counts = {
        severity: sum(1 for item in issues if item.severity.value == severity)
        for severity in ("error", "warning", "info")
    }
    run = ValidationRun(
        study_id=document.study_id,
        module_key="documents",
        owner_type="document",
        owner_id=document.id,
        status="failed" if counts["error"] else "succeeded",
        validator_name="documents-contract-validator",
        validator_version="1.0.0",
        input_fingerprint=fingerprint(snapshot),
        input_manifest=snapshot,
        started_at=utc_now(),
        completed_at=utc_now(),
        error_count=counts["error"],
        warning_count=counts["warning"],
        info_count=counts["info"],
        issues=[item.model_dump(mode="json") for item in issues],
        report_artifact_ids=[],
        failure={"code": "document_validation_failed"} if counts["error"] else None,
        created_by=principal.subject,
    )
    session.add(run)
    session.commit()
    return ValidationRunResponse.model_validate(run)


@router.post(
    "/documents/{document_id}/artifacts",
    response_model=ArtifactBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_document_artifacts(
    document_id: UUID,
    command: ArtifactRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    document = _require(session, registry, document_id, principal)
    return create_artifact_build(
        ArtifactBuildCreate(
            study_id=document.study_id,
            owner_type="document",
            owner_id=document.id,
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


def _not_found(code: str, title: str) -> ProblemException:
    return ProblemException(status_code=404, code=code, title=title, detail=title)


def _unprocessable(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=422,
        code=code,
        title="Document content is invalid",
        detail=detail,
    )


def _idempotent_resource(
    session: Session,
    document: Document,
    principal: Principal,
    route: str,
    key: str | None,
    request_fingerprint: str,
    model: type[DocumentContent] | type[ProtocolUsdmDocument],
) -> DocumentContent | ProtocolUsdmDocument | None:
    if not key:
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
            IdempotencyRecord.study_id == document.study_id,
            IdempotencyRecord.key == key,
        )
    )
    if existing is None:
        return None
    if existing.request_fingerprint != request_fingerprint:
        raise ProblemException(
            status_code=409,
            code="idempotency_key_reused",
            title="Idempotency key was reused",
            detail="The key is already bound to different import bytes.",
        )
    resource = session.get(model, existing.resource_id)
    if resource is None:
        raise RuntimeError("idempotency record references a missing document revision")
    return cast(DocumentContent | ProtocolUsdmDocument, resource)
