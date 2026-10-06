"""Verified read/publish primitives for checksum-addressed pinned asset content.

This is a technical primitive (no clinical logic). It reads bytes for a pinned
provider asset from checksum-addressed object storage, with an optional local-file
fallback for a missing object, and always re-verifies the fetched bytes against the
expected SHA-256 before returning. It also publishes a verified local file to its
immutable content-addressed key.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from app.artifacts.storage import (
    ObjectNotFoundError,
    ObjectStorage,
    ObjectStorageError,
    checksum_object_key,
)
from app.common.canonical import sha256_hex

AssetContentReason = Literal[
    "object_missing",
    "checksum_mismatch",
    "storage_error",
    "not_json_object",
]


class AssetContentError(RuntimeError):
    """Typed failure raised while reading or publishing pinned asset content."""

    def __init__(self, reason: AssetContentReason, *, checksum: str) -> None:
        super().__init__(reason)
        self.reason: AssetContentReason = reason
        self.checksum = checksum


def read_verified_asset_bytes(
    storage: ObjectStorage,
    expected_sha256: str,
    *,
    local_fallback: Callable[[], Path] | None = None,
) -> bytes:
    """Fetch and re-verify checksum-addressed bytes with an optional local fallback.

    Branch order is locked: object storage first; only a genuinely missing object
    may fall back to a local file; any other storage error never consults the
    fallback; fetched bytes are always re-hashed against ``expected_sha256``.
    """

    key = checksum_object_key(expected_sha256)
    try:
        with storage.open(key) as body:
            data = body.read()
    except ObjectNotFoundError:
        if local_fallback is None:
            raise AssetContentError("object_missing", checksum=expected_sha256) from None
        data = local_fallback().read_bytes()
    except ObjectStorageError as error:
        raise AssetContentError("storage_error", checksum=expected_sha256) from error
    if sha256_hex(data) != expected_sha256:
        raise AssetContentError("checksum_mismatch", checksum=expected_sha256)
    return data


def read_verified_asset_json_object(
    storage: ObjectStorage,
    expected_sha256: str,
    *,
    local_fallback: Callable[[], Path] | None = None,
) -> dict[str, object]:
    """Read verified bytes and parse them as a top-level JSON object."""

    data = read_verified_asset_bytes(storage, expected_sha256, local_fallback=local_fallback)
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise AssetContentError("not_json_object", checksum=expected_sha256)
    return value


def publish_verified_asset(
    storage: ObjectStorage,
    local_path: Path,
    expected_sha256: str,
    media_type: str,
) -> str:
    """Verify a local file and upload it to its immutable content-addressed key.

    Uploading identical content to a content-addressed key is an idempotent no-op.
    """

    if sha256_hex(local_path.read_bytes()) != expected_sha256:
        raise AssetContentError("checksum_mismatch", checksum=expected_sha256)
    key = checksum_object_key(expected_sha256)
    storage.put_file(key, local_path, media_type)
    return key
