"""Typed revisioned study Reference APIs."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_session
from app.artifacts.service import ArtifactService
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.idempotency import IdempotencyRecord
from app.common.outbox import OutboxEvent
from app.common.problems import ProblemException
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import DependencyCapability
from app.kernel.registry import ModuleRegistry
from app.reference.models import ReferenceImportBatch, ReferenceRecord, ReferenceRevision
from app.studies.service import StudyService

router = APIRouter(tags=["reference"])
studies = StudyService()
artifacts = ArtifactService()


class ReferenceType(StrEnum):
    ORGANIZATION = "organization"
    COUNTRY = "country"
    SITE = "site"
    VENDOR = "vendor"
    LANGUAGE = "language"
    UNIT = "unit"
    ROLE = "role"
    MILESTONE = "milestone"


class ReferenceField(BaseModel):
    """One explicitly named factual value."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    value: str | int | float | bool | date | None


class ReferenceValue(BaseModel):
    """Versioned manual Reference value without arbitrary nested JSON."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "1.0.0"
    fields: tuple[ReferenceField, ...]


class ReferenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_type: ReferenceType
    natural_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    value: ReferenceValue


class ReferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    value: ReferenceValue | None = None


class ReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    reference_type: str
    natural_key: str
    display_name: str
    status: str
    revision: int
    current_revision_id: UUID


class ReferenceRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    reference_id: UUID
    study_id: UUID
    revision: int
    schema_version: str
    value: dict[str, object]
    fingerprint: str
    created_by: str
    created_at: datetime


class ReferenceImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0.0"
    items: tuple[ReferenceCreate, ...]


class ReferenceCollection(BaseModel):
    schema_version: str = "1.0.0"
    items: tuple[ReferenceResponse, ...]


def _current_revision(session: Session, record: ReferenceRecord) -> ReferenceRevision:
    revision = session.scalar(
        select(ReferenceRevision).where(
            ReferenceRevision.reference_id == record.id,
            ReferenceRevision.revision == record.revision,
        )
    )
    if revision is None:
        raise RuntimeError("reference current revision is missing")
    return revision


def _response(session: Session, record: ReferenceRecord) -> ReferenceResponse:
    return ReferenceResponse(
        id=record.id,
        study_id=record.study_id,
        reference_type=record.reference_type,
        natural_key=record.natural_key,
        display_name=record.display_name,
        status=record.status,
        revision=record.revision,
        current_revision_id=_current_revision(session, record).id,
    )


def _require(session: Session, reference_id: UUID, principal: Principal) -> ReferenceRecord:
    record = session.get(ReferenceRecord, reference_id)
    if record is None:
        raise ProblemException(
            status_code=404,
            code="reference_not_found",
            title="Reference not found",
            detail="The Reference identity does not exist.",
        )
    studies.require_access(session, record.study_id, principal)
    return record


@router.post(
    "/studies/{study_id}/references",
    response_model=ReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_reference(
    study_id: UUID,
    command: ReferenceCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReferenceResponse:
    studies.require_access(session, study_id, principal)
    record = ReferenceRecord(
        study_id=study_id,
        reference_type=command.reference_type.value,
        natural_key=command.natural_key,
        display_name=command.display_name,
    )
    session.add(record)
    session.flush()
    payload = command.value.model_dump(mode="json")
    session.add(
        ReferenceRevision(
            reference_id=record.id,
            study_id=study_id,
            revision=1,
            schema_version=command.value.schema_version,
            value=payload,
            fingerprint=fingerprint(payload),
            created_by=principal.subject,
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="duplicate_reference_key",
            title="Reference key already exists",
            detail="The natural key is already used for this Reference type.",
        ) from error
    response.headers["ETag"] = etag_for_revision(record.revision)
    return _response(session, record)


@router.get("/studies/{study_id}/references", response_model=list[ReferenceResponse])
def list_references(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ReferenceResponse]:
    studies.require_access(session, study_id, principal)
    return [
        _response(session, item)
        for item in session.scalars(
            select(ReferenceRecord).where(ReferenceRecord.study_id == study_id)
        )
    ]


@router.get("/references/{reference_id}", response_model=ReferenceResponse)
def get_reference(
    reference_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReferenceResponse:
    record = _require(session, reference_id, principal)
    response.headers["ETag"] = etag_for_revision(record.revision)
    return _response(session, record)


@router.patch("/references/{reference_id}", response_model=ReferenceResponse)
def patch_reference(
    reference_id: UUID,
    command: ReferencePatch,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ReferenceResponse:
    record = _require(session, reference_id, principal)
    require_matching_etag(if_match, record.revision)
    old_revision = _current_revision(session, record)
    record.revision += 1
    if command.display_name is not None:
        record.display_name = command.display_name
    value = command.value.model_dump(mode="json") if command.value else old_revision.value
    session.add(
        ReferenceRevision(
            reference_id=record.id,
            study_id=record.study_id,
            revision=record.revision,
            schema_version=str(value["schema_version"]),
            value=value,
            fingerprint=fingerprint(value),
            created_by=principal.subject,
        )
    )
    for descriptor in registry.descriptors():
        if ModuleCapability.STALENESS in descriptor.capabilities:
            handler = cast(
                DependencyCapability,
                registry.require_handler(descriptor.module_key, ModuleCapability.STALENESS),
            )
            for aggregate_id in handler.mark_dependency_refresh(session, old_revision.id):
                artifacts.mark_owner_stale(
                    session, owner_type=next(iter(descriptor.entity_types)), owner_id=aggregate_id
                )
    session.add(
        OutboxEvent(
            id=uuid4(),
            study_id=record.study_id,
            event_type="references.revised",
            schema_version="1.0.0",
            module_key="reference",
            subject_type="reference",
            subject_id=record.id,
            subject_revision=record.revision,
            correlation_id=str(record.id),
            payload={"status": record.status, "revision": record.revision},
        )
    )
    session.commit()
    response.headers["ETag"] = etag_for_revision(record.revision)
    return _response(session, record)


@router.delete("/references/{reference_id}", status_code=status.HTTP_204_NO_CONTENT)
def retire_reference(
    reference_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    record = _require(session, reference_id, principal)
    require_matching_etag(if_match, record.revision)
    record.status = "retired"
    record.revision += 1
    session.commit()


@router.get("/references/{reference_id}/revisions", response_model=list[ReferenceRevisionResponse])
def list_reference_revisions(
    reference_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ReferenceRevisionResponse]:
    record = _require(session, reference_id, principal)
    return [
        ReferenceRevisionResponse.model_validate(item)
        for item in session.scalars(
            select(ReferenceRevision)
            .where(ReferenceRevision.reference_id == record.id)
            .order_by(ReferenceRevision.revision)
        )
    ]


@router.get("/reference-revisions/{revision_id}", response_model=ReferenceRevisionResponse)
def get_reference_revision(
    revision_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReferenceRevisionResponse:
    revision = session.get(ReferenceRevision, revision_id)
    if revision is None:
        raise ProblemException(
            status_code=404,
            code="reference_revision_not_found",
            title="Reference revision not found",
            detail="The exact revision does not exist.",
        )
    studies.require_access(session, revision.study_id, principal)
    return ReferenceRevisionResponse.model_validate(revision)


@router.post(
    "/studies/{study_id}/references/import",
    response_model=ReferenceCollection,
    status_code=status.HTTP_201_CREATED,
)
def import_references(
    study_id: UUID,
    command: ReferenceImport,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReferenceCollection:
    """Validate and commit a complete JSON Reference import atomically."""

    studies.require_access(session, study_id, principal)
    if not idempotency_key:
        raise ProblemException(
            status_code=400,
            code="idempotency_key_required",
            title="Idempotency-Key is required",
            detail="Supply an Idempotency-Key header.",
        )
    request_fingerprint = fingerprint(command.model_dump(mode="json"))
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.subject == principal.subject,
            IdempotencyRecord.route == "reference-import",
            IdempotencyRecord.study_id == study_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise ProblemException(
                status_code=409,
                code="idempotency_key_reused",
                title="Idempotency key was reused",
                detail="The key is already bound to a different import.",
            )
        batch = session.get(ReferenceImportBatch, existing.resource_id)
        if batch is None:
            raise RuntimeError("idempotency record references a missing Reference import")
        prior_records = [session.get(ReferenceRecord, UUID(item)) for item in batch.reference_ids]
        return ReferenceCollection(
            items=tuple(_response(session, item) for item in prior_records if item is not None)
        )
    keys = [(item.reference_type.value, item.natural_key) for item in command.items]
    if len(keys) != len(set(keys)):
        raise ProblemException(
            status_code=422,
            code="duplicate_reference_key",
            title="Reference import is invalid",
            detail="Natural keys must be unique within each Reference type.",
        )
    created_records: list[ReferenceRecord] = []
    for item in command.items:
        record = ReferenceRecord(
            study_id=study_id,
            reference_type=item.reference_type.value,
            natural_key=item.natural_key,
            display_name=item.display_name,
        )
        session.add(record)
        session.flush()
        payload = item.value.model_dump(mode="json")
        session.add(
            ReferenceRevision(
                reference_id=record.id,
                study_id=study_id,
                revision=1,
                schema_version=item.value.schema_version,
                value=payload,
                fingerprint=fingerprint(payload),
                created_by=principal.subject,
            )
        )
        created_records.append(record)
    batch = ReferenceImportBatch(
        study_id=study_id,
        input_fingerprint=request_fingerprint,
        reference_ids=[str(item.id) for item in created_records],
        created_by=principal.subject,
    )
    session.add(batch)
    session.flush()
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route="reference-import",
            study_id=study_id,
            key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_type="reference_import_batch",
            resource_id=batch.id,
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="duplicate_reference_key",
            title="Reference import conflicts",
            detail="At least one natural key already exists in this study.",
        ) from error
    return ReferenceCollection(items=tuple(_response(session, item) for item in created_records))


@router.get("/studies/{study_id}/references/export", response_model=ReferenceImport)
def export_references(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReferenceImport:
    """Return a non-persisting exact export of current Reference values."""

    studies.require_access(session, study_id, principal)
    records = session.scalars(
        select(ReferenceRecord)
        .where(ReferenceRecord.study_id == study_id)
        .order_by(ReferenceRecord.reference_type, ReferenceRecord.natural_key)
    )
    items = []
    for record in records:
        revision = _current_revision(session, record)
        items.append(
            ReferenceCreate(
                reference_type=ReferenceType(record.reference_type),
                natural_key=record.natural_key,
                display_name=record.display_name,
                value=ReferenceValue.model_validate(revision.value),
            )
        )
    return ReferenceImport(items=tuple(items))
