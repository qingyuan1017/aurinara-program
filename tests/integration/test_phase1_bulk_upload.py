"""PostgreSQL + object-store integration for atomic bulk source-file upload."""

import hashlib
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.catalog_seed import seed
from app.config import Settings
from app.database import create_database_engine, create_session_factory
from app.main import create_app
from tests.conftest import make_test_settings
from tests.integration.test_phase1_core import MemoryStorage, TestTokenVerifier

pytestmark = pytest.mark.skipif(
    os.getenv("AURINARA_INTEGRATION") != "1",
    reason="set AURINARA_INTEGRATION=1 with the Compose PostgreSQL service running",
)


class TempSpyStorage(MemoryStorage):
    """MemoryStorage that records how many temp files exist at each put_file call.

    Recording is scoped to a single operation: call :meth:`begin_spy` immediately
    before the bulk upload so unrelated staging (catalog seeding, manifest builds)
    is not counted.
    """

    def __init__(self) -> None:
        super().__init__()
        self.observed_concurrent: list[int] = []
        self.staged_paths: list[Path] = []
        self._spying = False

    def begin_spy(self) -> None:
        self._spying = True
        self.observed_concurrent = []
        self.staged_paths = []

    def put_file(self, object_key: str, path: Path, media_type: str) -> None:
        if self._spying:
            self.staged_paths.append(path)
            live = sum(1 for candidate in self.staged_paths if candidate.exists())
            self.observed_concurrent.append(live)
        super().put_file(object_key, path, media_type)


@pytest.fixture
def integration_settings() -> Settings:
    # A small byte cap keeps the oversize-rejection test cheap and deterministic.
    return make_test_settings(source_file_max_bytes=1024)


@pytest.fixture
async def bulk_client(
    integration_settings: Settings,
) -> AsyncIterator[tuple[AsyncClient, TempSpyStorage]]:
    engine = create_database_engine(integration_settings)
    factory = create_session_factory(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE integration_delivery_attempts, integration_subscriptions, "
                "integration_secret_versions, external_identifiers, integrations, "
                "reconciliation_runs, validation_runs, source_files, artifacts, jobs, "
                "outbox_events, study_memberships, studies CASCADE"
            )
        )
    storage = TempSpyStorage()
    with factory() as session:
        seed(session, storage)
    app = create_app(
        settings=integration_settings,
        session_factory=factory,
        object_storage=storage,
        token_verifier=TestTokenVerifier(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, storage
    engine.dispose()


async def _create_study(client: AsyncClient, headers: dict[str, str], code: str) -> str:
    created = await client.post(
        "/api/v1/studies", headers=headers, json={"code": code, "name": "Bulk Upload Study"}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


@pytest.mark.anyio
async def test_bulk_upload_creates_distinct_source_files_with_checksums(
    bulk_client: tuple[AsyncClient, TempSpyStorage],
) -> None:
    client, storage = bulk_client
    headers = {"Authorization": "Bearer test-token"}
    study_id = await _create_study(client, headers, "SYN-BULK")

    payloads = [b"USUBJID,AGE\n01,42\n", b"USUBJID,SEX\n01,F\n", b'{"rows": []}']
    storage.begin_spy()
    response = await client.post(
        f"/api/v1/studies/{study_id}/source-files:bulk",
        headers=headers,
        files=[
            ("files", ("dm.csv", payloads[0], "text/csv")),
            ("files", ("sex.csv", payloads[1], "text/csv")),
            ("files", ("empty.json", payloads[2], "application/json")),
        ],
    )
    assert response.status_code == 201, response.text
    items = response.json()["items"]
    assert [item["filename"] for item in items] == ["dm.csv", "sex.csv", "empty.json"]
    for item, payload in zip(items, payloads, strict=True):
        assert item["sha256"] == hashlib.sha256(payload).hexdigest()
        assert item["size"] == len(payload)
        assert "object_key" not in item
    # Distinct SourceFile rows (distinct IDs) even where bytes differ.
    assert len({item["id"] for item in items}) == 3
    # At most one temp file existed at any put_file call during the upload pass.
    assert storage.observed_concurrent
    assert max(storage.observed_concurrent) == 1


@pytest.mark.anyio
async def test_bulk_upload_oversize_file_rejects_whole_batch(
    bulk_client: tuple[AsyncClient, TempSpyStorage],
) -> None:
    client, storage = bulk_client
    headers = {"Authorization": "Bearer test-token"}
    study_id = await _create_study(client, headers, "SYN-BULK-BIG")

    application = client._transport.app  # type: ignore[attr-defined]
    limit = application.state.settings.source_file_max_bytes
    oversize = b"x" * (limit + 1)
    response = await client.post(
        f"/api/v1/studies/{study_id}/source-files:bulk",
        headers=headers,
        files=[
            ("files", ("ok.csv", b"USUBJID\n01\n", "text/csv")),
            ("files", ("big.csv", oversize, "text/csv")),
        ],
    )
    assert response.status_code == 413, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "source_file_too_large"

    listed = await client.get(f"/api/v1/studies/{study_id}/source-files", headers=headers)
    assert listed.json()["items"] == []
