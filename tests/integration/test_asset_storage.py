"""MinIO-backed storage integration tests for the verified pinned-asset reader/publisher."""

import os
from pathlib import Path

import pytest

from app.artifacts.storage import S3ObjectStorage, checksum_object_key
from app.common.asset_content import (
    AssetContentError,
    publish_verified_asset,
    read_verified_asset_bytes,
)
from app.common.canonical import sha256_hex
from app.config import Settings

pytestmark = pytest.mark.skipif(
    os.getenv("AURINARA_INTEGRATION") != "1",
    reason="set AURINARA_INTEGRATION=1 with the Compose MinIO service running",
)


@pytest.fixture
def storage() -> S3ObjectStorage:
    settings = Settings(_env_file=None, app_env="test")
    adapter = S3ObjectStorage(settings)
    adapter.check()
    return adapter


def test_publish_then_verified_read_round_trips(storage: S3ObjectStorage, tmp_path: Path) -> None:
    data = b'{"round":"trip"}'
    checksum = sha256_hex(data)
    local = tmp_path / "asset.json"
    local.write_bytes(data)

    key = publish_verified_asset(storage, local, checksum, "application/json")
    assert key == checksum_object_key(checksum)
    assert storage.exists(key) is True
    assert read_verified_asset_bytes(storage, checksum) == data


def test_missing_object_without_fallback_is_object_missing(storage: S3ObjectStorage) -> None:
    checksum = sha256_hex(os.urandom(32))
    assert storage.exists(checksum_object_key(checksum)) is False

    with pytest.raises(AssetContentError) as error:
        read_verified_asset_bytes(storage, checksum)

    assert error.value.reason == "object_missing"


def test_missing_object_served_from_local_fallback(
    storage: S3ObjectStorage, tmp_path: Path
) -> None:
    data = b'{"from":"disk"}' + os.urandom(8)
    checksum = sha256_hex(data)
    local = tmp_path / "fallback.json"
    local.write_bytes(data)

    served = read_verified_asset_bytes(storage, checksum, local_fallback=lambda: local)
    assert served == data


def test_tampered_object_fails_integrity(storage: S3ObjectStorage, tmp_path: Path) -> None:
    expected = b'{"expected":true}' + os.urandom(8)
    checksum = sha256_hex(expected)
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_bytes(b"corrupt-bytes")
    # Upload corrupt bytes directly to the key the reader will fetch.
    storage.put_file(checksum_object_key(checksum), corrupt, "application/json")

    with pytest.raises(AssetContentError) as error:
        read_verified_asset_bytes(storage, checksum)

    assert error.value.reason == "checksum_mismatch"


def test_reupload_identical_bytes_is_idempotent(storage: S3ObjectStorage, tmp_path: Path) -> None:
    data = b'{"idempotent":true}' + os.urandom(8)
    checksum = sha256_hex(data)
    local = tmp_path / "asset.json"
    local.write_bytes(data)

    first = publish_verified_asset(storage, local, checksum, "application/json")
    second = publish_verified_asset(storage, local, checksum, "application/json")
    assert first == second
    assert read_verified_asset_bytes(storage, checksum) == data
