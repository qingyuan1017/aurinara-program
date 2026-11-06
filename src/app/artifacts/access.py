"""Mode-specific access to immutable artifact bytes."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import BinaryIO, cast
from uuid import UUID

from app.artifacts.storage import ObjectStorage
from app.common.problems import ProblemException
from app.platform.objects import get_platform_objects


@contextmanager
def open_stored_object(
    storage: ObjectStorage,
    *,
    object_key: str | None,
    platform_object_id: UUID | None,
) -> Iterator[BinaryIO]:
    """Open bytes from the one storage provider selected for this deployment."""

    gateway = get_platform_objects()
    if gateway.mode == "disabled":
        if object_key is None:
            raise ProblemException(
                status_code=503,
                code="local_object_unavailable",
                title="Local object unavailable",
                detail="The record has no application-owned object reference.",
            )
        with storage.open(object_key) as body:
            yield body
        return

    if platform_object_id is None:
        raise ProblemException(
            status_code=503,
            code="platform_object_unavailable",
            title="Platform object unavailable",
            detail="The record has no Platform object reference.",
        )
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as temporary:
        body = cast(BinaryIO, temporary)
        gateway.download_to(platform_object_id, body)
        body.seek(0)
        yield body
