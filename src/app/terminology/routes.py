"""Study sponsor terminology extension APIs with immutable snapshots."""

from datetime import datetime
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
from app.common.outbox import OutboxEvent
from app.common.problems import ProblemException
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import DependencyCapability
from app.kernel.registry import ModuleRegistry
from app.studies.service import StudyService
from app.terminology.models import (
    TerminologyCodelist,
    TerminologyExtension,
    TerminologyExtensionRevision,
    TerminologyExtensionTerm,
    TerminologyRelease,
    TerminologyTerm,
)

router = APIRouter(tags=["terminology"])
studies = StudyService()
artifacts = ArtifactService()


class ExtensionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
    name: str = Field(min_length=1, max_length=255)
    base_release_id: UUID
    codelist_code: str = Field(min_length=1, max_length=64)


class ExtensionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, pattern=r"^(active|retired)$")


class ExtensionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    code: str
    name: str
    base_release_id: UUID
    codelist_code: str
    status: str
    revision: int
    current_revision_id: UUID


class ExtensionRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    extension_id: UUID
    study_id: UUID
    revision: int
    payload: dict[str, object]
    fingerprint: str
    created_by: str
    created_at: datetime


class ExtensionTermWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=128)
    submission_value: str = Field(min_length=1, max_length=255)
    decode: str = Field(min_length=1, max_length=1000)
    definition: str | None = Field(default=None, max_length=4000)
    preferred_term: str | None = Field(default=None, max_length=1000)
    synonyms: list[str] = Field(default_factory=list)


class ExtensionTermPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_value: str | None = Field(default=None, min_length=1, max_length=255)
    decode: str | None = Field(default=None, min_length=1, max_length=1000)
    definition: str | None = Field(default=None, max_length=4000)
    preferred_term: str | None = Field(default=None, max_length=1000)
    synonyms: list[str] | None = None


class ExtensionTermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    extension_id: UUID
    code: str
    submission_value: str
    decode: str
    definition: str | None
    preferred_term: str | None
    synonyms: list[str]
    created_at: datetime
    updated_at: datetime


def _require_extension(
    session: Session, extension_id: UUID, principal: Principal
) -> TerminologyExtension:
    extension = session.get(TerminologyExtension, extension_id)
    if extension is None:
        raise ProblemException(
            status_code=404,
            code="terminology_extension_not_found",
            title="Terminology extension not found",
            detail="The sponsor extension does not exist.",
        )
    studies.require_access(session, extension.study_id, principal)
    return extension


def _current_revision(
    session: Session, extension: TerminologyExtension
) -> TerminologyExtensionRevision:
    revision = session.scalar(
        select(TerminologyExtensionRevision).where(
            TerminologyExtensionRevision.extension_id == extension.id,
            TerminologyExtensionRevision.revision == extension.revision,
        )
    )
    if revision is None:
        raise RuntimeError("terminology extension current revision is missing")
    return revision


def _response(session: Session, extension: TerminologyExtension) -> ExtensionResponse:
    return ExtensionResponse(
        id=extension.id,
        study_id=extension.study_id,
        code=extension.code,
        name=extension.name,
        base_release_id=extension.base_release_id,
        codelist_code=extension.codelist_code,
        status=extension.status,
        revision=extension.revision,
        current_revision_id=_current_revision(session, extension).id,
    )


def _snapshot_payload(session: Session, extension: TerminologyExtension) -> dict[str, object]:
    terms = session.scalars(
        select(TerminologyExtensionTerm)
        .where(TerminologyExtensionTerm.extension_id == extension.id)
        .order_by(TerminologyExtensionTerm.code, TerminologyExtensionTerm.id)
    )
    return {
        "schema_version": "1.0.0",
        "code": extension.code,
        "name": extension.name,
        "base_release_id": str(extension.base_release_id),
        "codelist_code": extension.codelist_code,
        "status": extension.status,
        "terms": [
            {
                "id": str(term.id),
                "code": term.code,
                "submission_value": term.submission_value,
                "decode": term.decode,
                "definition": term.definition,
                "preferred_term": term.preferred_term,
                "synonyms": term.synonyms,
            }
            for term in terms
        ],
    }


def _add_snapshot(
    session: Session, extension: TerminologyExtension, principal: Principal
) -> TerminologyExtensionRevision:
    payload = _snapshot_payload(session, extension)
    revision = TerminologyExtensionRevision(
        extension_id=extension.id,
        study_id=extension.study_id,
        revision=extension.revision,
        payload=payload,
        fingerprint=fingerprint(payload),
        created_by=principal.subject,
    )
    session.add(revision)
    session.flush()
    return revision


