"""At-least-once outbound event scheduling and bounded HTTP delivery."""

from datetime import UTC, datetime
from typing import cast

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.canonical import fingerprint
from app.common.metrics import emit_metric
from app.common.outbox import OutboxEvent
from app.config import Settings
from app.integration.events import PublicEventProjector
from app.integration.models import (
    Integration,
    IntegrationDeliveryAttempt,
    IntegrationSecretVersion,
    IntegrationSubscription,
)
from app.integration.secrets import SecretCipher
from app.integration.security import sign_event, validate_callback_url
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry


class DeliveryService:
    """Schedule immutable events and perform one bounded delivery attempt."""

    def __init__(self, registry: ModuleRegistry) -> None:
        self._registry = registry

    def schedule(self, session: Session) -> int:
        """Create first attempts idempotently for all matching committed events."""

        created = 0
        events = session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.processed_at.is_(None))
            .with_for_update(skip_locked=True)
        )
        for event in events:
            subscriptions = session.scalars(
                select(IntegrationSubscription)
                .join(Integration)
                .where(
                    Integration.study_id == event.study_id,
                    Integration.status == "active",
                    IntegrationSubscription.status == "active",
                )
            )
            for subscription in subscriptions:
                if event.event_type not in subscription.event_types:
                    continue
                exists = session.scalar(
                    select(IntegrationDeliveryAttempt.id).where(
                        IntegrationDeliveryAttempt.event_id == event.id,
                        IntegrationDeliveryAttempt.subscription_id == subscription.id,
                        IntegrationDeliveryAttempt.attempt_number == 1,
                    )
                )
                if exists is None:
                    session.add(
                        IntegrationDeliveryAttempt(
                            event_id=event.id,
                            subscription_id=subscription.id,
                            subscription_revision=subscription.revision,
                            attempt_number=1,
                            destination_fingerprint=fingerprint({"url": subscription.callback_url}),
                            status="queued",
                        )
                    )
                    created += 1
            event.processed_at = datetime.now(UTC)
        return created

    def deliver_one(self, session: Session, settings: Settings) -> bool:
        """Deliver one queued attempt with DNS revalidation and response bounds."""

        attempt = session.scalar(
            select(IntegrationDeliveryAttempt)
            .where(IntegrationDeliveryAttempt.status == "queued")
            .order_by(IntegrationDeliveryAttempt.created_at, IntegrationDeliveryAttempt.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if attempt is None:
            return False
        subscription = session.get(IntegrationSubscription, attempt.subscription_id)
        event = session.get(OutboxEvent, attempt.event_id)
        if subscription is None or event is None:
            attempt.status = "dead_letter"
            attempt.failure = {"code": "delivery_input_missing"}
            return True
        integration = session.get(Integration, subscription.integration_id)
        if integration is None or integration.status != "active" or subscription.status != "active":
            attempt.status = "dead_letter"
            attempt.failure = {"code": "integration_inactive"}
            return True
        validate_callback_url(
            subscription.callback_url,
            allow_loopback=settings.integration_allow_loopback_callbacks,
        )
        secret = session.scalar(
            select(IntegrationSecretVersion)
            .where(IntegrationSecretVersion.integration_id == integration.id)
            .order_by(IntegrationSecretVersion.version.desc())
            .limit(1)
        )
        if secret is None:
            attempt.status = "dead_letter"
            attempt.failure = {"code": "signing_secret_missing"}
            return True
        owner = self._registry.owner_of("event_types", event.event_type)
        if owner is None:
            attempt.status = "dead_letter"
            attempt.failure = {"code": "event_projector_missing"}
            return True
        projector = cast(
            PublicEventProjector,
            self._registry.require_handler(owner, ModuleCapability.OUTBOUND_EVENTS),
        )
        try:
            public_event = projector.project(event)
        except ValueError:
            attempt.status = "dead_letter"
            attempt.failure = {"code": "event_projection_invalid"}
            return True
        signed = sign_event(
            public_event,
            SecretCipher(settings.integration_secret_encryption_key.get_secret_value()).decrypt(
                secret.encrypted_secret
            ),
            datetime.now(UTC),
        )
        if len(signed.body) > settings.integration_event_max_bytes:
            attempt.status = "dead_letter"
            attempt.failure = {"code": "event_payload_too_large"}
            return True
        attempt.status = "running"
        attempt.started_at = datetime.now(UTC)
        session.flush()
        headers = {
            **subscription.headers,
            "Content-Type": "application/json",
            "X-Aurinara-Event-ID": signed.event_id,
            "X-Aurinara-Timestamp": signed.timestamp,
            "X-Aurinara-Content-Digest": signed.content_digest,
            "X-Aurinara-Signature": signed.signature,
        }
        try:
            with httpx.Client(
                follow_redirects=False,
                timeout=min(
                    subscription.timeout_seconds, settings.integration_request_timeout_seconds
                ),
            ) as client:
                response = client.post(
                    subscription.callback_url, content=signed.body, headers=headers
                )
                excerpt = response.content[: settings.integration_response_limit_bytes]
            attempt.response_status = response.status_code
            attempt.response_excerpt = excerpt.decode("utf-8", errors="replace")
            attempt.completed_at = datetime.now(UTC)
            if 200 <= response.status_code < 300:
                attempt.status = "succeeded"
            else:
                self._retry_or_dead_letter(session, attempt, settings, "http_error")
        except (httpx.HTTPError, OSError, ValueError) as error:
            attempt.failure = {"code": "delivery_failed", "detail": type(error).__name__}
            attempt.completed_at = datetime.now(UTC)
            self._retry_or_dead_letter(session, attempt, settings, "delivery_failed")
        return True

    def _retry_or_dead_letter(
        self,
        session: Session,
        attempt: IntegrationDeliveryAttempt,
        settings: Settings,
        code: str,
    ) -> None:
        if attempt.attempt_number >= settings.integration_max_attempts:
            attempt.status = "dead_letter"
            attempt.failure = attempt.failure or {"code": code}
            emit_metric(
                "IntegrationDeliveryFailures",
                1,
                environment=settings.app_env,
            )
            return
        attempt.status = "failed"
        session.add(
            IntegrationDeliveryAttempt(
                event_id=attempt.event_id,
                subscription_id=attempt.subscription_id,
                subscription_revision=attempt.subscription_revision,
                attempt_number=attempt.attempt_number + 1,
                destination_fingerprint=attempt.destination_fingerprint,
                status="queued",
            )
        )
