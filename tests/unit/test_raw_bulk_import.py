"""Unit invariants for asynchronous JSON-array bulk dataset import."""

from __future__ import annotations

import io
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.common.canonical import fingerprint
from app.config import Settings
from app.raw.contracts import (
    RawDatasetImportEntry,
    RawDatasetImportRequest,
    RawPhysicalColumn,
    RawPhysicalSnapshot,
)
from app.raw.models import RawDataset, RawDatasetFileBinding, RawDatasetImport, RawWorkbench
from app.raw.service import (
    ResolvedSource,
    apply_bulk_dataset_import,
    resolve_bulk_sources,
)

# --------------------------------------------------------------------------- #
# Request contract validation
# --------------------------------------------------------------------------- #


def test_request_rejects_empty_entries() -> None:
    with pytest.raises(ValueError):
        RawDatasetImportRequest(entries=())


def test_request_rejects_over_limit_entries() -> None:
    entries = tuple(
        RawDatasetImportEntry(code=f"D{i}", label="x", source_file_id=uuid4()) for i in range(501)
    )
    with pytest.raises(ValueError):
        RawDatasetImportRequest(entries=entries)


def test_request_rejects_intra_batch_duplicate_code() -> None:
    source = uuid4()
    with pytest.raises(ValueError):
        RawDatasetImportRequest(
            entries=(
                RawDatasetImportEntry(code="DM", label="a", source_file_id=source),
                RawDatasetImportEntry(code="DM", label="b", source_file_id=uuid4()),
            )
        )


def test_entry_rejects_bad_code_pattern() -> None:
    with pytest.raises(ValueError):
        RawDatasetImportEntry(code="1bad", label="x", source_file_id=uuid4())


def test_request_rejects_extra_field() -> None:
    with pytest.raises(ValueError):
        RawDatasetImportRequest.model_validate(
            {
                "entries": [{"code": "DM", "label": "x", "source_file_id": str(uuid4())}],
                "unexpected": True,
            }
        )


def test_fingerprint_is_stable_across_dumps() -> None:
    request = RawDatasetImportRequest(
        entries=(RawDatasetImportEntry(code="DM", label="Demographics", source_file_id=uuid4()),)
    )
    first = fingerprint(request.model_dump(mode="json"))
    second = fingerprint(request.model_dump(mode="json"))
    assert first == second
    assert len(first) == 64


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeSourceFile:
    def __init__(self, source_id: UUID, study_id: UUID, *, size: int = 10) -> None:
        self.id = source_id
        self.study_id = study_id
        self.artifact_id = uuid4()
        self.object_key = f"sha256/{source_id}"
        self.sha256 = "0" * 64
        self.filename = "data.csv"
        self.size = size


class FakeScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def __iter__(self) -> Any:
        return iter(self._rows)


class FakeSession:
    """In-memory session supporting the subset the service helpers use."""

    def __init__(self, sources: dict[UUID, FakeSourceFile] | None = None) -> None:
        self._sources = sources or {}
        self.added: list[Any] = []
        self.validation_runs: list[Any] = []

    def get(self, model: type, identifier: UUID) -> Any:
        from app.artifacts.models import SourceFile

        if model is SourceFile:
            return self._sources.get(identifier)
        return None

    def add(self, row: Any) -> None:
        if isinstance(row, RawDataset) and getattr(row, "id", None) is None:
            row.id = uuid4()
            row.revision = 1
        self.added.append(row)

    def flush(self) -> None:
        for row in self.added:
            if isinstance(row, RawDataset) and getattr(row, "id", None) is None:
                row.id = uuid4()
                row.revision = 1

    def scalars(self, _statement: Any) -> FakeScalarResult:
        return FakeScalarResult(self.validation_runs)


class FakeStaleness:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    def mark_raw_refresh(self, session: Any, raw_id: UUID) -> tuple[UUID, ...]:
        self.calls.append(raw_id)
        return ()


class FakeRegistry:
    def __init__(self) -> None:
        self.staleness = FakeStaleness()

    def require_handler(self, module_key: str, capability: Any) -> Any:
        assert module_key == "sdtm"
        return self.staleness


