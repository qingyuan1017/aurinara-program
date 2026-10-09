"""PostgreSQL-backed Phase 1 study, upload, and job workflow."""

import hashlib
import hmac
import io
import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text

from app.api.auth import Principal
from app.artifacts.builds import resolve_build_input
from app.artifacts.storage import ObjectNotFoundError, ObjectStorage
from app.catalog_seed import seed
from app.common.canonical import fingerprint, sha256_hex
from app.config import Settings
from app.database import create_database_engine, create_session_factory
from app.execution.jobs import Job, JobService
from app.integration.delivery import DeliveryService
from app.main import create_app
from app.standards.importer import import_standard_manifest
from app.standards.models import StandardAsset, StandardProduct, StandardVersion
from app.terminology.importer import import_terminology_manifest
from app.terminology.models import (
    TerminologyCodelist,
    TerminologyRelease,
    TerminologyReleaseCompatibility,
    TerminologyTerm,
)
from tests.conftest import make_test_settings
from workers.job_worker import _process_job

pytestmark = pytest.mark.skipif(
    os.getenv("AURINARA_INTEGRATION") != "1",
    reason="set AURINARA_INTEGRATION=1 with the Compose PostgreSQL service running",
)


class TestTokenVerifier:
    """Trusted test-boundary verifier; production tests exercise JWKS separately."""

    def verify(self, token: str) -> Principal:
        assert token == "test-token"
        return Principal(subject="user-1", scopes=frozenset({"*"}))


