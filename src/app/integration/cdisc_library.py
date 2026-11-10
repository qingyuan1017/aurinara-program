"""Authenticated, read-only connector for on-demand CDISC Library selections."""

import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from app.config import Settings


@dataclass(frozen=True)
class CdiscLibraryResource:
    """One JSON representation fetched from a canonical Library href."""

    href: str
    title: str
    resource_type: str
    content: dict[str, object]


class CdiscLibraryUnavailable(RuntimeError):
    """Raised when the upstream Library cannot serve a bounded read."""


class CdiscLibraryConfigurationError(RuntimeError):
    """Raised when live Library access is not configured."""


class CdiscLibraryReader(Protocol):
    """Boundary used by the deterministic on-demand selection crawler."""

    def get(self, href: str) -> CdiscLibraryResource:
        """Fetch one canonical CDISC Library resource."""

    def canonical_href(self, href: str) -> str:
        """Normalize and constrain a linked resource reference."""


CdiscLibraryReaderFactory = Callable[
    [], AbstractContextManager[CdiscLibraryReader]
]


def create_cdisc_library_reader_factory(settings: Settings) -> CdiscLibraryReaderFactory:
    """Create request-safe live readers without exposing the configured API key."""

    def create() -> AbstractContextManager[CdiscLibraryReader]:
        secret = settings.cdisc_library_api_key
        api_key = secret.get_secret_value().strip() if secret is not None else ""
        if not api_key:
            raise CdiscLibraryConfigurationError(
                "CDISC Library live access is not configured"
            )
        return HttpCdiscLibraryClient(
            base_url=settings.cdisc_library_base_url,
            api_key=api_key,
            timeout_seconds=settings.cdisc_library_timeout_seconds,
        )

    return create


def iter_link_references(value: object) -> Iterator[tuple[str, str, str]]:
    """Yield every HAL-style href, title, and type in a Library representation."""

    if isinstance(value, dict):
        href = value.get("href")
        if isinstance(href, str):
            title = value.get("title")
            resource_type = value.get("type")
            yield (
                href,
                title if isinstance(title, str) else "",
                resource_type if isinstance(resource_type, str) else "",
            )
        for child in value.values():
            yield from iter_link_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_link_references(child)


class HttpCdiscLibraryClient:
    """Small bounded client that never persists or logs the supplied API key."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: int,
        max_response_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("CDISC Library base URL must be an absolute HTTPS URL")
        self.base_url = base_url.rstrip("/")
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.base_path = parsed.path.rstrip("/")
        self.max_response_bytes = max_response_bytes
        self.client = httpx.Client(
            headers={"Accept": "application/json", "api-key": api_key},
            timeout=timeout_seconds,
            follow_redirects=False,
        )

    def __enter__(self) -> "HttpCdiscLibraryClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.client.close()

    def canonical_href(self, href: str) -> str:
        """Accept only non-templated MDR resources on the configured origin."""

        if "{" in href or "}" in href:
            raise ValueError("templated CDISC Library href cannot be fetched")
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc:
            if f"{parsed.scheme}://{parsed.netloc}" != self.origin:
                raise ValueError("CDISC Library link changed origin")
            path = parsed.path
            if self.base_path and path.startswith(f"{self.base_path}/"):
                path = path[len(self.base_path) :]
        else:
            path = parsed.path
        if not path.startswith("/mdr/") and path != "/mdr/products":
            raise ValueError("CDISC Library link is outside the MDR resource tree")
        if parsed.query or parsed.fragment:
            raise ValueError("CDISC Library catalog links must not contain query or fragment data")
        return path

    def get(self, href: str) -> CdiscLibraryResource:
        """Fetch JSON with bounded retry behavior for rate and server failures."""

        canonical_href = self.canonical_href(href)
        response: httpx.Response | None = None
        for attempt in range(4):
            try:
                response = self.client.get(f"{self.base_url}{canonical_href}")
            except httpx.RequestError as error:
                if attempt == 3:
                    raise CdiscLibraryUnavailable(
                        "CDISC Library is unavailable; no registry content was changed"
                    ) from error
                time.sleep(2**attempt)
                continue
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
            if attempt < 3:
                time.sleep(2**attempt)
        assert response is not None
        if response.status_code in {429, 500, 502, 503, 504}:
            raise CdiscLibraryUnavailable(
                "CDISC Library is unavailable; no registry content was changed"
            )
        if response.is_error:
            raise CdiscLibraryUnavailable(
                f"CDISC Library rejected the live request with status {response.status_code}"
            )
        if len(response.content) > self.max_response_bytes:
            raise CdiscLibraryUnavailable(
                f"CDISC Library resource exceeds the live response limit: {canonical_href}"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise CdiscLibraryUnavailable(
                f"CDISC Library returned invalid JSON for: {canonical_href}"
            ) from error
        if not isinstance(payload, dict):
            raise CdiscLibraryUnavailable(
                f"CDISC Library resource is not a JSON object: {canonical_href}"
            )
        self_reference = payload.get("_links")
        title = ""
        resource_type = ""
        if isinstance(self_reference, dict):
            self_value = self_reference.get("self")
            if isinstance(self_value, dict):
                candidate_title = self_value.get("title")
                candidate_type = self_value.get("type")
                title = candidate_title if isinstance(candidate_title, str) else ""
                resource_type = candidate_type if isinstance(candidate_type, str) else ""
        return CdiscLibraryResource(
            href=canonical_href,
            title=title,
            resource_type=resource_type,
            content=payload,
        )
