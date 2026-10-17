"""Unit tests for the verified pinned-asset reader/publisher and storage boundary."""

import io
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.artifacts.storage import (
    ObjectNotFoundError,
    ObjectStorage,
    ObjectStorageError,
    S3ObjectStorage,
    checksum_object_key,
)
from app.common.asset_content import (
    AssetContentError,
    publish_verified_asset,
    read_verified_asset_bytes,
    read_verified_asset_json_object,
)
from app.common.canonical import sha256_hex
from app.config import Settings


class _FakeStorage(ObjectStorage):
    """Configurable in-memory storage for exercising the reader branches."""

    def __init__(
        self,
        *,
        objects: dict[str, bytes] | None = None,
        open_error: Exception | None = None,
        local_fallback_enabled: bool = False,
    ) -> None:
        self.objects = objects or {}
        self._open_error = open_error
        self.local_fallback_enabled = local_fallback_enabled
        self.put_calls: list[tuple[str, str]] = []

    def put_file(self, object_key: str, path: Path, media_type: str) -> None:
        self.put_calls.append((object_key, media_type))
        self.objects[object_key] = path.read_bytes()

    @contextmanager
    def open(self, object_key: str) -> Iterator[io.BytesIO]:
        if self._open_error is not None:
            raise self._open_error
        if object_key not in self.objects:
            raise ObjectNotFoundError("object not found")
        yield io.BytesIO(self.objects[object_key])

    def exists(self, object_key: str) -> bool:
        return object_key in self.objects

    def check(self) -> None:
        return None


def _store_object(storage: _FakeStorage, data: bytes) -> str:
    checksum = sha256_hex(data)
    storage.objects[checksum_object_key(checksum)] = data
    return checksum


def test_reader_returns_checksum_verified_object_bytes() -> None:
    storage = _FakeStorage()
    checksum = _store_object(storage, b'{"ok":true}')

    assert read_verified_asset_bytes(storage, checksum) == b'{"ok":true}'


def test_reader_rejects_corrupt_object_and_never_falls_back() -> None:
    data = b'{"ok":true}'
    checksum = sha256_hex(data)
    storage = _FakeStorage(objects={checksum_object_key(checksum): b"tampered"})
    fallback = MagicMock(return_value=Path("unused"))

    with pytest.raises(AssetContentError) as error:
        read_verified_asset_bytes(storage, checksum, local_fallback=fallback)

    assert error.value.reason == "checksum_mismatch"
    fallback.assert_not_called()


def test_reader_storage_error_never_falls_back() -> None:
    checksum = sha256_hex(b"content")
    storage = _FakeStorage(open_error=ObjectStorageError("boom"))
    fallback = MagicMock(return_value=Path("unused"))

    with pytest.raises(AssetContentError) as error:
        read_verified_asset_bytes(storage, checksum, local_fallback=fallback)

    assert error.value.reason == "storage_error"
    fallback.assert_not_called()


def test_reader_missing_object_without_fallback_is_object_missing() -> None:
    checksum = sha256_hex(b"content")
    storage = _FakeStorage()

    with pytest.raises(AssetContentError) as error:
        read_verified_asset_bytes(storage, checksum)

    assert error.value.reason == "object_missing"


def test_reader_falls_back_to_verified_local_file(tmp_path: Path) -> None:
    data = b'{"from":"disk"}'
    checksum = sha256_hex(data)
    local = tmp_path / "asset.json"
    local.write_bytes(data)
    storage = _FakeStorage(local_fallback_enabled=True)

    assert read_verified_asset_bytes(storage, checksum, local_fallback=lambda: local) == data


def test_reader_reverifies_fallback_bytes(tmp_path: Path) -> None:
    checksum = sha256_hex(b'{"expected":true}')
    local = tmp_path / "asset.json"
    local.write_bytes(b'{"tampered":true}')
    storage = _FakeStorage()

    with pytest.raises(AssetContentError) as error:
        read_verified_asset_bytes(storage, checksum, local_fallback=lambda: local)

    assert error.value.reason == "checksum_mismatch"


def test_json_object_reader_rejects_non_object() -> None:
    storage = _FakeStorage()
    checksum = _store_object(storage, b"[1,2,3]")

    with pytest.raises(AssetContentError) as error:
        read_verified_asset_json_object(storage, checksum)

    assert error.value.reason == "not_json_object"


def test_json_object_reader_returns_mapping() -> None:
    storage = _FakeStorage()
    checksum = _store_object(storage, b'{"a":1}')

    assert read_verified_asset_json_object(storage, checksum) == {"a": 1}