def _raw(study_id: UUID) -> RawWorkbench:
    raw = RawWorkbench(study_id=study_id, code="RAW", name="Raw")
    raw.id = uuid4()
    raw.revision = 3
    return raw


# --------------------------------------------------------------------------- #
# resolve_bulk_sources
# --------------------------------------------------------------------------- #


def test_resolve_bulk_sources_happy_path() -> None:
    study_id = uuid4()
    source = FakeSourceFile(uuid4(), study_id)
    session = FakeSession({source.id: source})
    entries = [RawDatasetImportEntry(code="DM", label="x", source_file_id=source.id)]

    resolved, issues = resolve_bulk_sources(
        session,  # type: ignore[arg-type]
        study_id=study_id,
        entries=entries,
    )

    assert issues == []
    assert resolved[0] is not None
    assert isinstance(resolved[0], ResolvedSource)
    assert resolved[0].id == source.id


def test_resolve_bulk_sources_missing_source_records_issue() -> None:
    study_id = uuid4()
    session = FakeSession({})
    entries = [RawDatasetImportEntry(code="DM", label="x", source_file_id=uuid4())]

    resolved, issues = resolve_bulk_sources(
        session,  # type: ignore[arg-type]
        study_id=study_id,
        entries=entries,
    )

    assert resolved == [None]
    assert len(issues) == 1
    assert issues[0].code == "raw_source_file_invalid"
    assert issues[0].dataset == "DM"


def test_resolve_bulk_sources_foreign_study_records_issue() -> None:
    study_id = uuid4()
    other_study = uuid4()
    source = FakeSourceFile(uuid4(), other_study)
    session = FakeSession({source.id: source})
    entries = [RawDatasetImportEntry(code="DM", label="x", source_file_id=source.id)]

    resolved, issues = resolve_bulk_sources(
        session,  # type: ignore[arg-type]
        study_id=study_id,
        entries=entries,
    )

    assert resolved == [None]
    assert issues[0].code == "raw_source_file_invalid"


# --------------------------------------------------------------------------- #
# apply_bulk_dataset_import
# --------------------------------------------------------------------------- #


def _snapshot() -> RawPhysicalSnapshot:
    return RawPhysicalSnapshot(
        columns=(RawPhysicalColumn(name="A", physical_type="string", ordinal=1),),
        row_count=1,
    )


def _resolved(study_id: UUID, source_id: UUID | None = None) -> ResolvedSource:
    sid = source_id or uuid4()
    return ResolvedSource(
        id=sid,
        artifact_id=uuid4(),
        object_key=f"sha256/{sid}",
        sha256="0" * 64,
        filename="data.csv",
        study_id=study_id,
        size=10,
    )


def test_apply_creates_one_dataset_per_entry_and_bumps_revision_once() -> None:
    study_id = uuid4()
    raw = _raw(study_id)
    session = FakeSession()
    registry = FakeRegistry()
    entries = [
        RawDatasetImportEntry(code="DM", label="a", source_file_id=uuid4()),
        RawDatasetImportEntry(code="AE", label="b", source_file_id=uuid4()),
    ]
    resolved = [_resolved(study_id), _resolved(study_id)]
    snapshots = [_snapshot(), _snapshot()]
    before = raw.revision

    created = apply_bulk_dataset_import(
        session,  # type: ignore[arg-type]
        registry,  # type: ignore[arg-type]
        raw=raw,
        entries=entries,
        resolved_sources=resolved,
        snapshots=snapshots,
        created_by="user-1",
    )

    assert len(created) == 2
    assert [d.code for d in created] == ["DM", "AE"]
    datasets = [r for r in session.added if isinstance(r, RawDataset)]
    bindings = [r for r in session.added if isinstance(r, RawDatasetFileBinding)]
    assert len(datasets) == 2
    assert len(bindings) == 2
    assert raw.revision == before + 1
    assert registry.staleness.calls == [raw.id]


