"""Study-scoped external integration configuration APIs."""

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_session
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.idempotency import IdempotencyRecord
from app.common.problems import ProblemException
from app.config import Settings
from app.integration.models import (
    ExternalIdentifier,
    Integration,
    IntegrationDeliveryAttempt,
    IntegrationSecretVersion,
    IntegrationSubscription,
)
from app.integration.secrets import SecretCipher
from app.integration.security import UnsafeCallbackUrl, validate_callback_url
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import DependencyCapability
from app.kernel.registry import ModuleRegistry, ModuleRegistryError
from app.studies.service import StudyService

router = APIRouter(tags=["integrations"])
studies = StudyService()


class IntegrationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    integration_code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    display_name: str
    direction: Literal["inbound", "outbound", "bidirectional"]
    external_subject: str | None = None
    allowed_modules: tuple[str, ...]


class IntegrationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = None
    external_subject: str | None = None
    allowed_modules: tuple[str, ...] | None = None
    status: Literal["active", "retired"] | None = None


class IntegrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    integration_code: str
    display_name: str
    direction: str
    external_subject: str | None
    allowed_modules: list[str]
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime


class SecretRotationResponse(BaseModel):
    integration_id: UUID
    version: int
    fingerprint: str
    signing_secret: str


class IntegrationCreated(BaseModel):
    integration: IntegrationResponse
    secret: SecretRotationResponse


class SubscriptionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    callback_url: str
    event_types: tuple[str, ...]
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=10, ge=1, le=30)


class SubscriptionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    callback_url: str | None = None
    event_types: tuple[str, ...] | None = None
    headers: dict[str, str] | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=30)
    status: str | None = Field(default=None, pattern=r"^(active|retired)$")


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    integration_id: UUID
    callback_url: str
    event_types: list[str]
    headers: dict[str, str]
    timeout_seconds: int
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime


class ExternalIdentifierWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_entity_type: str
    external_id: str
    target_module: str
    target_entity_type: str
    target_entity_id: UUID


class ExternalIdentifierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    integration_id: UUID
    external_entity_type: str
    external_id: str
    target_module: str
    target_entity_type: str
    target_entity_id: UUID
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime


class DeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_id: UUID
    subscription_id: UUID
    subscription_revision: int
    attempt_number: int
    destination_fingerprint: str
    status: str
    response_status: int | None
    response_excerpt: str | None
    failure: dict[str, object] | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


def _require_integration(session: Session, identifier: UUID, principal: Principal) -> Integration:
    integration = session.get(Integration, identifier)
    if integration is None:
        raise ProblemException(
            status_code=404,
            code="integration_not_found",
            title="Integration not found",
            detail="The integration does not exist.",
        )
    studies.require_access(session, integration.study_id, principal)
    return integration


def _validate_modules(registry: ModuleRegistry, modules: tuple[str, ...]) -> None:
    invalid = [key for key in modules if registry.get(key) is None]
    if invalid:
        raise ProblemException(
            status_code=422,
            code="integration_module_invalid",
            title="Integration modules are invalid",
            detail=f"Unknown module keys: {', '.join(invalid)}",
        )


def _rotate(
    session: Session, integration: Integration, settings: Settings
) -> SecretRotationResponse:
    version = (
        int(
            session.scalar(
                select(func.coalesce(func.max(IntegrationSecretVersion.version), 0)).where(
                    IntegrationSecretVersion.integration_id == integration.id
                )
            )
            or 0
        )
        + 1
    )
    plaintext, encrypted, secret_fingerprint = SecretCipher(
        settings.integration_secret_encryption_key.get_secret_value()
    ).generate()
    session.add(
        IntegrationSecretVersion(
            integration_id=integration.id,
            version=version,
            encrypted_secret=encrypted,
            fingerprint=secret_fingerprint,
        )
    )
    return SecretRotationResponse(
        integration_id=integration.id,
        version=version,
        fingerprint=secret_fingerprint,
        signing_secret=plaintext,
    )


