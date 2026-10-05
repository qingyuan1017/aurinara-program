"""Checksum-addressed object storage boundary."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Protocol, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings


class ObjectStorageError(RuntimeError):
    """Raised when object storage cannot complete an operation."""


class ObjectStorage(Protocol):
    """Minimal immutable object-storage interface."""

    def put_file(self, object_key: str, path: Path, media_type: str) -> None:
        """Upload a verified local file to its immutable key."""

    @contextmanager
    def open(self, object_key: str) -> Iterator[BinaryIO]:
        """Yield a readable object body."""

    def check(self) -> None:
        """Verify bucket connectivity."""


class S3ObjectStorage:
    """S3-compatible object storage implementation."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.object_store_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.object_store_endpoint,
            aws_access_key_id=settings.object_store_access_key.get_secret_value(),
            aws_secret_access_key=settings.object_store_secret_key.get_secret_value(),
            region_name=settings.object_store_region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if settings.object_store_path_style else "auto"},
            ),
        )

    def put_file(self, object_key: str, path: Path, media_type: str) -> None:
        """Upload without making the object public."""

        try:
            self._client.upload_file(
                str(path), self._bucket, object_key, ExtraArgs={"ContentType": media_type}
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("object upload failed") from error

    @contextmanager
    def open(self, object_key: str) -> Iterator[BinaryIO]:
        """Stream an object body and close it deterministically."""

        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("object download failed") from error
        body = cast(BinaryIO, response["Body"])
        try:
            yield body
        finally:
            body.close()

    def check(self) -> None:
        """Verify that the configured private bucket is reachable."""

        try:
            self._client.head_bucket(Bucket=self._bucket)
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("object-store bucket is unavailable") from error


def checksum_object_key(sha256: str) -> str:
    """Derive an object key only from a verified checksum."""

    return f"sha256/{sha256[:2]}/{sha256[2:4]}/{sha256}"