def test_apply_two_entries_sharing_source_make_two_datasets_two_bindings() -> None:
    study_id = uuid4()
    raw = _raw(study_id)
    session = FakeSession()
    registry = FakeRegistry()
    shared = uuid4()
    entries = [
        RawDatasetImportEntry(code="DM", label="a", source_file_id=shared),
        RawDatasetImportEntry(code="AE", label="b", source_file_id=shared),
    ]
    shared_resolved = _resolved(study_id, shared)
    resolved = [shared_resolved, shared_resolved]
    snapshots = [_snapshot(), _snapshot()]

    created = apply_bulk_dataset_import(
        session,  # type: ignore[arg-type]
        registry,  # type: ignore[arg-type]
        raw=raw,
        entries=entries,
        resolved_sources=resolved,
        snapshots=snapshots,
        created_by="user-1",
    )

    datasets = [r for r in session.added if isinstance(r, RawDataset)]
    bindings = [r for r in session.added if isinstance(r, RawDatasetFileBinding)]
    assert len(created) == 2
    assert len(datasets) == 2
    assert len(bindings) == 2
    assert {b.source_file_id for b in bindings} == {shared}


def test_apply_rejects_misaligned_lists() -> None:
    study_id = uuid4()
    raw = _raw(study_id)
    session = FakeSession()
    registry = FakeRegistry()
    entries = [RawDatasetImportEntry(code="DM", label="a", source_file_id=uuid4())]

    with pytest.raises(RuntimeError):
        apply_bulk_dataset_import(
            session,  # type: ignore[arg-type]
            registry,  # type: ignore[arg-type]
            raw=raw,
            entries=entries,
            resolved_sources=[],
            snapshots=[],
            created_by="user-1",
        )


def test_apply_rejects_none_in_resolved() -> None:
    study_id = uuid4()
    raw = _raw(study_id)
    session = FakeSession()
    registry = FakeRegistry()
    entries = [RawDatasetImportEntry(code="DM", label="a", source_file_id=uuid4())]

    with pytest.raises(RuntimeError):
        apply_bulk_dataset_import(
            session,  # type: ignore[arg-type]
            registry,  # type: ignore[arg-type]
            raw=raw,
            entries=entries,
            resolved_sources=[None],
            snapshots=[None],
            created_by="user-1",
        )


# --------------------------------------------------------------------------- #
# Worker job-vs-business rule + terminal-state guard
# --------------------------------------------------------------------------- #


class FakeJob:
    def __init__(self, import_id: UUID, *, cancellation: datetime | None = None) -> None:
        self.id = uuid4()
        self.operation_id = import_id
        self.job_type = "raw_dataset_import"
        self.status = "running"
        self.payload: dict[str, object] = {"import_id": str(import_id)}
        self.attempt_count = 1
        self.max_attempts = 3
        self.cancellation_requested_at = cancellation
        self.completed_at: datetime | None = None
        self.lease_owner: str | None = "worker"
        self.lease_expires_at: datetime | None = None
        self.available_at = datetime.now()


class WorkerSession:
    """Session usable from the worker's factory.begin() blocks."""

    def __init__(self, store: dict[UUID, object]) -> None:
        self.store = store

    def get(self, model: type, identifier: UUID) -> Any:
        return self.store.get(identifier)

    def add(self, row: Any) -> None:
        if isinstance(row, RawDataset) and getattr(row, "id", None) is None:
            row.id = uuid4()
            row.revision = 1
        self.store[getattr(row, "id", None) or uuid4()] = row

    def flush(self) -> None:
        for row in list(self.store.values()):
            if isinstance(row, RawDataset) and getattr(row, "id", None) is None:
                row.id = uuid4()
                row.revision = 1

    def rollback(self) -> None:
        return None

    def scalars(self, _statement: Any) -> FakeScalarResult:
        return FakeScalarResult([])


class WorkerFactory:
    def __init__(self, store: dict[UUID, object]) -> None:
        self.store = store

    @contextmanager
    def begin(self) -> Any:
        yield WorkerSession(self.store)


def _worker_settings() -> Settings:
    return Settings(_env_file=None, app_env="test")


