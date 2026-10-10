"""PostgreSQL-backed Phase 5 TLF execution, rendering, and packaging workflow."""

import hashlib
import io
import os
import subprocess
import sys
import zipfile
from collections.abc import AsyncIterator
from uuid import UUID

import pyarrow.parquet as parquet
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.adam.models import AdamDependencySelection, AdamWorkbench
from app.artifacts.builds import resolve_build_input
from app.artifacts.models import Artifact
from app.artifacts.service import ArtifactService, store_bytes_object
from app.catalog_seed import seed
from app.common.canonical import fingerprint
from app.database import create_database_engine, create_session_factory
from app.execution.adapters import ExecutionRequest, ExecutionResult
from app.execution.jobs import JobService
from app.execution.models import ExecutionRun
from app.execution.worker import process_execution_job
from app.main import create_app
from app.packaging.service import resolve_package
from app.validation.models import ValidationRun
from tests.conftest import make_test_settings
from tests.integration.test_phase1_core import MemoryStorage, TestTokenVerifier
from workers.job_worker import _process_job

pytestmark = pytest.mark.skipif(
    os.getenv("AURINARA_INTEGRATION") != "1",
    reason="set AURINARA_INTEGRATION=1 with the Compose PostgreSQL service running",
)


class HostPythonExecutor:
    """Test-only executor for a deterministic generated Python program."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        completed = subprocess.run(
            [sys.executable, "-I", str(request.workspace / "program.py")],
            check=False,
            capture_output=True,
            env={**os.environ, "AURINARA_WORKSPACE": str(request.workspace)},
            timeout=request.limits.runtime_seconds,
        )
        return ExecutionResult(
            status="succeeded" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            failure=None if completed.returncode == 0 else {"code": "program_failed"},
        )


@pytest.fixture
async def phase5_client() -> AsyncIterator[AsyncClient]:
    settings = make_test_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE submission_packages, tlf_authoring_revisions, execution_runs, "
                "validation_runs, artifacts, jobs, idempotency_records, outbox_events, "
                "study_memberships, studies CASCADE"
            )
        )
    storage = MemoryStorage()
    with factory() as session:
        seed(session, storage)
    application = create_app(
        settings=settings,
        session_factory=factory,
        object_storage=storage,
        token_verifier=TestTokenVerifier(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        yield client
    engine.dispose()


@pytest.mark.anyio
async def test_tlf_execute_render_and_deterministic_package(
    phase5_client: AsyncClient,
) -> None:
    client = phase5_client
    headers = {"Authorization": "Bearer test-token"}
    study = await client.post(
        "/api/v1/studies",
        headers=headers,
        json={"code": "P5-001", "name": "Phase 5"},
    )
    assert study.status_code == 201, study.text
    study_id = UUID(study.json()["id"])
    application = client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    storage = application.state.object_storage

    with factory.begin() as session:
        adam = AdamWorkbench(study_id=study_id, code="ADAM", name="ADaM")
        session.add(adam)
        session.flush()
        dependency_payload = {
            "standards": [],
            "terminology": [],
            "references": [],
            "templates": [],
        }
        dependency_fingerprint = fingerprint(dependency_payload)
        session.add(
            AdamDependencySelection(
                aggregate_id=adam.id,
                study_id=study_id,
                revision=1,
                state="current",
                payload=dependency_payload,
                fingerprint=dependency_fingerprint,
            )
        )
        validation = ValidationRun(
            study_id=study_id,
            module_key="adam",
            owner_type="adam_workbench",
            owner_id=adam.id,
            status="succeeded",
            validator_name="adam-authoring-validator",
            validator_version="1.0.0",
            input_fingerprint="1" * 64,
            input_manifest={"adam_revision": adam.revision},
            error_count=0,
            warning_count=0,
            info_count=0,
            issues=[],
            report_artifact_ids=[],
            created_by="user-1",
        )
        session.add(validation)
        session.flush()
        artifact_service = ArtifactService()
        program_stored = store_bytes_object(storage, b"# frozen ADaM program\n", "text/x-python")
        adam_program = artifact_service.record_artifact(
            session,
            stored=program_stored,
            study_id=study_id,
            module_key="adam",
            artifact_type="adam_program_python",
            owner_type="adam_workbench",
            owner_id=adam.id,
            filename="adam.py",
            media_type="text/x-python",
            manifest={"schema_version": "1.0.0"},
            input_fingerprint="2" * 64,
            dependency_selection_revision=1,
            dependency_fingerprint=dependency_fingerprint,
            generator_name="test",
            generator_version="1.0.0",
            created_by="user-1",
            validation_run_id=validation.id,
            source_specification_revision=adam.revision,
        )
        adam_run = ExecutionRun(
            study_id=study_id,
            module_key="adam",
            owner_type="adam_workbench",
            owner_id=adam.id,
            language="python",
            program_artifact_id=adam_program.id,
            input_artifact_ids=[],
            validation_run_id=validation.id,
            input_selection_revision=1,
            source_specification_revision=adam.revision,
            source_plan_type="adam_derivation_plan",
            source_plan_revision=1,
            compiler_fingerprint="3" * 64,
            input_fingerprint="4" * 64,
            limits={},
            manifest={},
            status="succeeded",
            output_artifact_ids=[],
            created_by="user-1",
        )
        session.add(adam_run)
        session.flush()
        input_bytes = b"USUBJID,SAFFL,EOSSTT\n01,Y,COMPLETED\n02,Y,DISCONTINUED\n03,N,COMPLETED\n"
        input_stored = store_bytes_object(storage, input_bytes, "text/csv")
        adam_output = artifact_service.record_artifact(
            session,
            stored=input_stored,
            study_id=study_id,
            module_key="adam",
            artifact_type="adam_dataset_csv",
            owner_type="adam_workbench",
            owner_id=adam.id,
            filename="ADSL.csv",
            media_type="text/csv",
            manifest={
                "schema_version": "1.0.0",
                "dataset": "ADSL",
                "source_specification": {
                    "revision": 1,
                    "fingerprint": "5" * 64,
                    "payload": {
                        "datasets": [
                            {
                                "code": "ADSL",
                                "variables": [
                                    {"name": "USUBJID"},
                                    {"name": "SAFFL"},
                                    {"name": "EOSSTT"},
                                ],
                            }
                        ]
                    },
                },
            },
            input_fingerprint="4" * 64,
            dependency_selection_revision=1,
            dependency_fingerprint=dependency_fingerprint,
            generator_name="test",
            generator_version="1.0.0",
            created_by="user-1",
            validation_run_id=validation.id,
            execution_run_id=adam_run.id,
            source_specification_revision=adam.revision,
        )
        adam_run.output_artifact_ids = [str(adam_output.id)]
        adam_id = adam.id
        adam_validation_id = validation.id
        adam_artifact_id = adam_output.id
        adam_checksum = adam_output.sha256

    created = await client.post(
        f"/api/v1/studies/{study_id}/tlfs",
        headers=headers,
        json={"code": "T-14-1", "name": "Disposition"},
    )
    assert created.status_code == 201, created.text
    tlf_id = created.json()["id"]
    dependency = await client.put(
        f"/api/v1/tlfs/{tlf_id}/dependencies",
        headers={**headers, "If-Match": created.headers["etag"]},
        json={
            "templates": [
                {
                    "purpose": "presentation",
                    "artifact_type": "tlf_table_pdf",
                    "template_version_id": "30000000-0000-0000-0000-000000000006",
                }
            ]
        },
    )
    assert dependency.status_code == 200, dependency.text
    shell = await client.put(
        f"/api/v1/tlfs/{tlf_id}/shell",
        headers={**headers, "If-Match": dependency.headers["etag"]},
        json={
            "output_code": "T-14-1",
            "output_type": "table",
            "title": "Subject disposition",
            "columns": [{"id": "value", "label": "Subjects", "order": 1}],
            "rows": [{"id": "completed", "label": "Completed", "order": 1, "leaf": True}],
        },
    )
    assert shell.status_code == 200, shell.text
    bindings = await client.put(
        f"/api/v1/tlfs/{tlf_id}/bindings",
        headers={**headers, "If-Match": shell.headers["etag"]},
        json={
            "datasets": [
                {
                    "id": "adsl",
                    "adam_id": str(adam_id),
                    "adam_revision": 1,
                    "dataset_code": "ADSL",
                    "artifact_id": str(adam_artifact_id),
                    "checksum": adam_checksum,
                    "validation_run_id": str(adam_validation_id),
                    "dependency_fingerprint": dependency_fingerprint,
                }
            ],
            "named": [
                {
                    "id": "safety",
                    "kind": "population",
                    "dataset_binding_id": "adsl",
                    "variable": "SAFFL",
                    "value": "Y",
                },
                {
                    "id": "frequency",
                    "kind": "statistic",
                    "dataset_binding_id": "adsl",
                    "variable": "STAT",
                    "value": "frequency",
                },
            ],
        },
    )
    assert bindings.status_code == 200, bindings.text
    assumptions = await client.put(
        f"/api/v1/tlfs/{tlf_id}/assumptions",
        headers={**headers, "If-Match": bindings.headers["etag"]},
        json={"items": [{"id": "a1", "text": "Safety population is manually selected."}]},
    )
    assert assumptions.status_code == 200, assumptions.text
    ars = await client.put(
        f"/api/v1/tlfs/{tlf_id}/ars",
        headers={**headers, "If-Match": assumptions.headers["etag"]},
        json={
            "analyses": [
                {
                    "id": "completed_analysis",
                    "leaf_row_id": "completed",
                    "dataset_binding_id": "adsl",
                    "population_binding_id": "safety",
                    "statistic_binding_id": "frequency",
                    "order": 1,
                }
            ]
        },
    )
    assert ars.status_code == 200, ars.text
    plan = await client.put(
        f"/api/v1/tlfs/{tlf_id}/program-plan",
        headers={**headers, "If-Match": ars.headers["etag"]},
        json={
            "shell_revision": 1,
            "bindings_revision": 1,
            "assumptions_revision": 1,
            "ars_revision": 1,
            "output_filename": "t_14_1.csv",
            "steps": [
                {
                    "id": "frequency_step",
                    "analysis_id": "completed_analysis",
                    "method": "frequency",
                    "variable": "EOSSTT",
                    "order": 1,
                }
            ],
        },
    )
    assert plan.status_code == 200, plan.text
    validation = await client.post(f"/api/v1/tlfs/{tlf_id}/validate", headers=headers)
    assert validation.status_code == 200, validation.text
    preview = await client.post(f"/api/v1/tlfs/{tlf_id}/program-plan/preview", headers=headers)
    assert preview.status_code == 200, preview.text
    assert "Subject disposition" not in str(preview.json()["normalized_analysis_ir"])

    with factory() as session:
        _, _, program_resolved = resolve_build_input(
            session,
            application.state.module_registry,
            study_id=study_id,
            owner_type="tlf_workbench",
            owner_id=UUID(tlf_id),
            artifact_types=("tlf_program_python",),
            options={},
        )
    program_build = await client.post(
        f"/api/v1/tlfs/{tlf_id}/compile",
        headers={**headers, "Idempotency-Key": "tlf-program-1"},
        json={
            "backend": "python",
            "expected_input_fingerprint": fingerprint(program_resolved),
        },
    )
    assert program_build.status_code == 202, program_build.text
    with factory.begin() as session:
        job = JobService().claim(session, worker_id="phase5-build", lease_seconds=60)
        assert job is not None
    _process_job(factory, application.state.module_registry, storage, job)
    completed_build = await client.get(
        f"/api/v1/artifact-builds/{program_build.json()['id']}", headers=headers
    )
    assert completed_build.json()["status"] == "succeeded", completed_build.text
    program_id = UUID(completed_build.json()["result_artifact_ids"][0])
    with factory() as session:
        program = session.get(Artifact, program_id)
        assert program is not None
        compiler_fingerprint = program.compiler_fingerprint
        program_input_fingerprint = program.input_fingerprint
    execution = await client.post(
        f"/api/v1/tlfs/{tlf_id}/execute",
        headers={**headers, "Idempotency-Key": "tlf-execution-1"},
        json={
            "language": "python",
            "program_artifact_id": str(program_id),
            "input_artifact_ids": [str(adam_artifact_id)],
            "validation_run_id": validation.json()["id"],
            "bindings_revision": 1,
            "shell_revision": 1,
            "program_plan_revision": 1,
            "compiler_fingerprint": compiler_fingerprint,
            "expected_input_fingerprint": program_input_fingerprint,
            "limits": {"cpu": 1, "memory_mb": 256, "runtime_seconds": 30, "output_bytes": 100000},
        },
    )
    assert execution.status_code == 202, execution.text
    with factory.begin() as session:
        execution_job = JobService().claim(session, worker_id="phase5-execution", lease_seconds=60)
        assert execution_job is not None
    process_execution_job(
        factory,
        application.state.module_registry,
        storage,
        HostPythonExecutor(),
        application.state.settings,
        execution_job.id,
    )
    completed_execution = await client.get(
        f"/api/v1/execution-runs/{execution.json()['id']}", headers=headers
    )
    assert completed_execution.json()["status"] == "succeeded", completed_execution.text
    output_ids = [UUID(value) for value in completed_execution.json()["output_artifact_ids"]]
    assert len(output_ids) == 2
    result_id = output_ids[0]
    with factory() as session:
        parquet_artifact = session.get(Artifact, output_ids[1])
        assert parquet_artifact is not None
        assert parquet_artifact.artifact_type == "tlf_result_parquet"
        with storage.open(parquet_artifact.object_key) as stream:
            result_table = parquet.read_table(stream)
        assert result_table.num_rows > 0
        assert result_table.column_names

    with factory() as session:
        _, _, render_resolved = resolve_build_input(
            session,
            application.state.module_registry,
            study_id=study_id,
            owner_type="tlf_workbench",
            owner_id=UUID(tlf_id),
            artifact_types=("tlf_table_pdf",),
            options={},
        )
    rendered = await client.post(
        f"/api/v1/tlfs/{tlf_id}/render",
        headers={**headers, "Idempotency-Key": "tlf-render-1"},
        json={"format": "pdf", "expected_input_fingerprint": fingerprint(render_resolved)},
    )
    assert rendered.status_code == 202, rendered.text
    with factory.begin() as session:
        render_job = JobService().claim(session, worker_id="phase5-render", lease_seconds=60)
        assert render_job is not None
    _process_job(factory, application.state.module_registry, storage, render_job)
    completed_render = await client.get(
        f"/api/v1/artifact-builds/{rendered.json()['id']}", headers=headers
    )
    assert completed_render.json()["status"] == "succeeded", completed_render.text
    rendered_id = UUID(completed_render.json()["result_artifact_ids"][0])

    module_selection = {
        "module": "tlf",
        "artifact_ids": [str(result_id), str(rendered_id)],
        "options": {},
    }
    with factory() as session:
        resolved_package = resolve_package(
            session,
            application.state.module_registry,
            study_id=study_id,
            module_selections=(module_selection,),
            supporting_artifact_ids=(),
            reconciliation_run_ids=(),
        )
    package = await client.post(
        f"/api/v1/studies/{study_id}/submission-packages",
        headers={**headers, "Idempotency-Key": "package-1"},
        json={
            "name": "TLF delivery",
            "module_selections": [module_selection],
            "artifact_ids": [],
            "reconciliation_run_ids": [],
            "expected_study_fingerprint": resolved_package.fingerprint,
        },
    )
    assert package.status_code == 202, package.text
    assert package.json()["status"] == "queued"
    with factory.begin() as session:
        package_job = JobService().claim(
            session,
            worker_id="phase5-package",
            lease_seconds=60,
            job_types=("submission_package",),
        )
        assert package_job is not None
    _process_job(factory, application.state.module_registry, storage, package_job)
    completed_package = await client.get(
        f"/api/v1/submission-packages/{package.json()['id']}", headers=headers
    )
    assert completed_package.json()["status"] == "succeeded", completed_package.text
    downloaded = await client.get(
        f"/api/v1/submission-packages/{package.json()['id']}/download", headers=headers
    )
    assert downloaded.status_code == 200, downloaded.text
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        for line in archive.read("checksums.sha256").decode("utf-8").splitlines():
            expected, path = line.split("  ", 1)
            assert hashlib.sha256(archive.read(path)).hexdigest() == expected
