"""Verified human Review item and append-only comment APIs."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_session
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.problems import ProblemException
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import DependencyCapability
from app.kernel.registry import ModuleRegistry, ModuleRegistryError
from app.review.models import ReviewComment, ReviewItem
from app.studies.service import StudyService

router = APIRouter(tags=["review"])
studies = StudyService()


class ReviewItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_module: str
    target_entity_type: str
    target_entity_id: UUID
    field_path: str | None = None
    question: str = Field(min_length=1, max_length=4000)
    assignee: str | None = None
    priority: str = "normal"


class ReviewItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignee: str | None = None
    priority: str | None = None
    status: str | None = None
    disposition: str | None = None
    resolution: str | None = None


class ReviewItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    target_module: str
    target_entity_type: str
    target_entity_id: UUID
    field_path: str | None
    question: str
    assignee: str | None
    priority: str
    status: str
    disposition: str | None
    resolution: str | None
    revision: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=8000)


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    review_item_id: UUID
    author: str
    body: str
    created_at: datetime


def _require(session: Session, item_id: UUID, principal: Principal) -> ReviewItem:
    item = session.get(ReviewItem, item_id)
    if item is None:
        raise ProblemException(
            status_code=404,
            code="review_item_not_found",
            title="Review item not found",
            detail="The Review item does not exist.",
        )
    studies.require_access(session, item.study_id, principal)
    return item


@router.post(
    "/studies/{study_id}/review-items",
    response_model=ReviewItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_review_item(
    study_id: UUID,
    command: ReviewItemCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReviewItemResponse:
    studies.require_access(session, study_id, principal)
    try:
        resolver = cast(
            DependencyCapability,
            registry.require_handler(command.target_module, ModuleCapability.ENTITY_RESOLUTION),
        )
    except ModuleRegistryError as error:
        raise ProblemException(
            status_code=422,
            code="review_target_unsupported",
            title="Review target is unsupported",
            detail=error.detail,
        ) from error
    resolved_study = resolver.resolve_entity(
        session, command.target_entity_type, command.target_entity_id
    )
    if resolved_study != study_id:
        raise ProblemException(
            status_code=422,
            code="review_target_invalid",
            title="Review target is invalid",
            detail="The target does not exist in this study.",
        )
    item = ReviewItem(
        study_id=study_id,
        target_module=command.target_module,
        target_entity_type=command.target_entity_type,
        target_entity_id=command.target_entity_id,
        field_path=command.field_path,
        question=command.question,
        assignee=command.assignee,
        priority=command.priority,
        status="open",
        created_by=principal.subject,
    )
    session.add(item)
    session.commit()
    response.headers["ETag"] = etag_for_revision(item.revision)
    return ReviewItemResponse.model_validate(item)


@router.get("/studies/{study_id}/review-items", response_model=list[ReviewItemResponse])
def list_review_items(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ReviewItemResponse]:
    studies.require_access(session, study_id, principal)
    return [
        ReviewItemResponse.model_validate(item)
        for item in session.scalars(select(ReviewItem).where(ReviewItem.study_id == study_id))
    ]


@router.get("/review-items/{item_id}", response_model=ReviewItemResponse)
def get_review_item(
    item_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReviewItemResponse:
    item = _require(session, item_id, principal)
    response.headers["ETag"] = etag_for_revision(item.revision)
    return ReviewItemResponse.model_validate(item)


@router.patch("/review-items/{item_id}", response_model=ReviewItemResponse)
def patch_review_item(
    item_id: UUID,
    command: ReviewItemPatch,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ReviewItemResponse:
    item = _require(session, item_id, principal)
    require_matching_etag(if_match, item.revision)
    for field_name, value in command.model_dump(exclude_unset=True).items():
        setattr(item, field_name, value)
    item.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(item.revision)
    return ReviewItemResponse.model_validate(item)


@router.get("/review-items/{item_id}/comments", response_model=list[CommentResponse])
def list_comments(
    item_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[CommentResponse]:
    _require(session, item_id, principal)
    return [
        CommentResponse.model_validate(item)
        for item in session.scalars(
            select(ReviewComment)
            .where(ReviewComment.review_item_id == item_id)
            .order_by(ReviewComment.created_at)
        )
    ]


@router.post(
    "/review-items/{item_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    item_id: UUID,
    command: CommentCreate,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> CommentResponse:
    _require(session, item_id, principal)
    comment = ReviewComment(review_item_id=item_id, author=principal.subject, body=command.body)
    session.add(comment)
    session.commit()
    return CommentResponse.model_validate(comment)