def test_worker_content_failure_completes_job_not_fail() -> None:
    from workers import job_worker

    study_id = uuid4()
    raw = _raw(study_id)
    record = RawDatasetImport(
        raw_id=raw.id,
        study_id=study_id,
        schema_version="1.0.0",
        entries=[{"code": "DM", "label": "x", "source_file_id": str(uuid4())}],
        input_fingerprint="0" * 64,
        entry_count=1,
        created_by="user-1",
    )
    record.id = uuid4()
    record.status = "queued"
    record.files_inspected = 0
    record.result_dataset_ids = []
    record.issues = []
    job = FakeJob(record.id)
    store: dict[UUID, object] = {job.id: job, record.id: record, raw.id: raw}
    factory = WorkerFactory(store)

    job_worker._handle_raw_dataset_import(
        factory,  # type: ignore[arg-type]
        FakeRegistry(),  # type: ignore[arg-type]
        _FakeStorageNeverOpened(),  # type: ignore[arg-type]
        _worker_settings(),
        job.id,
    )

    # The source id does not resolve -> business failure recorded, job completed.
    assert record.status == "failed"
    assert record.issues
    assert record.issues[0]["code"] == "raw_source_file_invalid"
    assert job.status == "succeeded"
    assert job.attempt_count == 1


def test_worker_terminal_state_guard_is_noop() -> None:
    from workers import job_worker

    study_id = uuid4()
    raw = _raw(study_id)
    record = RawDatasetImport(
        raw_id=raw.id,
        study_id=study_id,
        schema_version="1.0.0",
        entries=[],
        input_fingerprint="0" * 64,
        entry_count=0,
        created_by="user-1",
    )
    record.id = uuid4()
    record.status = "succeeded"
    record.result_dataset_ids = ["x"]
    record.issues = []
    job = FakeJob(record.id)
    store: dict[UUID, object] = {job.id: job, record.id: record, raw.id: raw}
    factory = WorkerFactory(store)

    job_worker._handle_raw_dataset_import(
        factory,  # type: ignore[arg-type]
        FakeRegistry(),  # type: ignore[arg-type]
        _FakeStorageNeverOpened(),  # type: ignore[arg-type]
        _worker_settings(),
        job.id,
    )

    assert record.status == "succeeded"
    assert record.result_dataset_ids == ["x"]
    assert job.status == "succeeded"


class _FakeStorageNeverOpened:
    def open(self, object_key: str) -> Any:  # pragma: no cover - must not be called
        raise AssertionError("storage must not be opened on a resolution failure")


class _CountingStream(io.BytesIO):
    def __init__(self, data: bytes, owner: _CountingStorage) -> None:
        super().__init__(data)
        self._owner = owner

    def __enter__(self) -> _CountingStream:
        self._owner.live += 1
        self._owner.max_live = max(self._owner.max_live, self._owner.live)
        return self

    def __exit__(self, *exc: object) -> None:
        self._owner.live -= 1