def _mark_consumers(
    session: Session, registry: ModuleRegistry, superseded_revision_id: UUID
) -> None:
    for descriptor in registry.descriptors():
        if ModuleCapability.STALENESS not in descriptor.capabilities:
            continue
        handler = cast(
            DependencyCapability,
            registry.require_handler(descriptor.module_key, ModuleCapability.STALENESS),
        )
        for aggregate_id in handler.mark_dependency_refresh(session, superseded_revision_id):
            artifacts.mark_owner_stale(
                session, owner_type=next(iter(descriptor.entity_types)), owner_id=aggregate_id
            )


def _record_revision_event(session: Session, extension: TerminologyExtension) -> None:
    session.add(
        OutboxEvent(
            id=uuid4(),
            study_id=extension.study_id,
            event_type="terminology.extension_revised",
            schema_version="1.0.0",
            module_key="terminology",
            subject_type="terminology_extension",
            subject_id=extension.id,
            subject_revision=extension.revision,
            correlation_id=str(extension.id),
            payload={"status": extension.status, "revision": extension.revision},
        )
    )


def _validate_base(session: Session, release_id: UUID, codelist_code: str) -> TerminologyCodelist:
    release = session.get(TerminologyRelease, release_id)
    codelist = session.scalar(
        select(TerminologyCodelist).where(
            TerminologyCodelist.release_id == release_id,
            TerminologyCodelist.code == codelist_code,
        )
    )
    if release is None or release.lifecycle not in {"active", "deprecated"} or codelist is None:
        raise ProblemException(
            status_code=422,
            code="terminology_extension_base_invalid",
            title="Terminology extension base is invalid",
            detail="The exact available release and codelist must exist.",
        )
    if not codelist.extensible:
        raise ProblemException(
            status_code=422,
            code="terminology_codelist_not_extensible",
            title="Terminology codelist is not extensible",
            detail="Sponsor terms can only be added to a codelist published as extensible.",
        )
    return codelist


def _reject_published_collision(
    session: Session, extension: TerminologyExtension, *, code: str, submission_value: str
) -> None:
    codelist = _validate_base(session, extension.base_release_id, extension.codelist_code)
    collision = session.scalar(
        select(TerminologyTerm.id).where(
            TerminologyTerm.codelist_id == codelist.id,
            (TerminologyTerm.code == code) | (TerminologyTerm.submission_value == submission_value),
        )
    )
    if collision is not None:
        raise ProblemException(
            status_code=422,
            code="published_term_shadowed",
            title="Published term cannot be shadowed",
            detail="An extension term must use a distinct code and submission value.",
        )