class MemoryStorage(ObjectStorage):
    """Deterministic byte store for API/database integration tests."""

    def __init__(self, local_fallback_enabled: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.local_fallback_enabled = local_fallback_enabled

    def put_file(self, object_key: str, path: Path, media_type: str) -> None:
        del media_type
        self.objects[object_key] = path.read_bytes()

    @contextmanager
    def open(self, object_key: str) -> Iterator[io.BytesIO]:
        if object_key not in self.objects:
            raise ObjectNotFoundError("object not found")
        yield io.BytesIO(self.objects[object_key])

    def exists(self, object_key: str) -> bool:
        return object_key in self.objects

    def check(self) -> None:
        return None


@pytest.fixture
def integration_settings() -> Settings:
    return make_test_settings()


@pytest.fixture
async def integration_client(integration_settings: Settings) -> AsyncIterator[AsyncClient]:
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
    storage = MemoryStorage()
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
        yield client
    engine.dispose()


@pytest.mark.anyio
async def test_create_study_upload_and_download(integration_client: AsyncClient) -> None:
    headers = {"Authorization": "Bearer test-token"}
    created = await integration_client.post(
        "/api/v1/studies",
        headers=headers,
        json={"code": "SYN-001", "name": "Synthetic Study"},
    )
    assert created.status_code == 201, created.text
    study_id = created.json()["id"]
    assert created.headers["etag"] == '"revision-1"'

    uploaded = await integration_client.post(
        f"/api/v1/studies/{study_id}/source-files",
        headers=headers,
        files={"file": ("raw.csv", b"USUBJID,AGE\n01,42\n", "text/csv")},
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["size"] == 18
    assert len(body["sha256"]) == 64
    assert "object_key" not in body

    downloaded = await integration_client.get(
        f"/api/v1/source-files/{body['id']}/download", headers=headers
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"USUBJID,AGE\n01,42\n"
    validation = await integration_client.post(
        f"/api/v1/artifacts/{body['artifact_id']}/validate", headers=headers
    )
    assert validation.status_code == 202, validation.text
    application = integration_client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    with factory.begin() as session:
        claimed = JobService().claim(session, worker_id="test-worker", lease_seconds=60)
        assert claimed is not None
    _process_job(
        factory,
        application.state.module_registry,
        application.state.object_storage,
        claimed,
    )
    completed = await integration_client.get(
        f"/api/v1/validation-runs/{validation.json()['id']}", headers=headers
    )
    assert completed.json()["status"] == "succeeded"
    assert completed.json()["error_count"] == 0


@pytest.mark.anyio
async def test_exact_dependencies_reference_review_trace_and_reconciliation(
    integration_client: AsyncClient,
) -> None:
    headers = {"Authorization": "Bearer test-token"}
    study = await integration_client.post(
        "/api/v1/studies", headers=headers, json={"code": "SYN-DEP", "name": "Dependencies"}
    )
    study_id = study.json()["id"]
    rule_packs = await integration_client.get("/api/v1/validation-rule-packs", headers=headers)
    assert rule_packs.status_code == 200
    assert rule_packs.json()[0]["code"] == "PLATFORM_INTEGRITY"
    raw = await integration_client.post(
        f"/api/v1/studies/{study_id}/raw",
        headers=headers,
        json={"code": "RAW", "name": "Raw Workbench"},
    )
    assert raw.status_code == 201, raw.text
    raw_id = raw.json()["id"]

    reference = await integration_client.post(
        f"/api/v1/studies/{study_id}/references",
        headers=headers,
        json={
            "reference_type": "vendor",
            "natural_key": "EDC",
            "display_name": "Synthetic EDC",
            "value": {
                "schema_version": "1.0.0",
                "fields": [{"name": "system", "value": "Synthetic"}],
            },
        },
    )
    assert reference.status_code == 201, reference.text
    reference_body = reference.json()
    selection = {
        "standards": [
            {
                "purpose": "dependency_contract",
                "standard_version_id": "10000000-0000-0000-0000-000000000002",
            }
        ],
        "terminology": [
            {
                "scope": "validation",
                "terminology_release_id": "20000000-0000-0000-0000-000000000001",
                "terminology_extension_revision_ids": [],
            }
        ],
        "references": [
            {
                "purpose": "source_system",
                "reference_id": reference_body["id"],
                "reference_revision_id": reference_body["current_revision_id"],
            }
        ],
        "templates": [
            {
                "purpose": "report",
                "artifact_type": "validation_report",
                "template_version_id": "30000000-0000-0000-0000-000000000002",
            }
        ],
    }
    replaced = await integration_client.put(
        f"/api/v1/raw/{raw_id}/dependencies",
        headers={**headers, "If-Match": raw.headers["etag"]},
        json=selection,
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["state"] == "current"

    application = integration_client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    registry = application.state.module_registry
    storage = application.state.object_storage
    with factory() as session:
        _, _, build_input = resolve_build_input(
            session,
            registry,
            study_id=UUID(study_id),
            owner_type="raw_workbench",
            owner_id=UUID(raw_id),
            artifact_types=("raw_dependency_manifest",),
            options={},
        )
    build = await integration_client.post(
        "/api/v1/artifact-builds",
        headers={**headers, "Idempotency-Key": "raw-manifest-1"},
        json={
            "study_id": study_id,
            "owner_type": "raw_workbench",
            "owner_id": raw_id,
            "artifact_types": ["raw_dependency_manifest"],
            "expected_input_fingerprint": fingerprint(build_input),
            "options": {},
        },
    )
    assert build.status_code == 202, build.text
    with factory.begin() as session:
        claimed_build = JobService().claim(session, worker_id="test-worker", lease_seconds=60)
        assert claimed_build is not None
    _process_job(factory, registry, storage, claimed_build)
    completed_build = await integration_client.get(
        f"/api/v1/artifact-builds/{build.json()['id']}", headers=headers
    )
    assert completed_build.json()["status"] == "succeeded"
    artifact_id = completed_build.json()["result_artifact_ids"][0]
    artifact_download = await integration_client.get(
        f"/api/v1/artifacts/{artifact_id}/download", headers=headers
    )
    assert artifact_download.status_code == 200

    review = await integration_client.post(
        f"/api/v1/studies/{study_id}/review-items",
        headers=headers,
        json={
            "target_module": "raw",
            "target_entity_type": "raw_workbench",
            "target_entity_id": raw_id,
            "question": "Confirm the manually selected source system.",
            "priority": "normal",
        },
    )
    assert review.status_code == 201, review.text
    comment = await integration_client.post(
        f"/api/v1/review-items/{review.json()['id']}/comments",
        headers=headers,
        json={"body": "Confirmed using synthetic metadata."},
    )
    assert comment.status_code == 201

    trace = await integration_client.post(
        f"/api/v1/studies/{study_id}/trace-links",
        headers=headers,
        json={
            "relationship_type": "depends_on",
            "source": {"module": "raw", "entity_type": "raw_workbench", "entity_id": raw_id},
            "target": {"module": "raw", "entity_type": "raw_workbench", "entity_id": raw_id},
        },
    )
    assert trace.status_code == 201, trace.text

    changed_reference = await integration_client.patch(
        f"/api/v1/references/{reference_body['id']}",
        headers={**headers, "If-Match": reference.headers["etag"]},
        json={
            "value": {
                "schema_version": "1.0.0",
                "fields": [{"name": "system", "value": "Synthetic v2"}],
            }
        },
    )
    assert changed_reference.status_code == 200, changed_reference.text
    refreshed = await integration_client.get(f"/api/v1/raw/{raw_id}/dependencies", headers=headers)
    assert refreshed.json()["state"] == "dependency_refresh_required"
    stale_artifact = await integration_client.get(
        f"/api/v1/artifacts/{artifact_id}", headers=headers
    )
    assert stale_artifact.json()["status"] == "stale"
    retained = await integration_client.get(
        f"/api/v1/artifacts/{artifact_id}/download", headers=headers
    )
    assert retained.status_code == 200

    selection["references"][0]["reference_revision_id"] = changed_reference.json()[
        "current_revision_id"
    ]
    accepted_refresh = await integration_client.put(
        f"/api/v1/raw/{raw_id}/dependencies",
        headers={**headers, "If-Match": '"revision-2"'},
        json=selection,
    )
    assert accepted_refresh.status_code == 200, accepted_refresh.text
    assert accepted_refresh.json()["state"] == "current"

    request_without_expected = {
        "study_id": study_id,
        "reconciliation_type": "dependency_snapshot",
        "reconciliation_version": "1.0.0",
        "inputs": [
            {
                "entity_type": "raw_workbench",
                "entity_id": raw_id,
                "revision": 3,
                "artifact_id": None,
                "checksum": None,
            }
        ],
        "options": {},
    }
    reconciliation = await integration_client.post(
        "/api/v1/reconciliation-runs",
        headers={**headers, "Idempotency-Key": "reconcile-1"},
        json={
            **request_without_expected,
            "expected_input_fingerprint": fingerprint(request_without_expected),
        },
    )
    assert reconciliation.status_code == 202, reconciliation.text
    replay = await integration_client.post(
        "/api/v1/reconciliation-runs",
        headers={**headers, "Idempotency-Key": "reconcile-1"},
        json={
            **request_without_expected,
            "expected_input_fingerprint": fingerprint(request_without_expected),
        },
    )
    assert replay.json()["id"] == reconciliation.json()["id"]
    with factory.begin() as session:
        claimed_reconciliation = JobService().claim(
            session, worker_id="test-worker", lease_seconds=60
        )
        assert claimed_reconciliation is not None
    _process_job(factory, registry, storage, claimed_reconciliation)
    completed_reconciliation = await integration_client.get(
        f"/api/v1/reconciliation-runs/{reconciliation.json()['id']}", headers=headers
    )
    assert completed_reconciliation.json()["status"] == "succeeded"


@pytest.mark.anyio
async def test_reference_import_and_terminology_extension_revisions(
    integration_client: AsyncClient,
) -> None:
    headers = {"Authorization": "Bearer test-token"}
    study = await integration_client.post(
        "/api/v1/studies", headers=headers, json={"code": "SYN-REG", "name": "Registries"}
    )
    study_id = study.json()["id"]
    application = integration_client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    non_extensible_id = uuid4()
    with factory.begin() as session:
        session.add(
            TerminologyCodelist(
                id=non_extensible_id,
                release_id=UUID("20000000-0000-0000-0000-000000000001"),
                code=f"LOCKED_{non_extensible_id.hex[:8]}",
                name="Synthetic Non-Extensible Codelist",
                synonyms=[],
                extensible=False,
            )
        )
    rejected_extension = await integration_client.post(
        f"/api/v1/studies/{study_id}/terminology-extensions",
        headers=headers,
        json={
            "code": "LOCKED_EXTENSION",
            "name": "Must Be Rejected",
            "base_release_id": "20000000-0000-0000-0000-000000000001",
            "codelist_code": f"LOCKED_{non_extensible_id.hex[:8]}",
        },
    )
    assert rejected_extension.status_code == 422, rejected_extension.text
    assert rejected_extension.json()["code"] == "terminology_codelist_not_extensible"
    imported = await integration_client.post(
        f"/api/v1/studies/{study_id}/references/import",
        headers={**headers, "Idempotency-Key": "reference-import-1"},
        json={
            "schema_version": "1.0.0",
            "items": [
                {
                    "reference_type": "vendor",
                    "natural_key": "LAB",
                    "display_name": "Synthetic Lab",
                    "value": {
                        "schema_version": "1.0.0",
                        "fields": [{"name": "system", "value": "Lab v1"}],
                    },
                }
            ],
        },
    )
    assert imported.status_code == 201, imported.text
    replay = await integration_client.post(
        f"/api/v1/studies/{study_id}/references/import",
        headers={**headers, "Idempotency-Key": "reference-import-1"},
        json={
            "schema_version": "1.0.0",
            "items": [
                {
                    "reference_type": "vendor",
                    "natural_key": "LAB",
                    "display_name": "Synthetic Lab",
                    "value": {
                        "schema_version": "1.0.0",
                        "fields": [{"name": "system", "value": "Lab v1"}],
                    },
                }
            ],
        },
    )
    assert replay.json() == imported.json()
    exported = await integration_client.get(
        f"/api/v1/studies/{study_id}/references/export", headers=headers
    )
    assert exported.json()["items"][0]["natural_key"] == "LAB"

    extension = await integration_client.post(
        f"/api/v1/studies/{study_id}/terminology-extensions",
        headers=headers,
        json={
            "code": "SPONSOR_SEVERITY",
            "name": "Sponsor Severity",
            "base_release_id": "20000000-0000-0000-0000-000000000001",
            "codelist_code": "ISSUE_SEVERITY",
        },
    )
    assert extension.status_code == 201, extension.text
    term = await integration_client.post(
        f"/api/v1/terminology-extensions/{extension.json()['id']}/terms",
        headers={**headers, "If-Match": extension.headers["etag"]},
        json={"code": "NOTICE", "submission_value": "notice", "decode": "Notice"},
    )
    assert term.status_code == 201, term.text
    patched = await integration_client.patch(
        f"/api/v1/terminology-extension-terms/{term.json()['id']}",
        headers={**headers, "If-Match": term.headers["etag"]},
        json={"decode": "Sponsor Notice"},
    )
    assert patched.status_code == 200, patched.text
    revisions = await integration_client.get(
        f"/api/v1/terminology-extensions/{extension.json()['id']}/revisions",
        headers=headers,
    )
    assert [item["revision"] for item in revisions.json()] == [1, 2, 3]
    historical_terms = await integration_client.get(
        f"/api/v1/terminology-extension-revisions/{revisions.json()[1]['id']}/terms",
        headers=headers,
    )
    assert historical_terms.json()[0]["decode"] == "Notice"


@pytest.mark.anyio
async def test_offline_cdisc_package_import_is_atomic_and_queryable(
    integration_client: AsyncClient, tmp_path: Path
) -> None:
    application = integration_client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    product_id, standard_id, asset_id = uuid4(), uuid4(), uuid4()
    release_id, codelist_id, term_id, compatibility_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    asset_path = tmp_path / "schemas" / "cdisc" / "synthetic-model.json"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_text('{"synthetic":true}', encoding="utf-8")
    standard_manifest = tmp_path / "schemas" / "cdisc" / "synthetic-manifest.json"
    standard_manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "provider": "CDISC",
                "product": {
                    "id": str(product_id),
                    "code": f"SYNTHETIC_{product_id.hex[:8].upper()}",
                    "name": "Synthetic CDISC Model",
                    "family": "DataTabulation",
                    "product_type": "model",
                    "scope": "clinical",
                },
                "release": {
                    "id": str(standard_id),
                    "version": "synthetic-1.0",
                    "publication_date": "2026-01-01",
                    "library_href": "https://library.cdisc.org/synthetic",
                    "applicable_modules": ["sdtm"],
                    "purposes": ["model"],
                    "provenance": {"source": "synthetic-test"},
                },
                "assets": [
                    {
                        "id": str(asset_id),
                        "role": "machine_readable_metadata",
                        "media_type": "application/json",
                        "path": "schemas/cdisc/synthetic-model.json",
                        "sha256": sha256_hex(asset_path.read_bytes()),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    terminology_manifest = tmp_path / "terminology" / "cdisc" / "synthetic-ct.json"
    terminology_manifest.parent.mkdir(parents=True)
    terminology_manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "provider": "CDISC",
                "release": {
                    "id": str(release_id),
                    "code": f"SYN_CT_{release_id.hex[:8].upper()}",
                    "product": "SDTM",
                    "version": "synthetic-2026-01-01",
                    "publication_date": "2026-01-01",
                    "applicable_modules": ["sdtm"],
                    "provenance": {"source": "synthetic-test"},
                },
                "codelists": [
                    {
                        "id": str(codelist_id),
                        "concept_id": "C900001",
                        "name": "Synthetic Extensible Codelist",
                        "submission_value": "SYNCL",
                        "extensible": True,
                        "terms": [
                            {
                                "id": str(term_id),
                                "concept_id": "C900002",
                                "submission_value": "VALUE",
                                "decode": "Synthetic Value",
                            }
                        ],
                    }
                ],
                "compatibilities": [
                    {
                        "id": str(compatibility_id),
                        "standard_version_id": str(standard_id),
                        "terminology_scope": "sdtm",
                        "standard_purpose": "model",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with factory.begin() as session:
        imported_standard = import_standard_manifest(session, standard_manifest, tmp_path)
        imported_terminology = import_terminology_manifest(session, terminology_manifest, tmp_path)
        assert imported_standard.id == standard_id
        assert imported_terminology.id == release_id
    headers = {"Authorization": "Bearer test-token"}
    standards_response = await integration_client.get(
        "/api/v1/standards?provider=CDISC&family=DataTabulation", headers=headers
    )
    assert any(item["id"] == str(product_id) for item in standards_response.json())
    assets_response = await integration_client.get(
        f"/api/v1/standard-versions/{standard_id}/assets", headers=headers
    )
    assert assets_response.json()[0]["checksum"] == sha256_hex(asset_path.read_bytes())
    assert "asset_path" not in assets_response.json()[0]
    releases_response = await integration_client.get(
        f"/api/v1/terminology-releases?provider=CDISC&product=SDTM&"
        f"compatible_standard_version_id={standard_id}",
        headers=headers,
    )
    assert any(item["id"] == str(release_id) for item in releases_response.json())
    codelists_response = await integration_client.get(
        f"/api/v1/terminology-releases/{release_id}/codelists?extensible=true",
        headers=headers,
    )
    assert codelists_response.json()[0]["concept_id"] == "C900001"
    with factory.begin() as session:
        codelist = session.scalar(
            select(TerminologyCodelist).where(TerminologyCodelist.id == codelist_id)
        )
        assert codelist is not None and codelist.extensible is True
        assert session.get(TerminologyTerm, term_id).concept_id == "C900002"  # type: ignore[union-attr]
        session.execute(
            delete(TerminologyReleaseCompatibility).where(
                TerminologyReleaseCompatibility.release_id == release_id
            )
        )
        session.execute(delete(TerminologyTerm).where(TerminologyTerm.id == term_id))
        session.execute(delete(TerminologyCodelist).where(TerminologyCodelist.id == codelist_id))
        session.execute(delete(TerminologyRelease).where(TerminologyRelease.id == release_id))
        session.execute(delete(StandardAsset).where(StandardAsset.id == asset_id))
        session.execute(delete(StandardVersion).where(StandardVersion.id == standard_id))
        session.execute(delete(StandardProduct).where(StandardProduct.id == product_id))


@pytest.mark.anyio
async def test_signed_delivery_retry_and_idempotent_redelivery(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = {"Authorization": "Bearer test-token"}
    study = await integration_client.post(
        "/api/v1/studies", headers=headers, json={"code": "SYN-INT", "name": "Integration"}
    )
    study_id = study.json()["id"]
    created = await integration_client.post(
        f"/api/v1/studies/{study_id}/integrations",
        headers=headers,
        json={
            "integration_code": "EDC",
            "display_name": "Synthetic EDC",
            "direction": "outbound",
            "allowed_modules": ["raw"],
        },
    )
    assert created.status_code == 201, created.text
    integration_id = created.json()["integration"]["id"]
    secret = created.json()["secret"]["signing_secret"].encode()
    subscription = await integration_client.post(
        f"/api/v1/integrations/{integration_id}/subscriptions",
        headers=headers,
        json={
            "callback_url": "http://127.0.0.1:8080/events",
            "event_types": ["studies.created"],
            "headers": {"X-Receiver": "synthetic"},
            "timeout_seconds": 5,
        },
    )
    assert subscription.status_code == 201, subscription.text

    captured: list[tuple[bytes, dict[str, str]]] = []
    response_status = {"value": 200}

    class FakeResponse:
        def __init__(self) -> None:
            self.status_code = response_status["value"]
            self.content = b"synthetic receiver"

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, _url: str, *, content: bytes, headers: dict[str, str]) -> FakeResponse:
            captured.append((content, headers))
            return FakeResponse()

    monkeypatch.setattr("app.integration.delivery.httpx.Client", FakeClient)
    application = integration_client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    service = DeliveryService(application.state.module_registry)
    with factory.begin() as session:
        assert service.schedule(session) == 1
    with factory.begin() as session:
        assert service.deliver_one(session, application.state.settings)
    body, delivery_headers = captured[0]
    digest = hashlib.sha256(body).hexdigest()
    signed = (
        f"{delivery_headers['X-Aurinara-Timestamp']}."
        f"{delivery_headers['X-Aurinara-Event-ID']}.{digest}."
    ).encode() + body
    assert delivery_headers["X-Aurinara-Content-Digest"] == f"sha256={digest}"
    assert delivery_headers["X-Aurinara-Signature"] == (
        f"sha256={hmac.new(secret, signed, hashlib.sha256).hexdigest()}"
    )

    deliveries = await integration_client.get(
        f"/api/v1/integrations/{integration_id}/deliveries", headers=headers
    )
    first_delivery = deliveries.json()[0]
    assert first_delivery["status"] == "succeeded"
    redelivery = await integration_client.post(
        f"/api/v1/integration-deliveries/{first_delivery['id']}/redeliver",
        headers={**headers, "Idempotency-Key": "redeliver-1"},
    )
    assert redelivery.status_code == 202, redelivery.text
    replay = await integration_client.post(
        f"/api/v1/integration-deliveries/{first_delivery['id']}/redeliver",
        headers={**headers, "Idempotency-Key": "redeliver-1"},
    )
    assert replay.json()["id"] == redelivery.json()["id"]
    response_status["value"] = 500
    with factory.begin() as session:
        assert service.deliver_one(session, application.state.settings)
    attempts = await integration_client.get(
        f"/api/v1/integrations/{integration_id}/deliveries", headers=headers
    )
    assert {item["status"] for item in attempts.json()} == {"succeeded", "failed", "queued"}


def test_job_claim_retry_recovery_and_completion(integration_settings: Settings) -> None:
    engine = create_database_engine(integration_settings)
    factory = create_session_factory(engine)
    operation_id = uuid4()
    with factory.begin() as session:
        session.execute(delete(Job))
        session.add(
            Job(
                operation_id=operation_id,
                job_type="test",
                payload={"schema_version": "1.0.0"},
                max_attempts=2,
            )
        )

    service = JobService()
    with factory.begin() as session:
        claimed = service.claim(session, worker_id="worker-1", lease_seconds=1)
        assert claimed is not None
        service.fail(claimed, {"code": "transient"})
    with factory.begin() as session:
        recovered = service.claim(session, worker_id="worker-2", lease_seconds=1)
        assert recovered is not None
        assert recovered.operation_id == operation_id
        service.complete(recovered)
    with factory() as session:
        finished = session.get(Job, recovered.id)
        assert finished is not None
        assert finished.status == "succeeded"
        assert finished.attempt_count == 2
    engine.dispose()
