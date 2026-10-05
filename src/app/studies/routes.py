"""Study HTTP routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_session
from app.common.etag import etag_for_revision
from app.common.pagination import paginate
from app.studies.models import Study
from app.studies.schemas import StudyCollection, StudyCreate, StudyPatch, StudyResponse
from app.studies.service import StudyService

router = APIRouter(tags=["studies"])
service = StudyService()


def _with_etag(response: Response, study: Study) -> None:
    response.headers["ETag"] = etag_for_revision(study.revision)


@router.post("/studies", response_model=StudyResponse, status_code=status.HTTP_201_CREATED)
def create_study(
    command: StudyCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> StudyResponse:
    """Create a study and make the caller its owner."""

    study = service.create(session, command, principal)
    _with_etag(response, study)
    response.headers["Location"] = f"/api/v1/studies/{study.id}"
    return StudyResponse.model_validate(study)


@router.get("/studies", response_model=StudyCollection)
def list_studies(
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    after: str | None = None,
) -> StudyCollection:
    """List studies visible to the caller."""

    records, next_cursor = paginate(
        service.list(session, principal), limit=limit, after=after, filters={}
    )
    return StudyCollection(
        items=tuple(StudyResponse.model_validate(item) for item in records),
        next_cursor=next_cursor,
    )


@router.get("/studies/{study_id}", response_model=StudyResponse)
def get_study(
    study_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> StudyResponse:
    """Get one authorized study."""

    study = service.require_access(session, study_id, principal)
    _with_etag(response, study)
    return StudyResponse.model_validate(study)


@router.patch("/studies/{study_id}", response_model=StudyResponse)
def patch_study(
    study_id: UUID,
    command: StudyPatch,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> StudyResponse:
    """Edit study metadata using its current ETag."""

    study = service.patch(session, study_id, command, principal, if_match)
    _with_etag(response, study)
    return StudyResponse.model_validate(study)
