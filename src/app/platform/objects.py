"""Opaque-object client for the shared Aurinara platform gateway."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import httpx

from app.common.problems import ProblemException
from app.config import Settings, get_settings
from app.platform.authorization import PlatformAuthorizationClient, get_platform_authorization


@dataclass(frozen=True, slots=True)
class PlatformObjectRegistration:
    object_id: UUID
    reference_id: UUID
    external_reference: str


@dataclass(frozen=True, slots=True)
class PlatformRepositoryVersion:
    """Authorized immutable Repository version metadata used for product binding."""

    id: UUID
    study_id: UUID
    object_id: UUID
    filename: str
    media_type: str
    sha256: str
    size: int
    classification: str
    source_status: str


class PlatformObjectClient:
    """Request short-lived object URLs without exposing bucket credentials."""

    def __init__(
        self,
        settings: Settings,
        authorization: PlatformAuthorizationClient,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.mode = settings.platform_authorization_mode
        self._base_url = (settings.platform_control_plane_url or "").rstrip("/")
        self._authorization = authorization
        self._client = httpx.Client(
            transport=transport,
            timeout=settings.platform_authorization_timeout_seconds,
        )

    def authorize_download(self, object_id: UUID) -> str:
        """Return a gateway-authorized URL for an opaque catalog object."""

        if not self._base_url:
            raise self._unavailable()
        try:
            response = self._client.post(
                f"{self._base_url}/v1/objects/{object_id}/download",
                headers={"Authorization": f"Bearer {self._authorization.service_token()}"},
                json={"authorization_action": "aurinara.artifacts.read"},
            )
            response.raise_for_status()
            url = str(response.json()["url"])
            if not url:
                raise ValueError("empty object URL")
            return url
        except ProblemException:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise self._unavailable() from error

    def register_file(
        self,
        *,
        study_id: UUID,
        path: Path,
        sha256: str,
        size: int,
        media_type: str,
        classification: str,
        external_reference: str,
        repository: dict[str, object] | None = None,
    ) -> PlatformObjectRegistration:
        """Upload one verified file and register its product reference."""

        if not self._base_url:
            raise self._unavailable()
        headers = {"Authorization": f"Bearer {self._authorization.service_token()}"}
        try:
            created = self._client.post(
                f"{self._base_url}/v1/objects/upload-sessions",
                headers=headers,
                json={
                    "study_id": str(study_id),
                    "owner_product": "aurinara",
                    "authorization_action": "aurinara.artifacts.write",
                    "classification": classification,
                    "media_type": media_type,
                    "expected_sha256": sha256,
                    "expected_size_bytes": size,
                    "part_count": 1,
                },
            )
            if created.status_code == 409:
                object_id = UUID(created.json()["error"]["details"]["object_id"])
            else:
                created.raise_for_status()
                payload = created.json()
                object_id = UUID(payload["object_id"])
                with path.open("rb") as body:
                    uploaded = self._client.put(
                        str(payload["parts"][0]["url"]),
                        content=body,
                        headers={"Content-Type": media_type},
                    )
                uploaded.raise_for_status()
                etag = uploaded.headers.get("ETag")
                if not etag:
                    raise ValueError("upload response did not include an ETag")
                finalized = self._client.post(
                    f"{self._base_url}/v1/objects/{object_id}/finalize",
                    headers=headers,
                    json={"parts": [{"part_number": 1, "etag": etag}]},
                )
                finalized.raise_for_status()
            referenced = self._client.post(
                f"{self._base_url}/v1/objects/{object_id}/references",
                headers=headers,
                json={
                    "product": "aurinara",
                    "authorization_action": "aurinara.artifacts.write",
                    "external_reference": external_reference,
                    "idempotency_key": external_reference,
                    **({"repository": repository} if repository is not None else {}),
                },
            )
            referenced.raise_for_status()
            return PlatformObjectRegistration(
                object_id=object_id,
                reference_id=UUID(referenced.json()["id"]),
                external_reference=external_reference,
            )
        except ProblemException:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise self._unavailable() from error

    def publish_repository_metadata(
        self,
        registration: PlatformObjectRegistration,
        repository: dict[str, object],
    ) -> None:
        """Atomically attach exact Repository metadata to an existing object reference."""

        if not self._base_url:
            raise self._unavailable()
        try:
            response = self._client.post(
                f"{self._base_url}/v1/objects/{registration.object_id}/references",
                headers={"Authorization": f"Bearer {self._authorization.service_token()}"},
                json={
                    "product": "aurinara",
                    "authorization_action": "aurinara.artifacts.write",
                    "external_reference": registration.external_reference,
                    "idempotency_key": registration.external_reference,
                    "repository": repository,
                },
            )
            response.raise_for_status()
        except ProblemException:
            raise
        except httpx.HTTPError as error:
            raise self._unavailable() from error

    def publish_existing_repository_reference(
        self,
        reference_id: UUID,
        repository: dict[str, object],
    ) -> None:
        """Publish reviewed metadata against an exact existing Platform reference."""

        if not self._base_url:
            raise self._unavailable()
        try:
            response = self._client.post(
                f"{self._base_url}/v1/object-references/{reference_id}/repository",
                headers={"Authorization": f"Bearer {self._authorization.service_token()}"},
                json=repository,
            )
            response.raise_for_status()
        except ProblemException:
            raise
        except httpx.HTTPError as error:
            raise self._unavailable() from error

    def resolve_repository_version(
        self, version_id: UUID, user_access_token: str
    ) -> PlatformRepositoryVersion:
        """Resolve a version through the signed-in user's Platform authorization."""

        if not self._base_url:
            raise self._unavailable()
        try:
            response = self._client.get(
                f"{self._base_url}/v1/repository/versions/{version_id}",
                headers={"Authorization": f"Bearer {user_access_token}"},
            )
            response.raise_for_status()
            payload = response.json()
            return PlatformRepositoryVersion(
                id=UUID(payload["id"]),
                study_id=UUID(payload["study_id"]),
                object_id=UUID(payload["object_id"]),
                filename=str(payload["filename"]),
                media_type=str(payload["media_type"]),
                sha256=str(payload["sha256"]),
                size=int(payload["size_bytes"]),
                classification=str(payload["classification"]),
                source_status=str(payload["source_status"]),
            )
        except ProblemException:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise self._unavailable() from error

    def bind_repository_object(
        self, *, object_id: UUID, external_reference: str
    ) -> PlatformObjectRegistration:
        """Create the Aurinara reference for an explicitly selected Repository version."""

        if not self._base_url:
            raise self._unavailable()
        try:
            response = self._client.post(
                f"{self._base_url}/v1/objects/{object_id}/references",
                headers={"Authorization": f"Bearer {self._authorization.service_token()}"},
                json={
                    "product": "aurinara",
                    "authorization_action": "aurinara.artifacts.write",
                    "external_reference": external_reference,
                    "idempotency_key": external_reference,
                },
            )
            response.raise_for_status()
            return PlatformObjectRegistration(
                object_id=object_id,
                reference_id=UUID(response.json()["id"]),
                external_reference=external_reference,
            )
        except ProblemException:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise self._unavailable() from error

    def release_reference(self, reference_id: UUID) -> None:
        """Release an idempotent catalog reference after product retention permits it."""

        if not self._base_url:
            raise self._unavailable()
        try:
            response = self._client.delete(
                f"{self._base_url}/v1/object-references/{reference_id}",
                headers={"Authorization": f"Bearer {self._authorization.service_token()}"},
            )
            response.raise_for_status()
        except ProblemException:
            raise
        except httpx.HTTPError as error:
            raise self._unavailable() from error

    @staticmethod
    def _unavailable() -> ProblemException:
        return ProblemException(
            status_code=503,
            code="object_gateway_unavailable",
            title="Object gateway unavailable",
            detail="The object gateway is temporarily unavailable.",
        )


@lru_cache(maxsize=1)
def get_platform_objects() -> PlatformObjectClient:
    settings = get_settings()
    return PlatformObjectClient(settings, get_platform_authorization())