@router.post(
    "/studies/{study_id}/integrations",
    response_model=IntegrationCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_integration(
    study_id: UUID,
    command: IntegrationWrite,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> IntegrationCreated:
    studies.require_access(session, study_id, principal)
    _validate_modules(registry, command.allowed_modules)
    integration = Integration(study_id=study_id, **command.model_dump(mode="python"))
    session.add(integration)
    session.flush()
    secret = _rotate(session, integration, request.app.state.settings)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="duplicate_integration_code",
            title="Integration code already exists",
            detail="The integration code is already used in this study.",
        ) from error
    response.headers["ETag"] = etag_for_revision(integration.revision)
    return IntegrationCreated(
        integration=IntegrationResponse.model_validate(integration), secret=secret
    )


@router.get("/studies/{study_id}/integrations", response_model=list[IntegrationResponse])
def list_integrations(
    study_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[IntegrationResponse]:
    studies.require_access(session, study_id, principal)
    return [
        IntegrationResponse.model_validate(item)
        for item in session.scalars(select(Integration).where(Integration.study_id == study_id))
    ]


@router.get("/integrations/{integration_id}", response_model=IntegrationResponse)
def get_integration(
    integration_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> IntegrationResponse:
    integration = _require_integration(session, integration_id, principal)
    response.headers["ETag"] = etag_for_revision(integration.revision)
    return IntegrationResponse.model_validate(integration)


@router.patch("/integrations/{integration_id}", response_model=IntegrationResponse)
def patch_integration(
    integration_id: UUID,
    command: IntegrationPatch,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> IntegrationResponse:
    integration = _require_integration(session, integration_id, principal)
    require_matching_etag(if_match, integration.revision)
    if command.allowed_modules is not None:
        _validate_modules(registry, command.allowed_modules)
    for name, value in command.model_dump(exclude_unset=True).items():
        setattr(integration, name, list(value) if name == "allowed_modules" else value)
    integration.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(integration.revision)
    return IntegrationResponse.model_validate(integration)


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def retire_integration(
    integration_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    integration = _require_integration(session, integration_id, principal)
    require_matching_etag(if_match, integration.revision)
    integration.status, integration.revision = "retired", integration.revision + 1
    session.commit()


@router.post("/integrations/{integration_id}/secrets/rotate", response_model=SecretRotationResponse)
def rotate_secret(
    integration_id: UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> SecretRotationResponse:
    integration = _require_integration(session, integration_id, principal)
    result = _rotate(session, integration, request.app.state.settings)
    session.commit()
    return result


@router.post(
    "/integrations/{integration_id}/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription(
    integration_id: UUID,
    command: SubscriptionWrite,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> SubscriptionResponse:
    integration = _require_integration(session, integration_id, principal)
    if integration.status != "active":
        raise ProblemException(
            status_code=409,
            code="integration_inactive",
            title="Integration is inactive",
            detail="Subscriptions cannot be added to a retired integration.",
        )
    registered_events = {
        event for descriptor in registry.descriptors() for event in descriptor.event_types
    }
    if not set(command.event_types) <= registered_events:
        raise ProblemException(
            status_code=422,
            code="event_type_not_registered",
            title="Event type is not registered",
            detail="Every selected event type must be registered by an enabled module.",
        )
    settings: Settings = request.app.state.settings
    try:
        validate_callback_url(
            command.callback_url, allow_loopback=settings.integration_allow_loopback_callbacks
        )
    except UnsafeCallbackUrl as error:
        raise ProblemException(
            status_code=422,
            code="unsafe_callback_url",
            title="Callback URL is unsafe",
            detail=str(error),
        ) from error
    forbidden_headers = {
        name
        for name in command.headers
        if name.lower() in {"authorization", "host", "content-length"}
    }
    if forbidden_headers:
        raise ProblemException(
            status_code=422,
            code="subscription_header_forbidden",
            title="Subscription header is forbidden",
            detail="Authorization, Host, and Content-Length cannot be configured.",
        )
    subscription = IntegrationSubscription(
        integration_id=integration.id,
        callback_url=command.callback_url,
        event_types=list(command.event_types),
        headers=command.headers,
        timeout_seconds=command.timeout_seconds,
    )
    session.add(subscription)
    session.commit()
    response.headers["ETag"] = etag_for_revision(subscription.revision)
    return SubscriptionResponse.model_validate(subscription)


@router.get(
    "/integrations/{integration_id}/subscriptions", response_model=list[SubscriptionResponse]
)
def list_subscriptions(
    integration_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[SubscriptionResponse]:
    _require_integration(session, integration_id, principal)
    return [
        SubscriptionResponse.model_validate(item)
        for item in session.scalars(
            select(IntegrationSubscription).where(
                IntegrationSubscription.integration_id == integration_id
            )
        )
    ]


@router.post(
    "/integrations/{integration_id}/external-identifiers",
    response_model=ExternalIdentifierResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_external_identifier(
    integration_id: UUID,
    command: ExternalIdentifierWrite,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ExternalIdentifierResponse:
    integration = _require_integration(session, integration_id, principal)
    if command.target_module not in integration.allowed_modules:
        raise ProblemException(
            status_code=403,
            code="integration_module_forbidden",
            title="Target module is not allowed",
            detail="The integration is not scoped to this module.",
        )
    try:
        resolver = cast(
            DependencyCapability,
            registry.require_handler(command.target_module, ModuleCapability.ENTITY_RESOLUTION),
        )
    except ModuleRegistryError as error:
        raise ProblemException(
            status_code=422,
            code="external_target_unsupported",
            title="External target is unsupported",
            detail=error.detail,
        ) from error
    if (
        resolver.resolve_entity(session, command.target_entity_type, command.target_entity_id)
        != integration.study_id
    ):
        raise ProblemException(
            status_code=422,
            code="external_target_invalid",
            title="External target is invalid",
            detail="The target does not exist in this study.",
        )
    binding = ExternalIdentifier(integration_id=integration.id, **command.model_dump(mode="python"))
    session.add(binding)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ProblemException(
            status_code=409,
            code="duplicate_external_identifier",
            title="External identifier already exists",
            detail="The external entity type and identifier are already bound.",
        ) from error
    return ExternalIdentifierResponse.model_validate(binding)


@router.get(
    "/integrations/{integration_id}/external-identifiers",
    response_model=list[ExternalIdentifierResponse],
)
def list_external_identifiers(
    integration_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ExternalIdentifierResponse]:
    _require_integration(session, integration_id, principal)
    return [
        ExternalIdentifierResponse.model_validate(item)
        for item in session.scalars(
            select(ExternalIdentifier).where(ExternalIdentifier.integration_id == integration_id)
        )
    ]


@router.get("/integrations/{integration_id}/deliveries", response_model=list[DeliveryResponse])
def list_deliveries(
    integration_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[DeliveryResponse]:
    _require_integration(session, integration_id, principal)
    statement = (
        select(IntegrationDeliveryAttempt)
        .join(IntegrationSubscription)
        .where(IntegrationSubscription.integration_id == integration_id)
    )
    return [DeliveryResponse.model_validate(item) for item in session.scalars(statement)]


def _require_subscription(
    session: Session, subscription_id: UUID, principal: Principal
) -> tuple[IntegrationSubscription, Integration]:
    subscription = session.get(IntegrationSubscription, subscription_id)
    if subscription is None:
        raise ProblemException(
            status_code=404,
            code="integration_subscription_not_found",
            title="Integration subscription not found",
            detail="The subscription does not exist.",
        )
    integration = _require_integration(session, subscription.integration_id, principal)
    return subscription, integration


def _validate_subscription(
    command: SubscriptionWrite | SubscriptionPatch,
    *,
    registry: ModuleRegistry,
    settings: Settings,
) -> None:
    if command.event_types is not None:
        registered_events = {
            event for descriptor in registry.descriptors() for event in descriptor.event_types
        }
        if not set(command.event_types) <= registered_events:
            raise ProblemException(
                status_code=422,
                code="event_type_not_registered",
                title="Event type is not registered",
                detail="Every selected event type must be registered by an enabled module.",
            )
    if command.callback_url is not None:
        try:
            validate_callback_url(
                command.callback_url,
                allow_loopback=settings.integration_allow_loopback_callbacks,
            )
        except UnsafeCallbackUrl as error:
            raise ProblemException(
                status_code=422,
                code="unsafe_callback_url",
                title="Callback URL is unsafe",
                detail=str(error),
            ) from error
    if command.headers is not None:
        forbidden_headers = {
            name
            for name in command.headers
            if name.lower() in {"authorization", "host", "content-length"}
        }
        if forbidden_headers:
            raise ProblemException(
                status_code=422,
                code="subscription_header_forbidden",
                title="Subscription header is forbidden",
                detail="Authorization, Host, and Content-Length cannot be configured.",
            )


@router.get("/integration-subscriptions/{subscription_id}", response_model=SubscriptionResponse)
def get_subscription(
    subscription_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> SubscriptionResponse:
    subscription, _ = _require_subscription(session, subscription_id, principal)
    response.headers["ETag"] = etag_for_revision(subscription.revision)
    return SubscriptionResponse.model_validate(subscription)


@router.patch("/integration-subscriptions/{subscription_id}", response_model=SubscriptionResponse)
def patch_subscription(
    subscription_id: UUID,
    command: SubscriptionPatch,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SubscriptionResponse:
    subscription, integration = _require_subscription(session, subscription_id, principal)
    require_matching_etag(if_match, subscription.revision)
    if integration.status != "active":
        raise ProblemException(
            status_code=409,
            code="integration_inactive",
            title="Integration is inactive",
            detail="A retired integration cannot be changed.",
        )
    _validate_subscription(command, registry=registry, settings=request.app.state.settings)
    for name, value in command.model_dump(exclude_unset=True).items():
        setattr(subscription, name, list(value) if name == "event_types" else value)
    subscription.revision += 1
    session.commit()
    response.headers["ETag"] = etag_for_revision(subscription.revision)
    return SubscriptionResponse.model_validate(subscription)


@router.delete(
    "/integration-subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT
)
def retire_subscription(
    subscription_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    subscription, _ = _require_subscription(session, subscription_id, principal)
    require_matching_etag(if_match, subscription.revision)
    subscription.status = "retired"
    subscription.revision += 1
    session.commit()


def _require_binding(
    session: Session, binding_id: UUID, principal: Principal
) -> tuple[ExternalIdentifier, Integration]:
    binding = session.get(ExternalIdentifier, binding_id)
    if binding is None:
        raise ProblemException(
            status_code=404,
            code="external_identifier_not_found",
            title="External identifier not found",
            detail="The binding does not exist.",
        )
    integration = _require_integration(session, binding.integration_id, principal)
    return binding, integration


@router.get("/external-identifiers/{binding_id}", response_model=ExternalIdentifierResponse)
def get_external_identifier(
    binding_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ExternalIdentifierResponse:
    binding, _ = _require_binding(session, binding_id, principal)
    response.headers["ETag"] = etag_for_revision(binding.revision)
    return ExternalIdentifierResponse.model_validate(binding)


@router.delete("/external-identifiers/{binding_id}", status_code=status.HTTP_204_NO_CONTENT)
def retire_external_identifier(
    binding_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    binding, integration = _require_binding(session, binding_id, principal)
    require_matching_etag(if_match, binding.revision)
    if integration.status != "active":
        raise ProblemException(
            status_code=409,
            code="integration_inactive",
            title="Integration is inactive",
            detail="A retired integration cannot be changed.",
        )
    binding.status = "retired"
    binding.revision += 1
    session.commit()


def _require_delivery(
    session: Session, delivery_id: UUID, principal: Principal
) -> tuple[IntegrationDeliveryAttempt, IntegrationSubscription, Integration]:
    delivery = session.get(IntegrationDeliveryAttempt, delivery_id)
    if delivery is None:
        raise ProblemException(
            status_code=404,
            code="integration_delivery_not_found",
            title="Integration delivery not found",
            detail="The delivery attempt does not exist.",
        )
    subscription, integration = _require_subscription(session, delivery.subscription_id, principal)
    return delivery, subscription, integration


@router.get("/integration-deliveries/{delivery_id}", response_model=DeliveryResponse)
def get_delivery(
    delivery_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> DeliveryResponse:
    delivery, _, _ = _require_delivery(session, delivery_id, principal)
    return DeliveryResponse.model_validate(delivery)


@router.post(
    "/integration-deliveries/{delivery_id}/redeliver",
    response_model=DeliveryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def redeliver(
    delivery_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DeliveryResponse:
    delivery, subscription, integration = _require_delivery(session, delivery_id, principal)
    if not idempotency_key:
        raise ProblemException(
            status_code=400,
            code="idempotency_key_required",
            title="Idempotency-Key is required",
            detail="Supply an Idempotency-Key header.",
        )
    if integration.status != "active" or subscription.status != "active":
        raise ProblemException(
            status_code=409,
            code="integration_inactive",
            title="Delivery cannot be redelivered",
            detail="The integration and subscription must both be active.",
        )
    request_fingerprint = fingerprint({"delivery_id": str(delivery_id)})
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.subject == principal.subject,
            IdempotencyRecord.route == "integration-delivery-redeliver",
            IdempotencyRecord.study_id == integration.study_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise ProblemException(
                status_code=409,
                code="idempotency_key_reused",
                title="Idempotency key was reused",
                detail="The key is already bound to a different delivery.",
            )
        prior = session.get(IntegrationDeliveryAttempt, existing.resource_id)
        if prior is None:
            raise RuntimeError("idempotency record references a missing delivery")
        return DeliveryResponse.model_validate(prior)
    next_attempt = (
        int(
            session.scalar(
                select(func.coalesce(func.max(IntegrationDeliveryAttempt.attempt_number), 0)).where(
                    IntegrationDeliveryAttempt.event_id == delivery.event_id,
                    IntegrationDeliveryAttempt.subscription_id == subscription.id,
                )
            )
            or 0
        )
        + 1
    )
    created = IntegrationDeliveryAttempt(
        event_id=delivery.event_id,
        subscription_id=subscription.id,
        subscription_revision=subscription.revision,
        attempt_number=next_attempt,
        destination_fingerprint=fingerprint({"url": subscription.callback_url}),
        status="queued",
    )
    session.add(created)
    session.flush()
    session.add(
        IdempotencyRecord(
            subject=principal.subject,
            route="integration-delivery-redeliver",
            study_id=integration.study_id,
            key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_type="integration_delivery_attempt",
            resource_id=created.id,
        )
    )
    session.commit()
    return DeliveryResponse.model_validate(created)
