"""Idempotent canonical-study projection consumer."""

import json
import logging
from dataclasses import dataclass
from uuid import UUID

import boto3
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.common.problems import ProblemException
from app.config import Settings
from app.platform.authorization import get_platform_authorization
from app.platform.models import PlatformProjectionEvent
from app.studies.models import Study

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlatformEvent:
    id: UUID
    type: str
    aggregate_id: UUID
    sequence: int
    data: dict[str, object]

    @classmethod
    def parse(cls, payload: dict[str, object]) -> "PlatformEvent":
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("platform event data must be an object")
        return cls(
            id=UUID(str(payload["id"])),
            type=str(payload["type"]),
            aggregate_id=UUID(str(payload["aggregate_id"])),
            sequence=int(payload["sequence"]),
            data=data,
        )


def apply_platform_event(session: Session, event: PlatformEvent) -> bool:
    """Apply once; old or duplicated sequences can never restore stale state."""

    if session.get(PlatformProjectionEvent, event.id) is not None:
        return False
    if event.type not in {"platform.study.created.v1", "platform.study.updated.v1"}:
        return False
    study = session.get(Study, event.aggregate_id)
    code = str(event.data["code"])
    if study is None:
        collision = session.scalar(select(Study).where(Study.code == code))
        if collision is not None:
            raise ProblemException(
                status_code=409,
                code="canonical_study_conflict",
                title="Canonical study conflict",
                detail="The canonical study code is already mapped to another study.",
            )
        study = Study(
            id=event.aggregate_id,
            code=code,
            name=str(event.data["display_name"]),
            sponsor=(str(event.data["sponsor"]) if event.data.get("sponsor") else None),
            created_by="aurinara-platform",
            platform_managed=True,
            platform_revision=event.sequence,
            platform_registry_status=str(event.data["status"]),
        )
        session.add(study)
    elif study.platform_revision is None or event.sequence > study.platform_revision:
        if study.code != code:
            raise ProblemException(
                status_code=409,
                code="canonical_study_conflict",
                title="Canonical study conflict",
                detail="The local study code does not match the canonical identity.",
            )
        study.name = str(event.data["display_name"])
        if "sponsor" in event.data:
            study.sponsor = str(event.data["sponsor"]) if event.data["sponsor"] else None
        study.platform_managed = True
        study.platform_revision = event.sequence
        study.platform_registry_status = str(event.data["status"])
        study.revision += 1
    session.add(
        PlatformProjectionEvent(
            id=event.id,
            event_type=event.type,
            aggregate_id=event.aggregate_id,
            sequence=event.sequence,
        )
    )
    session.flush()
    return True


def consume_once(
    settings: Settings, factory: sessionmaker[Session], *, max_messages: int = 10
) -> int:
    if not settings.platform_event_queue_url:
        raise ValueError("platform event queue URL is not configured")
    sqs = boto3.client(
        "sqs",
        region_name=settings.platform_event_region,
        endpoint_url=settings.platform_event_endpoint_url,
    )
    result = sqs.receive_message(
        QueueUrl=settings.platform_event_queue_url,
        MaxNumberOfMessages=min(max_messages, 10),
        WaitTimeSeconds=10,
    )
    consumed = 0
    for message in result.get("Messages", []):
        try:
            body = json.loads(message["Body"])
            detail = body.get("detail", body)
            event = PlatformEvent.parse(detail)
            with factory.begin() as session:
                apply_platform_event(session, event)
        except Exception:
            logger.exception(
                "Platform projection deferred; message remains available for retry",
                extra={"message_id": message.get("MessageId")},
            )
            continue
        if event.type == "platform.assignment.changed.v1":
            get_platform_authorization().invalidate()
        elif event.type == "platform.membership.changed.v1":
            get_platform_authorization().invalidate(study_id=UUID(str(event.data["study_id"])))
        elif event.type.startswith("platform.user."):
            get_platform_authorization().invalidate()
        sqs.delete_message(
            QueueUrl=settings.platform_event_queue_url,
            ReceiptHandle=message["ReceiptHandle"],
        )
        consumed += 1
    return consumed
