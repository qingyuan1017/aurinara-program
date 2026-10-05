"""Outbound integration SSRF and signing invariants."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.integration.security import (
    PublicEvent,
    UnsafeCallbackUrl,
    sign_event,
    validate_callback_url,
)


def _resolve_to(address: str):
    def resolve(_host: str, _port: int) -> tuple[str, ...]:
        return (address,)

    return resolve


@pytest.mark.parametrize(
    "address",
    ["10.0.0.1", "169.254.169.254", "127.0.0.1", "::1", "0.0.0.0"],
)
def test_production_callback_rejects_non_public_addresses(address: str) -> None:
    with pytest.raises(UnsafeCallbackUrl):
        validate_callback_url(
            "https://callback.example/events",
            allow_loopback=False,
            resolver=_resolve_to(address),
        )


def test_local_callback_allows_only_explicit_loopback_exception() -> None:
    assert (
        validate_callback_url(
            "http://localhost:8080/events",
            allow_loopback=True,
            resolver=_resolve_to("127.0.0.1"),
        )
        == "http://localhost:8080/events"
    )


def test_event_signature_covers_exact_body_and_metadata() -> None:
    event = PublicEvent(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        type="studies.created",
        schema_version="1.0.0",
        occurred_at=datetime(2026, 10, 4, tzinfo=UTC),
        study_id=UUID("00000000-0000-0000-0000-000000000002"),
        module_key="integration",
        subject_type="study",
        subject_id=UUID("00000000-0000-0000-0000-000000000002"),
        subject_revision=1,
        correlation_id="request-1",
        data={"study_code": "SYNTHETIC"},
    )

    first = sign_event(event, b"secret", datetime(2026, 10, 4, 1, tzinfo=UTC))
    second = sign_event(event, b"secret", datetime(2026, 10, 4, 1, tzinfo=UTC))

    assert first == second
    assert first.content_digest.startswith("sha256=")
    assert first.signature.startswith("sha256=")
    assert b"object_key" not in first.body
