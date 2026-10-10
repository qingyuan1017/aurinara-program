"""Service-backed integration tests for asynchronous bulk dataset import."""

import io
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.artifacts.storage import ObjectNotFoundError, ObjectStorage
from app.catalog_seed import seed
from app.database import create_database_engine, create_session_factory
from app.execution.jobs import JobService
from app.main import create_app
from tests.conftest import make_test_settings
from tests.integration.test_phase1_core import TestTokenVerifier
from workers.job_worker import _process_job

pytestmark = pytest.mark.skipif(
    os.getenv("AURINARA_INTEGRATION") != "1",
    reason="set AURINARA_INTEGRATION=1 with the Compose PostgreSQL service running",
)

_TRUNCATE = (
    "TRUNCATE raw_dataset_imports, raw_variables, raw_dataset_file_bindings, raw_datasets, "
    "raw_dependency_selections, raw_workbenches, reconciliation_runs, validation_runs, "
    "source_files, artifacts, jobs, idempotency_records, outbox_events, "
    "study_memberships, studies CASCADE"
)


class _SpyStorage(ObjectStorage):
    """In-memory store that fails if two streams are open at once."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.live = 0
        self.max_live = 0

    def put_file(self, object_key: str, path: Path, media_type: str) -> None:
        del media_type
        self.objects[object_key] = path.read_bytes()

    @contextmanager
    def open(self, object_key: str) -> Iterator[io.BytesIO]:
        if object_key not in self.objects:
            raise ObjectNotFoundError("object not found")
        self.live += 1
        self.max_live = max(self.max_live, self.live)
        try:
            if self.live > 1:
                raise AssertionError("more than one object stream open at once")
            yield io.BytesIO(self.objects[object_key])
        finally:
            self.live -= 1

    def exists(self, object_key: str) -> bool:
        return object_key in self.objects

    def check(self) -> None:
        return None


@pytest.fixture
async def bulk_client() -> AsyncIterator[AsyncClient]:
    settings = make_test_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    with engine.begin() as connection:
        connection.execute(text(_TRUNCATE))
    storage = _SpyStorage()
    with factory() as session:
        seed(session, storage)
    app = create_app(
        settings=settings,
        session_factory=factory,
        object_storage=storage,
        token_verifier=TestTokenVerifier(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    engine.dispose()


_HEADERS = {"Authorization": "Bearer test-token"}
_JSON = b'[{"SUBJID":"01","AGE":42},{"SUBJID":"02","AGE":38}]'


async def _study_and_raw(client: AsyncClient) -> tuple[str, str]:
    study = await client.post(
        "/api/v1/studies", headers=_HEADERS, json={"code": f"P3B-{uuid4().hex[:6]}", "name": "B"}
    )
    study_id = study.json()["id"]
    raw = await client.post(
        f"/api/v1/studies/{study_id}/raw",
        headers=_HEADERS,
        json={"code": "RAW", "name": "Raw"},
    )
    return study_id, raw.json()["id"]


async def _source(client: AsyncClient, study_id: str, name: str = "demog.json") -> str:
    source = await client.post(
        f"/api/v1/studies/{study_id}/source-files",
        headers=_HEADERS,
        files={"file": (name, _JSON, "application/json")},
    )
    assert source.status_code == 201, source.text
    return source.json()["id"]


def _run_next_job(client: AsyncClient) -> None:
    application = client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    with factory.begin() as session:
        job = JobService().claim(
            session,
            worker_id="bulk-worker",
            lease_seconds=60,
            job_types=("raw_dataset_import",),
        )
        assert job is not None
    _process_job(
        factory,
        application.state.module_registry,
        application.state.object_storage,
        job,
    )


def _count(client: AsyncClient, table: str) -> int:
    application = client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    with factory.begin() as session:
        return int(session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())  # noqa: S608


@pytest.mark.anyio
async def test_bulk_import_single_transaction_commit(bulk_client: AsyncClient) -> None:
    client = bulk_client
    study_id, raw_id = await _study_and_raw(client)
    source_id = await _source(client, study_id)

    before_datasets = _count(client, "raw_datasets")
    before_bindings = _count(client, "raw_dataset_file_bindings")

    created = await client.post(
        f"/api/v1/raw/{raw_id}/datasets/import",
        headers={**_HEADERS, "Idempotency-Key": "bulk-ok-1"},
        json={
            "entries": [
                {"code": "DM", "label": "Demographics", "source_file_id": source_id},
                {"code": "AE", "label": "Adverse Events", "source_file_id": source_id},
            ]
        },
    )
    assert created.status_code == 202, created.text
    assert created.json()["status"] == "queued"
    assert created.headers["location"] == f"/api/v1/raw-dataset-imports/{created.json()['id']}"

    _run_next_job(client)

    status = await client.get(
        f"/api/v1/raw-dataset-imports/{created.json()['id']}", headers=_HEADERS
    )
    body = status.json()
    assert body["status"] == "succeeded", body
    assert len(body["result_dataset_ids"]) == 2
    assert body["files_inspected"] == 1  # one distinct shared source
    assert body["issues"] == []
    # Exactly two datasets and two bindings committed; one shared stream open at a time.
    assert _count(client, "raw_datasets") == before_datasets + 2
    assert _count(client, "raw_dataset_file_bindings") == before_bindings + 2
    assert client._transport.app.state.object_storage.max_live == 1  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_bulk_import_missing_key_is_400(bulk_client: AsyncClient) -> None:
    client = bulk_client
    study_id, raw_id = await _study_and_raw(client)
    source_id = await _source(client, study_id)
    response = await client.post(
        f"/api/v1/raw/{raw_id}/datasets/import",
        headers=_HEADERS,
        json={"entries": [{"code": "DM", "label": "x", "source_file_id": source_id}]},
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "idempotency_key_required"


@pytest.mark.anyio
async def test_bulk_import_idempotency_replay_and_reuse(bulk_client: AsyncClient) -> None:
    client = bulk_client
    study_id, raw_id = await _study_and_raw(client)
    source_id = await _source(client, study_id)
    body = {"entries": [{"code": "DM", "label": "x", "source_file_id": source_id}]}

    first = await client.post(
        f"/api/v1/raw/{raw_id}/datasets/import",
        headers={**_HEADERS, "Idempotency-Key": "reuse-1"},
        json=body,
    )
    assert first.status_code == 202, first.text
    replay = await client.post(
        f"/api/v1/raw/{raw_id}/datasets/import",
        headers={**_HEADERS, "Idempotency-Key": "reuse-1"},
        json=body,
    )
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == first.json()["id"]

    reuse = await client.post(
        f"/api/v1/raw/{raw_id}/datasets/import",
        headers={**_HEADERS, "Idempotency-Key": "reuse-1"},
        json={"entries": [{"code": "AE", "label": "x", "source_file_id": source_id}]},
    )
    assert reuse.status_code == 409, reuse.text
    assert reuse.json()["code"] == "idempotency_key_reused"


@pytest.mark.anyio
async def test_bulk_import_content_failure_not_requeued(bulk_client: AsyncClient) -> None:
    client = bulk_client
    _, raw_id = await _study_and_raw(client)
    # A source id that does not resolve -> deterministic content failure.
    created = await client.post(
        f"/api/v1/raw/{raw_id}/datasets/import",
        headers={**_HEADERS, "Idempotency-Key": "bad-source-1"},
        json={"entries": [{"code": "DM", "label": "x", "source_file_id": str(uuid4())}]},
    )
    assert created.status_code == 202, created.text
    import_id = created.json()["id"]

    _run_next_job(client)

    status = await client.get(f"/api/v1/raw-dataset-imports/{import_id}", headers=_HEADERS)
    body = status.json()
    assert body["status"] == "failed", body
    assert body["issues"][0]["code"] == "raw_source_file_invalid"
    assert body["result_dataset_ids"] == []
    assert _count(client, "raw_datasets") == 0

    # The backing job is terminal and was never requeued.
    application = client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    with factory.begin() as session:
        row = session.execute(
            text(
                "SELECT attempt_count, status FROM jobs "
                "WHERE job_type = 'raw_dataset_import' LIMIT 1"
            )
        ).one()
    assert row.attempt_count == 1
    assert row.status == "succeeded"


@pytest.mark.anyio
async def test_bulk_import_late_duplicate_rolls_back(bulk_client: AsyncClient) -> None:
    client = bulk_client
    study_id, raw_id = await _study_and_raw(client)
    source_id = await _source(client, study_id)

    created = await client.post(
        f"/api/v1/raw/{raw_id}/datasets/import",
        headers={**_HEADERS, "Idempotency-Key": "late-dup-1"},
        json={"entries": [{"code": "DUP", "label": "x", "source_file_id": source_id}]},
    )
    assert created.status_code == 202, created.text
    import_id = created.json()["id"]

    # Create the conflicting dataset AFTER enqueue but BEFORE the worker runs,
    # so the duplicate surfaces as a late IntegrityError inside T2.
    conflict = await client.post(
        f"/api/v1/raw/{raw_id}/datasets",
        headers=_HEADERS,
        json={"code": "DUP", "label": "existing", "source_file_id": source_id},
    )
    assert conflict.status_code == 201, conflict.text
    before = _count(client, "raw_datasets")

    _run_next_job(client)

    status = await client.get(f"/api/v1/raw-dataset-imports/{import_id}", headers=_HEADERS)
    body = status.json()
    assert body["status"] == "failed", body
    assert body["issues"][0]["code"] == "duplicate_raw_dataset_code"
    # No new rows beyond the pre-existing conflict dataset.
    assert _count(client, "raw_datasets") == before

    application = client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    with factory.begin() as session:
        row = session.execute(
            text(
                "SELECT attempt_count, status FROM jobs "
                "WHERE job_type = 'raw_dataset_import' LIMIT 1"
            )
        ).one()
    assert row.attempt_count == 1
    assert row.status == "succeeded"


@pytest.mark.anyio
async def test_cancel_queued_import_is_synchronous(bulk_client: AsyncClient) -> None:
    client = bulk_client
    study_id, raw_id = await _study_and_raw(client)
    source_id = await _source(client, study_id)
    created = await client.post(
        f"/api/v1/raw/{raw_id}/datasets/import",
        headers={**_HEADERS, "Idempotency-Key": "cancel-1"},
        json={"entries": [{"code": "DM", "label": "x", "source_file_id": source_id}]},
    )
    assert created.status_code == 202, created.text
    import_id = created.json()["id"]

    cancelled = await client.post(
        f"/api/v1/raw-dataset-imports/{import_id}/cancel", headers=_HEADERS
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    # The worker observes the cancellation and writes no datasets.
    _run_next_job(client)
    status = await client.get(f"/api/v1/raw-dataset-imports/{import_id}", headers=_HEADERS)
    assert status.json()["status"] == "cancelled"
    assert _count(client, "raw_datasets") == 0