def test_publish_refuses_upload_on_local_mismatch(tmp_path: Path) -> None:
    local = tmp_path / "asset.json"
    local.write_bytes(b"actual-bytes")
    storage = _FakeStorage()

    with pytest.raises(AssetContentError) as error:
        publish_verified_asset(storage, local, sha256_hex(b"different"), "application/json")

    assert error.value.reason == "checksum_mismatch"
    assert storage.put_calls == []


def test_publish_uploads_to_checksum_key(tmp_path: Path) -> None:
    data = b"publishable"
    checksum = sha256_hex(data)
    local = tmp_path / "asset.json"
    local.write_bytes(data)
    storage = _FakeStorage()

    key = publish_verified_asset(storage, local, checksum, "application/json")

    assert key == checksum_object_key(checksum)
    assert storage.put_calls == [(key, "application/json")]


def _s3_storage() -> S3ObjectStorage:
    storage = S3ObjectStorage(Settings(_env_file=None))
    storage._client = MagicMock()  # type: ignore[attr-defined]
    return storage


def test_s3_storage_uses_default_credential_chain_when_static_keys_are_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    create_client = MagicMock(return_value=client)
    monkeypatch.setattr("app.artifacts.storage.boto3.client", create_client)
    settings = Settings(
        _env_file=None,
        object_store_endpoint=None,
        object_store_access_key="",
        object_store_secret_key="",
        object_store_path_style=False,
    )

    S3ObjectStorage(settings)

    options = create_client.call_args.kwargs
    assert "endpoint_url" not in options
    assert "aws_access_key_id" not in options
    assert "aws_secret_access_key" not in options


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "GetObject")


def test_s3_open_maps_missing_key_to_object_not_found() -> None:
    storage = _s3_storage()
    storage._client.get_object.side_effect = _client_error("NoSuchKey")  # type: ignore[attr-defined]

    with pytest.raises(ObjectNotFoundError), storage.open("sha256/aa/bb/x"):
        pass


def test_s3_open_maps_connectivity_error_to_storage_error() -> None:
    storage = _s3_storage()
    storage._client.get_object.side_effect = EndpointConnectionError(  # type: ignore[attr-defined]
        endpoint_url="http://localhost:9000"
    )

    with pytest.raises(ObjectStorageError) as error, storage.open("sha256/aa/bb/x"):
        pass

    assert not isinstance(error.value, ObjectNotFoundError)


def test_load_presentation_template_uses_local_fallback_when_enabled() -> None:
    from app.cdisc_registry import REPOSITORY_ROOT
    from app.documents.service import load_presentation_template

    relative = "templates/platform/document-layout-2.0.0.json"
    checksum = sha256_hex((REPOSITORY_ROOT / relative).read_bytes())
    # Object absent, but fallback enabled -> served and boundary-validated from disk.
    storage = _FakeStorage(local_fallback_enabled=True)
    ref = {
        "checksum": checksum,
        "asset_path": relative,
        "renderer_versions": ["document-1"],
    }

    template = load_presentation_template(storage, ref)
    assert template["renderer"] == "document-1"


def test_load_presentation_template_without_fallback_raises_object_missing() -> None:
    from app.cdisc_registry import REPOSITORY_ROOT
    from app.documents.service import load_presentation_template

    relative = "templates/platform/document-layout-2.0.0.json"
    checksum = sha256_hex((REPOSITORY_ROOT / relative).read_bytes())
    storage = _FakeStorage(local_fallback_enabled=False)
    ref = {
        "checksum": checksum,
        "asset_path": relative,
        "renderer_versions": ["document-1"],
    }

    with pytest.raises(AssetContentError) as error:
        load_presentation_template(storage, ref)

    assert error.value.reason == "object_missing"


def test_group_digest_skip_detection() -> None:
    from app.cdisc_registry import REPOSITORY_ROOT, _is_group_digest

    relative = "schemas/platform/dependency-selection-1.0.0.json"
    actual = sha256_hex((REPOSITORY_ROOT / relative).read_bytes())

    # A row whose stored checksum equals its own file sha256 owns a real file object.
    assert _is_group_digest(relative, actual, "schemas") is False
    # A row whose stored checksum is a synthetic digest (does not match the file) is skipped.
    assert _is_group_digest(relative, sha256_hex(b"synthetic-group-digest"), "schemas") is True


def test_s3_exists_true_false_and_error() -> None:
    storage = _s3_storage()
    storage._client.head_object.return_value = {}  # type: ignore[attr-defined]
    assert storage.exists("sha256/aa/bb/x") is True

    storage._client.head_object.side_effect = _client_error("404")  # type: ignore[attr-defined]
    assert storage.exists("sha256/aa/bb/x") is False

    storage._client.head_object.side_effect = _client_error("AccessDenied")  # type: ignore[attr-defined]
    with pytest.raises(ObjectStorageError):
        storage.exists("sha256/aa/bb/x")
