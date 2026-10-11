from pathlib import Path
from uuid import uuid4

import httpx

from app.config import Settings
from app.platform.authorization import PlatformAuthorizationClient
from app.platform.objects import PlatformObjectClient


def test_object_download_returns_gateway_url_without_storage_key() -> None:
    object_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/objects/{object_id}/download"
        assert request.headers["Authorization"] == "Bearer service-token"
        return httpx.Response(
            200,
            json={
                "url": "https://objects.test/signed",
                "expires_at": "2026-10-10T00:00:00Z",
            },
        )

    settings = Settings(
        _env_file=None,
        app_env="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    authorization = PlatformAuthorizationClient(settings)
    authorization._token = ("service-token", float("inf"))
    client = PlatformObjectClient(settings, authorization, httpx.MockTransport(handler))

    assert client.authorize_download(object_id) == "https://objects.test/signed"


def test_register_file_uses_presigned_upload_and_opaque_reference(tmp_path: Path) -> None:
    object_id = uuid4()
    reference_id = uuid4()
    path = tmp_path / "source.csv"
    path.write_bytes(b"verified")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/v1/objects/upload-sessions":
            return httpx.Response(
                201,
                json={
                    "object_id": str(object_id),
                    "upload_id": "upload-1",
                    "expires_at": "2026-10-10T00:00:00Z",
                    "parts": [{"part_number": 1, "url": "https://upload.test/part"}],
                },
            )
        if request.url.host == "upload.test":
            return httpx.Response(200, headers={"ETag": '"etag"'})
        if request.url.path.endswith("/finalize"):
            return httpx.Response(200, json={})
        if request.url.path.endswith("/references"):
            return httpx.Response(201, json={"id": str(reference_id)})
        raise AssertionError(request.url)

    settings = Settings(
        _env_file=None,
        app_env="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    authorization = PlatformAuthorizationClient(settings)
    authorization._token = ("service-token", float("inf"))
    client = PlatformObjectClient(settings, authorization, httpx.MockTransport(handler))

    result = client.register_file(
        study_id=uuid4(),
        path=path,
        sha256="0" * 64,
        size=8,
        media_type="text/csv",
        classification="source-file",
        external_reference="source_file:1",
    )

    assert result.object_id == object_id
    assert result.reference_id == reference_id
    assert seen == [
        "/v1/objects/upload-sessions",
        "/part",
        f"/v1/objects/{object_id}/finalize",
        f"/v1/objects/{object_id}/references",
    ]