class _CountingStorage:
    """Count stream opens per object key and the max concurrently-open streams."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.opens: dict[str, int] = {}
        self.live = 0
        self.max_live = 0

    def open(self, object_key: str) -> _CountingStream:
        self.opens[object_key] = self.opens.get(object_key, 0) + 1
        return _CountingStream(self._data, self)


class _SharedSourceSession(WorkerSession):
    """Worker session that also resolves two entries to one shared SourceFile."""

    def __init__(self, store: dict[UUID, object], source: FakeSourceFile) -> None:
        super().__init__(store)
        self._source = source

    def get(self, model: type, identifier: UUID) -> Any:
        from app.artifacts.models import SourceFile

        if model is SourceFile:
            return self._source if identifier == self._source.id else None
        return super().get(model, identifier)


class _SharedSourceFactory:
    def __init__(self, store: dict[UUID, object], source: FakeSourceFile) -> None:
        self.store = store
        self.source = source

    @contextmanager
    def begin(self) -> Any:
        yield _SharedSourceSession(self.store, self.source)


def test_worker_inspects_shared_source_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from workers import job_worker

    study_id = uuid4()
    raw = _raw(study_id)
    source = FakeSourceFile(uuid4(), study_id)
    # Make the stored checksum match the inspected bytes so inspection proceeds.
    import hashlib

    data = b"A,B\n1,2\n"
    source.sha256 = hashlib.sha256(data).hexdigest()
    record = RawDatasetImport(
        raw_id=raw.id,
        study_id=study_id,
        schema_version="1.0.0",
        entries=[
            {"code": "DM", "label": "a", "source_file_id": str(source.id)},
            {"code": "AE", "label": "b", "source_file_id": str(source.id)},
        ],
        input_fingerprint="0" * 64,
        entry_count=2,
        created_by="user-1",
    )
    record.id = uuid4()
    record.status = "queued"
    record.files_inspected = 0
    record.result_dataset_ids = []
    record.issues = []
    job = FakeJob(record.id)
    store: dict[UUID, object] = {job.id: job, record.id: record, raw.id: raw}
    factory = _SharedSourceFactory(store, source)
    storage = _CountingStorage(data)

    job_worker._handle_raw_dataset_import(
        factory,  # type: ignore[arg-type]
        FakeRegistry(),  # type: ignore[arg-type]
        storage,  # type: ignore[arg-type]
        _worker_settings(),
        job.id,
    )

    assert record.status == "succeeded"
    # Two reads happen for the single file (checksum pass + inspect pass), but
    # the shared source is handled once across the two entries, so no third open.
    assert storage.opens[source.object_key] == 2
    assert storage.max_live == 1
    assert record.files_inspected == 1
    assert len(record.result_dataset_ids) == 2


# --------------------------------------------------------------------------- #
# Cancel handler
# --------------------------------------------------------------------------- #


class CancelSession:
    def __init__(self, record: RawDatasetImport, job: FakeJob) -> None:
        self._record = record
        self._job = job
        self.commits = 0

    def get(self, model: type, identifier: UUID) -> Any:
        if model is RawDatasetImport:
            return self._record if identifier == self._record.id else None
        return None

    def scalar(self, _statement: Any) -> Any:
        return self._job

    def commit(self) -> None:
        self.commits += 1


def test_cancel_handler_transitions_queued_to_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.auth import Principal
    from app.raw import routes

    study_id = uuid4()
    record = RawDatasetImport(
        raw_id=uuid4(),
        study_id=study_id,
        schema_version="1.0.0",
        entries=[],
        input_fingerprint="0" * 64,
        entry_count=0,
        created_by="user-1",
    )
    record.id = uuid4()
    record.status = "queued"
    record.files_inspected = 0
    record.result_dataset_ids = []
    record.issues = []
    record.created_at = datetime.now()
    job = FakeJob(record.id)
    session = CancelSession(record, job)

    monkeypatch.setattr(routes.studies, "require_access", lambda s, sid, p: object())
    principal = Principal(subject="user-1", scopes=frozenset({"*"}))

    result = routes.cancel_dataset_import(
        record.id,
        session,  # type: ignore[arg-type]
        principal,
    )

    assert result.status == "cancelled"
    assert record.status == "cancelled"
    assert record.completed_at is not None
    assert job.cancellation_requested_at is not None
    assert session.commits == 1


def test_cancel_handler_rejects_terminal_import(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.auth import Principal
    from app.common.problems import ProblemException
    from app.raw import routes

    study_id = uuid4()
    record = RawDatasetImport(
        raw_id=uuid4(),
        study_id=study_id,
        schema_version="1.0.0",
        entries=[],
        input_fingerprint="0" * 64,
        entry_count=0,
        created_by="user-1",
    )
    record.id = uuid4()
    record.status = "succeeded"
    record.files_inspected = 0
    record.result_dataset_ids = []
    record.issues = []
    job = FakeJob(record.id)
    session = CancelSession(record, job)

    monkeypatch.setattr(routes.studies, "require_access", lambda s, sid, p: object())
    principal = Principal(subject="user-1", scopes=frozenset({"*"}))

    with pytest.raises(ProblemException) as excinfo:
        routes.cancel_dataset_import(
            record.id,
            session,  # type: ignore[arg-type]
            principal,
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "invalid_lifecycle_transition"
