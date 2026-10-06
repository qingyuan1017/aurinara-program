"""Contract tests for pinned catalog asset content routes and Decision 6 error codes.

The content routes keep their path, parameters, and ``response_model=dict[str, object]``
success shape; only the typed object-storage error codes are asserted here. The DB
session, principal, and object storage are injected via FastAPI dependency overrides so
no PostgreSQL/MinIO is required.
"""

import io
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_object_storage, get_session
from app.artifacts.storage import ObjectNotFoundError, ObjectStorage, checksum_object_key
from app.common.canonical import sha256_hex
from app.config import Settings
from app.main import create_app
from app.standards.models import StandardAsset
from app.terminology.models import TerminologyAsset

pytestmark = pytest.mark.anyio


def _standard_asset(checksum: str) -> StandardAsset:
    return StandardAsset(
        checksum=checksum,
        asset_path="schemas/platform/dependency-selection-1.0.0.json",
    )


def _terminology_asset(checksum: str) -> TerminologyAsset:
    return TerminologyAsset(
        checksum=checksum,
        asset_path="terminology/platform/issue-severity-1.0.0.json",
    )


class _StubSession:
    def __init__(self, asset: object | None) -> None:
        self._asset = asset

    def get(self, model: type, identifier: UUID) -> object | None:
        del model, identifier
        return self._asset


class _ContentStorage(ObjectStorage):
    def __init__(
        self, *, objects: dict[str, bytes] | None = None, local_fallback_enabled: bool = False
    ) -> None:
        self.objects = objects or {}
        self.local_fallback_enabled = local_fallback_enabled

    def put_file(self, object_key: str, path: Path, media_type: str) -> None:
        self.objects[object_key] = path.read_bytes()

    @contextmanager
    def open(self, object_key: str) -> Iterator[io.BytesIO]:
        if object_key not in self.objects:
            raise ObjectNotFoundError("object not found")
        yield io.BytesIO(self.objects[object_key])

    def exists(self, object_key: str) -> bool:
        return object_key in self.objects

    def check(self) -> None:
        return None


def _app(asset: object | None, storage: ObjectStorage):
    settings = Settings(_env_file=None, app_env="test", pinned_asset_local_fallback=False)
    application = create_app(settings=settings)
    application.dependency_overrides[get_session] = lambda: _StubSession(asset)
    application.dependency_overrides[get_object_storage] = lambda: storage
    application.dependency_overrides[get_principal] = lambda: Principal(
        subject="user-1", scopes=frozenset({"*"})
    )
    return application


async def _get(application, path: str) -> object:
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        return await client.get(path)


async def test_published_asset_returns_200_object() -> None:
    data = b'{"schema":"ok"}'
    checksum = sha256_hex(data)
    storage = _ContentStorage(objects={checksum_object_key(checksum): data})
    application = _app(_standard_asset(checksum), storage)

    response = await _get(application, f"/api/v1/standard-assets/{uuid4()}/content")

    assert response.status_code == 200
    assert response.json() == {"schema": "ok"}


async def test_unpublished_asset_returns_503_unpublished() -> None:
    checksum = sha256_hex(b"missing")
    storage = _ContentStorage(local_fallback_enabled=False)
    application = _app(_standard_asset(checksum), storage)

    response = await _get(application, f"/api/v1/standard-assets/{uuid4()}/content")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "asset_content_unpublished"


async def test_non_object_asset_returns_500_contract_violation() -> None:
    data = b"[1, 2, 3]"
    checksum = sha256_hex(data)
    storage = _ContentStorage(objects={checksum_object_key(checksum): data})
    application = _app(_terminology_asset(checksum), storage)

    response = await _get(application, f"/api/v1/terminology-assets/{uuid4()}/content")

    assert response.status_code == 500
    assert response.json()["code"] == "asset_content_contract_violation"


async def test_missing_asset_row_returns_404() -> None:
    storage = _ContentStorage()
    application = _app(None, storage)

    response = await _get(application, f"/api/v1/standard-assets/{uuid4()}/content")

    assert response.status_code == 404
    assert response.json()["code"] == "standard_asset_not_found"


async def test_content_routes_unchanged_response_model() -> None:
    application = create_app(settings=Settings(_env_file=None, app_env="test"))
    schema = application.openapi()
    for path in (
        "/api/v1/standard-assets/{asset_id}/content",
        "/api/v1/terminology-assets/{asset_id}/content",
    ):
        operation = schema["paths"][path]["get"]
        content = operation["responses"]["200"]["content"]["application/json"]["schema"]
        # response_model=dict[str, object] renders as a free-form object schema.
        assert content.get("type") == "object"
