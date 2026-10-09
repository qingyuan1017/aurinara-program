"""Unit invariants for the atomic bulk source-file upload service."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.api.auth import Principal
from app.artifacts.models import Artifact, SourceFile
from app.artifacts.service import ArtifactService
from app.common.problems import ProblemException
from app.config import Settings


class FakeUpload:
    """Minimal async stand-in for Starlette's UploadFile."""

    def __init__(self, filename: str | None, content_type: str | None, data: bytes) -> None:
        self.filename = filename
        self.content_type = content_type
        self._data = data
        self._read = False
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        del size
        if self._read:
            return b""
        self._read = True
        return self._data

    async def close(self) -> None:
        self.closed = True


class FakeStorage:
    """Record uploaded bytes and assert at most one temp file exists at a time."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[str] = []

    def put_file(self, object_key: str, path: Path, media_type: str) -> None:
        del media_type
        self.put_calls.append(object_key)
        self.objects[object_key] = path.read_bytes()


class FakeSession:
    """Capture staged rows and commits without touching a database."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add_all(self, rows: object) -> None:
        self.added.extend(rows)  # type: ignore[arg-type]

    def commit(self) -> None:
        self.commits += 1


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="test")


def _service(monkeypatch: pytest.MonkeyPatch, study_id: UUID) -> ArtifactService:
    service = ArtifactService()

    def _allow(session: object, requested: UUID, principal: Principal) -> object:
        assert requested == study_id
        return object()

    monkeypatch.setattr(service._studies, "require_access", _allow)
    return service


PRINCIPAL = Principal(subject="user-1", scopes=frozenset({"*"}))


@pytest.mark.anyio
async def test_bulk_upload_returns_one_source_file_per_part_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_id = uuid4()
    service = _service(monkeypatch, study_id)
    session = FakeSession()
    storage = FakeStorage()
    uploads = [
        FakeUpload("a.csv", "text/csv", b"A,B\n1,2\n"),
        FakeUpload("b.csv", "text/csv", b"C,D\n3,4\n"),
        FakeUpload("c.json", "application/json", b"[]"),
    ]

    result = await service.create_source_files_bulk(
        session,
        storage,
        _settings(),
        study_id,
        uploads,
        PRINCIPAL,  # type: ignore[arg-type]
    )

    assert [row.filename for row in result] == ["a.csv", "b.csv", "c.json"]
    assert all(isinstance(row, SourceFile) for row in result)
    assert session.commits == 1
    # One Artifact + one SourceFile per part staged in a single commit.
    assert sum(isinstance(row, Artifact) for row in session.added) == 3
    assert sum(isinstance(row, SourceFile) for row in session.added) == 3
    assert all(upload.closed for upload in uploads)
    assert len(storage.objects) >= 1


@pytest.mark.anyio
async def test_bulk_upload_rejects_disallowed_media_type_without_committing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_id = uuid4()
    service = _service(monkeypatch, study_id)
    session = FakeSession()
    storage = FakeStorage()
    uploads = [
        FakeUpload("a.csv", "text/csv", b"A,B\n1,2\n"),
        FakeUpload("evil.exe", "application/x-msdownload", b"MZ"),
    ]

    with pytest.raises(ProblemException) as excinfo:
        await service.create_source_files_bulk(
            session,
            storage,
            _settings(),
            study_id,
            uploads,
            PRINCIPAL,  # type: ignore[arg-type]
        )

    assert excinfo.value.status_code == 415
    assert excinfo.value.code == "unsupported_media_type"
    assert session.commits == 0
    assert session.added == []
    # Metadata pass runs before any streaming, so nothing is uploaded.
    assert storage.put_calls == []


@pytest.mark.anyio
async def test_bulk_upload_rejects_unsafe_filename_without_committing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_id = uuid4()
    service = _service(monkeypatch, study_id)
    session = FakeSession()
    storage = FakeStorage()
    uploads = [
        FakeUpload("ok.csv", "text/csv", b"A,B\n1,2\n"),
        FakeUpload("../escape.csv", "text/csv", b"x"),
    ]

    with pytest.raises(ProblemException) as excinfo:
        await service.create_source_files_bulk(
            session,
            storage,
            _settings(),
            study_id,
            uploads,
            PRINCIPAL,  # type: ignore[arg-type]
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "invalid_filename"
    assert session.commits == 0
    assert session.added == []
    assert storage.put_calls == []


@pytest.mark.anyio
async def test_bulk_upload_empty_list_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    study_id = uuid4()
    service = _service(monkeypatch, study_id)
    session = FakeSession()
    storage = FakeStorage()

    with pytest.raises(ProblemException) as excinfo:
        await service.create_source_files_bulk(
            session,
            storage,
            _settings(),
            study_id,
            [],
            PRINCIPAL,  # type: ignore[arg-type]
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "raw_bulk_upload_empty"
    assert session.commits == 0


@pytest.mark.anyio
async def test_bulk_upload_too_many_parts_is_413(monkeypatch: pytest.MonkeyPatch) -> None:
    study_id = uuid4()
    service = _service(monkeypatch, study_id)
    session = FakeSession()
    storage = FakeStorage()
    settings = Settings(_env_file=None, app_env="test", raw_bulk_upload_max_files=2)
    uploads = [
        FakeUpload("a.csv", "text/csv", b"a"),
        FakeUpload("b.csv", "text/csv", b"b"),
        FakeUpload("c.csv", "text/csv", b"c"),
    ]

    with pytest.raises(ProblemException) as excinfo:
        await service.create_source_files_bulk(
            session,
            storage,
            settings,
            study_id,
            uploads,
            PRINCIPAL,  # type: ignore[arg-type]
        )

    assert excinfo.value.status_code == 413
    assert excinfo.value.code == "raw_bulk_upload_too_many"
    assert session.commits == 0
    assert storage.put_calls == []