@router.post(
    "/studies/{study_id}/terminology-extensions",
    response_model=ExtensionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_extension(
    study_id: UUID,
    command: ExtensionCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ExtensionResponse:
    studies.require_access(session, study_id, principal)
    _validate_base(session, command.base_release_id, command.codelist_code)
    extension = TerminologyExtension(study_id=study_id, **command.model_dump(mode="python"))
    session.add(extension)
    session.flush()
    _add_snapshot(session, extension, principal)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="duplicate_terminology_extension",
            title="Terminology extension already exists",
            detail="The extension code is already used in this study.",
        ) from error
    response.headers["ETag"] = etag_for_revision(extension.revision)
    return _response(session, extension)


@router.get("/studies/{study_id}/terminology-extensions", response_model=list[ExtensionResponse])
def list_extensions(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ExtensionResponse]:
    studies.require_access(session, study_id, principal)
    return [
        _response(session, item)
        for item in session.scalars(
            select(TerminologyExtension).where(TerminologyExtension.study_id == study_id)
        )
    ]


@router.get("/terminology-extensions/{extension_id}", response_model=ExtensionResponse)
def get_extension(
    extension_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ExtensionResponse:
    extension = _require_extension(session, extension_id, principal)
    response.headers["ETag"] = etag_for_revision(extension.revision)
    return _response(session, extension)


@router.patch("/terminology-extensions/{extension_id}", response_model=ExtensionResponse)
def patch_extension(
    extension_id: UUID,
    command: ExtensionPatch,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ExtensionResponse:
    extension = _require_extension(session, extension_id, principal)
    require_matching_etag(if_match, extension.revision)
    old_revision = _current_revision(session, extension)
    for name, value in command.model_dump(exclude_unset=True).items():
        setattr(extension, name, value)
    extension.revision += 1
    _add_snapshot(session, extension, principal)
    _mark_consumers(session, registry, old_revision.id)
    _record_revision_event(session, extension)
    session.commit()
    response.headers["ETag"] = etag_for_revision(extension.revision)
    return _response(session, extension)


@router.get(
    "/terminology-extensions/{extension_id}/revisions",
    response_model=list[ExtensionRevisionResponse],
)
def list_extension_revisions(
    extension_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ExtensionRevisionResponse]:
    extension = _require_extension(session, extension_id, principal)
    return [
        ExtensionRevisionResponse.model_validate(item)
        for item in session.scalars(
            select(TerminologyExtensionRevision)
            .where(TerminologyExtensionRevision.extension_id == extension.id)
            .order_by(TerminologyExtensionRevision.revision)
        )
    ]


@router.get(
    "/terminology-extension-revisions/{revision_id}",
    response_model=ExtensionRevisionResponse,
)
def get_extension_revision(
    revision_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ExtensionRevisionResponse:
    revision = session.get(TerminologyExtensionRevision, revision_id)
    if revision is None:
        raise ProblemException(
            status_code=404,
            code="terminology_extension_revision_not_found",
            title="Terminology extension revision not found",
            detail="The exact extension revision does not exist.",
        )
    studies.require_access(session, revision.study_id, principal)
    return ExtensionRevisionResponse.model_validate(revision)


@router.get(
    "/terminology-extension-revisions/{revision_id}/terms",
    response_model=list[dict[str, object]],
)
def list_revision_terms(
    revision_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[dict[str, object]]:
    revision = session.get(TerminologyExtensionRevision, revision_id)
    if revision is None:
        raise ProblemException(
            status_code=404,
            code="terminology_extension_revision_not_found",
            title="Terminology extension revision not found",
            detail="The exact extension revision does not exist.",
        )
    studies.require_access(session, revision.study_id, principal)
    terms = revision.payload.get("terms", [])
    return [dict(item) for item in cast(list[dict[str, object]], terms)]


@router.get(
    "/terminology-extensions/{extension_id}/terms", response_model=list[ExtensionTermResponse]
)
def list_extension_terms(
    extension_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ExtensionTermResponse]:
    _require_extension(session, extension_id, principal)
    return [
        ExtensionTermResponse.model_validate(item)
        for item in session.scalars(
            select(TerminologyExtensionTerm)
            .where(TerminologyExtensionTerm.extension_id == extension_id)
            .order_by(TerminologyExtensionTerm.code)
        )
    ]


@router.post(
    "/terminology-extensions/{extension_id}/terms",
    response_model=ExtensionTermResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_extension_term(
    extension_id: UUID,
    command: ExtensionTermWrite,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ExtensionTermResponse:
    extension = _require_extension(session, extension_id, principal)
    require_matching_etag(if_match, extension.revision)
    _reject_published_collision(
        session,
        extension,
        code=command.code,
        submission_value=command.submission_value,
    )
    old_revision = _current_revision(session, extension)
    term = TerminologyExtensionTerm(extension_id=extension.id, **command.model_dump())
    session.add(term)
    session.flush()
    extension.revision += 1
    _add_snapshot(session, extension, principal)
    _mark_consumers(session, registry, old_revision.id)
    _record_revision_event(session, extension)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="duplicate_extension_term",
            title="Extension term already exists",
            detail="The code or submission value is already used in this extension.",
        ) from error
    response.headers["ETag"] = etag_for_revision(extension.revision)
    return ExtensionTermResponse.model_validate(term)


def _require_term(
    session: Session, term_id: UUID, principal: Principal
) -> tuple[TerminologyExtensionTerm, TerminologyExtension]:
    term = session.get(TerminologyExtensionTerm, term_id)
    if term is None:
        raise ProblemException(
            status_code=404,
            code="terminology_extension_term_not_found",
            title="Terminology extension term not found",
            detail="The extension term does not exist.",
        )
    return term, _require_extension(session, term.extension_id, principal)


@router.patch("/terminology-extension-terms/{term_id}", response_model=ExtensionTermResponse)
def patch_extension_term(
    term_id: UUID,
    command: ExtensionTermPatch,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ExtensionTermResponse:
    term, extension = _require_term(session, term_id, principal)
    require_matching_etag(if_match, extension.revision)
    submission_value = command.submission_value or term.submission_value
    _reject_published_collision(
        session, extension, code=term.code, submission_value=submission_value
    )
    old_revision = _current_revision(session, extension)
    for name, value in command.model_dump(exclude_unset=True).items():
        setattr(term, name, value)
    extension.revision += 1
    session.flush()
    _add_snapshot(session, extension, principal)
    _mark_consumers(session, registry, old_revision.id)
    _record_revision_event(session, extension)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="duplicate_extension_term",
            title="Extension term already exists",
            detail="The submission value is already used in this extension.",
        ) from error
    response.headers["ETag"] = etag_for_revision(extension.revision)
    return ExtensionTermResponse.model_validate(term)


@router.delete("/terminology-extension-terms/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_extension_term(
    term_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    term, extension = _require_term(session, term_id, principal)
    require_matching_etag(if_match, extension.revision)
    old_revision = _current_revision(session, extension)
    session.delete(term)
    session.flush()
    extension.revision += 1
    _add_snapshot(session, extension, principal)
    _mark_consumers(session, registry, old_revision.id)
    _record_revision_event(session, extension)
    session.commit()
