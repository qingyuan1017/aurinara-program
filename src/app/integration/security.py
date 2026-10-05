"""Outbound callback validation, event canonicalization, and signing."""

import hashlib
import hmac
import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.common.canonical import canonical_json

AddressResolver = Callable[[str, int], Iterable[str]]


class UnsafeCallbackUrl(ValueError):
    """Raised when a callback violates outbound SSRF policy."""


class PublicEvent(BaseModel):
    """Versioned minimal envelope delivered to subscribers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    type: str = Field(pattern=r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*)+$")
    schema_version: str
    occurred_at: datetime
    study_id: UUID
    module_key: str
    subject_type: str
    subject_id: UUID
    subject_revision: int
    correlation_id: str
    data: dict[str, object]


@dataclass(frozen=True, slots=True)
class SignedDelivery:
    """Exact event bytes and non-secret signing headers."""

    body: bytes
    event_id: str
    timestamp: str
    content_digest: str
    signature: str


def validate_callback_url(
    value: str,
    *,
    allow_loopback: bool,
    resolver: AddressResolver | None = None,
) -> str:
    """Validate scheme, authority, port, credentials, and every resolved address."""

    parsed = urlsplit(value)
    if parsed.scheme not in ({"https", "http"} if allow_loopback else {"https"}):
        raise UnsafeCallbackUrl("callback must use HTTPS")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise UnsafeCallbackUrl("callback authority is invalid")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in ({443, 8443, 80, 8080} if allow_loopback else {443, 8443}):
        raise UnsafeCallbackUrl("callback port is not permitted")
    resolve = resolver or _resolve_addresses
    addresses = tuple(resolve(parsed.hostname, port))
    if not addresses:
        raise UnsafeCallbackUrl("callback host did not resolve")
    for value_address in addresses:
        address = ipaddress.ip_address(value_address)
        if _unsafe_address(address, allow_loopback=allow_loopback):
            raise UnsafeCallbackUrl("callback resolves to a prohibited address")
    return value


def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                cast(str, item[4][0])
                for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            }
        )
    )


def _unsafe_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address, *, allow_loopback: bool
) -> bool:
    if allow_loopback and address.is_loopback:
        return False
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def sign_event(event: PublicEvent, secret: bytes, timestamp: datetime) -> SignedDelivery:
    """Sign the exact canonical bytes delivered to a subscriber."""

    body = canonical_json(event.model_dump(mode="json"))
    digest = hashlib.sha256(body).hexdigest()
    timestamp_value = timestamp.isoformat()
    signed = f"{timestamp_value}.{event.id}.{digest}.".encode() + body
    signature = hmac.new(secret, signed, hashlib.sha256).hexdigest()
    return SignedDelivery(
        body=body,
        event_id=str(event.id),
        timestamp=timestamp_value,
        content_digest=f"sha256={digest}",
        signature=f"sha256={signature}",
    )
