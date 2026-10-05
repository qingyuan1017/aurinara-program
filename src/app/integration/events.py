"""Registered public event schemas and projectors."""

from typing import Protocol

from app.common.outbox import OutboxEvent
from app.integration.security import PublicEvent


class PublicEventProjector(Protocol):
    """Typed public-event projection capability."""

    def project(self, event: OutboxEvent) -> PublicEvent: ...


class IntegrationEventProjector:
    """Project registered internal events into the minimal public envelope."""

    def __init__(self, event_types: frozenset[str] | None = None) -> None:
        self.event_types = event_types or frozenset({"studies.created"})

    def project(self, event: OutboxEvent) -> PublicEvent:
        """Project only explicitly registered event types."""

        if (
            event.event_type not in self.event_types
            or event.schema_version != "1.0.0"
            or event.study_id is None
        ):
            raise ValueError("outbox event has no registered public projector")
        return PublicEvent(
            id=event.id,
            type=event.event_type,
            schema_version=event.schema_version,
            occurred_at=event.occurred_at,
            study_id=event.study_id,
            module_key=event.module_key,
            subject_type=event.subject_type,
            subject_id=event.subject_id,
            subject_revision=event.subject_revision,
            correlation_id=event.correlation_id,
            data=event.payload,
        )
