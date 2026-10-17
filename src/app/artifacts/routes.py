"""Authorized source-file and artifact HTTP routes."""

import logging
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_object_storage, get_session
from app.artifacts.schemas import (
    ArtifactCollection,
    ArtifactResponse,
    RepositorySourceFileBind,
    SourceFileBulkResponse,
    SourceFileCollection,
    SourceFileResponse,
)
from app.artifacts.service import ArtifactService
from app.artifacts.storage import ObjectStorage
from app.common.pagination import paginate
from app.common.problems import ProblemException
from app.config import Settings
from app.platform.objects import get_platform_objects

router = APIRouter(tags=["artifacts"])
service = ArtifactService()
logger = logging.getLogger(__name__)


def _stream_object(storage: ObjectStorage, object_key: str) -> Iterator[bytes]:
    with storage.open(object_key) as body:
        while chunk := body.read(1024 * 1024):
            yield chunk


@router.post(
    "/studies/{study_id}/source-files:bind-repository",
    response_model=SourceFileResponse,
    status_code=status.HTTP_201_CREATED,
)
def bind_repository_source_file(
    study_id: UUID,
    command: RepositorySourceFileBind,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    authorization: Annotated[str, Header(alias="Authorization")],
) -> SourceFileResponse:
    """Bind an exact authorized Repository version without copying its bytes."""

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ProblemException(
            status_code=401,
            code="invalid_token",
            title="Invalid token",
            detail="A bearer token is required for Repository binding.",
        )
    source_file = service.bind_repository_source_file(
        session,
        study_id=study_id,
        version_id=command.version_id,
        expected_sha256=command.expected_sha256,
        user_access_token=token,
        principal=principal,
    )
    response.headers["Location"] = f"/api/v1/source-files/{source_file.id}"
    return SourceFileResponse.model_validate(source_file)


@router.post(
    "/studies/{study_id}/source-files",
    response_model=SourceFileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_source_file(
    study_id: UUID,
    file: UploadFile,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> SourceFileResponse:
    """Upload immutable bytes and publish their verified metadata."""

    settings: Settings = request.app.state.settings
    source_file = await service.create_source_file(
        session, storage, settings, study_id, file, principal
    )
    response.headers["Location"] = f"/api/v1/source-files/{source_file.id}"
    return SourceFileResponse.model_validate(source_file)


@router.post(
    "/studies/{study_id}/source-files:bulk",
    response_model=SourceFileBulkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_source_files_bulk(
    study_id: UUID,
    files: list[UploadFile],
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> SourceFileBulkResponse:
    """Upload many immutable source files atomically in request order."""

    settings: Settings = request.app.state.settings
    source_files = await service.create_source_files_bulk(
        session, storage, settings, study_id, files, principal
    )
    return SourceFileBulkResponse(
        items=tuple(SourceFileResponse.model_validate(item) for item in source_files)
    )


@router.get("/studies/{study_id}/source-files", response_model=SourceFileCollection)
def list_source_files(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    after: str | None = None,
) -> SourceFileCollection:
    """List source files visible within a study."""

    records, next_cursor = paginate(
        service.list_source_files(session, study_id, principal),
        limit=limit,
        after=after,
        filters={"study_id": str(study_id)},
    )
    return SourceFileCollection(
        items=tuple(SourceFileResponse.model_validate(item) for item in records),
        next_cursor=next_cursor,
    )


@router.get("/source-files/{source_file_id}", response_model=SourceFileResponse)
def get_source_file(
    source_file_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> SourceFileResponse:
    """Get one authorized source-file record."""

    return SourceFileResponse.model_validate(
        service.require_source_file(session, source_file_id, principal)
    )


@router.get("/source-files/{source_file_id}/download")
def download_source_file(
    source_file_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> Response:
    """Stream authorized immutable source bytes."""

    source_file = service.require_source_file(
        session,
        source_file_id,
        principal,
        action="artifact.object.download",
    )
    if source_file.platform_object_id is not None:
        gateway = get_platform_objects()
        if gateway.mode != "disabled":
            try:
                return RedirectResponse(
                    gateway.authorize_download(source_file.platform_object_id),
                    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                )
            except ProblemException:
                if gateway.mode == "enforced":
                    raise
                logger.warning(
                    "Shared object download unavailable in shadow mode; using legacy bytes"
                )
    if source_file.object_key is None:
        raise ProblemException(
            status_code=503,
            code="platform_object_unavailable",
            title="Platform object unavailable",
            detail="This source file exists only in Platform storage.",
        )
    return StreamingResponse(
        _stream_object(storage, source_file.object_key),
        media_type=source_file.media_type,
        headers={"Content-Disposition": f'attachment; filename="{source_file.filename}"'},
    )


@router.get("/studies/{study_id}/artifacts", response_model=ArtifactCollection)
def list_artifacts(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    after: str | None = None,
) -> ArtifactCollection:
    """List immutable artifact metadata."""

    records, next_cursor = paginate(
        service.list_artifacts(session, study_id, principal),
        limit=limit,
        after=after,
        filters={"study_id": str(study_id)},
    )
    return ArtifactCollection(
        items=tuple(ArtifactResponse.from_record(item) for item in records),
        next_cursor=next_cursor,
    )


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(
    artifact_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ArtifactResponse:
    """Get authorized artifact metadata."""

    return ArtifactResponse.from_record(service.require_artifact(session, artifact_id, principal))


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> Response:
    """Stream authorized artifact bytes, including retained stale evidence."""

    artifact = service.require_artifact(
        session,
        artifact_id,
        principal,
        action="artifact.object.download",
    )
    if artifact.platform_object_id is not None:
        gateway = get_platform_objects()
        if gateway.mode != "disabled":
            try:
                return RedirectResponse(
                    gateway.authorize_download(artifact.platform_object_id),
                    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                )
            except ProblemException:
                if gateway.mode == "enforced":
                    raise
                logger.warning(
                    "Shared object download unavailable in shadow mode; using legacy bytes"
                )
    if artifact.object_key is None:
        raise ProblemException(
            status_code=503,
            code="platform_object_unavailable",
            title="Platform object unavailable",
            detail="This artifact exists only in Platform storage.",
        )
    return StreamingResponse(
        _stream_object(storage, artifact.object_key),
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )
