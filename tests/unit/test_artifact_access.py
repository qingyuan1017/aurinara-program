"""Storage reads never cross the deployment's selected provider boundary."""

from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

import pytest

from app.artifacts import access
from app.common.problems import ProblemException


class MemoryStorage:
    local_fallback_enabled = False

    def __init__(self) -> None:
        self.opened: list[str] = []

    def put_file(self, object_key: str, path: Path, media_type: str) -> None:
        raise AssertionError("not used")

    @contextmanager
    def open(self, object_key: str) -> Iterator[BinaryIO]:
        self.opened.append(object_key)
        yield BytesIO(b"local")

    def exists(self, object_key: str) -> bool:
        return False

    def check(self) -> None:
        return None


class MemoryGateway:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.downloaded: list[UUID] = []

    def download_to(self, object_id: UUID, target: BinaryIO) -> None:
        self.downloaded.append(object_id)
        target.write(b"platform")


def test_disabled_mode_reads_only_application_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = MemoryStorage()
    gateway = MemoryGateway("disabled")
    monkeypatch.setattr(access, "get_platform_objects", lambda: gateway)

    with access.open_stored_object(
        storage, object_key="sha256/local", platform_object_id=uuid4()
    ) as body:
        assert body.read() == b"local"

    assert storage.opened == ["sha256/local"]
    assert gateway.downloaded == []


def test_disabled_mode_does_not_fall_back_to_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = MemoryGateway("disabled")
    monkeypatch.setattr(access, "get_platform_objects", lambda: gateway)

    with (
        pytest.raises(ProblemException, match="application-owned object reference") as error,
        access.open_stored_object(
            MemoryStorage(), object_key=None, platform_object_id=uuid4()
        ),
    ):
        pass

    assert error.value.code == "local_object_unavailable"
    assert gateway.downloaded == []


def test_enforced_mode_reads_only_platform_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = MemoryStorage()
    gateway = MemoryGateway("enforced")
    object_id = uuid4()
    monkeypatch.setattr(access, "get_platform_objects", lambda: gateway)

    with access.open_stored_object(
        storage, object_key="sha256/local", platform_object_id=object_id
    ) as body:
        assert body.read() == b"platform"

    assert storage.opened == []
    assert gateway.downloaded == [object_id]


def test_enforced_mode_does_not_fall_back_to_application_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryStorage()
    gateway = MemoryGateway("enforced")
    monkeypatch.setattr(access, "get_platform_objects", lambda: gateway)

    with (
        pytest.raises(ProblemException, match="Platform object reference") as error,
        access.open_stored_object(
            storage, object_key="sha256/local", platform_object_id=None
        ),
    ):
        pass

    assert error.value.code == "platform_object_unavailable"
    assert storage.opened == []
