"""Execution job staging, isolated dispatch, output validation, and publication."""

import shutil
import tempfile
import time
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.artifacts.models import Artifact
from app.artifacts.service import (
    ArtifactService,
    StoredObject,
    store_bytes_object,
    store_json_object,
)
from app.artifacts.storage import ObjectStorage
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.config import Settings
from app.execution.adapters import ExecutionLimits, ExecutionRequest, Executor
from app.execution.contracts import ExecutionProduct
from app.execution.jobs import Job, JobService
from app.execution.models import ExecutionRun
from app.execution.staging import tabular_csv_bytes
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry


class ExecutionOutputCapability(Protocol):
    def prepare_execution_outputs(
        self,
        program_manifest: dict[str, object],
        files: dict[str, bytes],
        maximum_bytes: int,
    ) -> tuple[ExecutionProduct, ...]: ...


def _copy_object(storage: ObjectStorage, artifact: Artifact, destination: Path) -> None:
    with storage.open(artifact.object_key) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)


def _cancellation_requested(factory: sessionmaker[Session], run_id: UUID) -> bool:
    with factory() as session:
        run = session.get(ExecutionRun, run_id)
        return run is None or run.cancellation_requested_at is not None


def process_execution_job(
    factory: sessionmaker[Session],
    registry: ModuleRegistry,
    storage: ObjectStorage,
    executor: Executor,
    settings: Settings,
    job_id: UUID,
) -> None:
    """Process one claimed execution job without holding I/O transactions open."""

    with factory.begin() as session:
        job = session.get(Job, job_id)
        run = session.get(ExecutionRun, job.operation_id) if job is not None else None
        if job is None or run is None:
            return
        if job.cancellation_requested_at is not None or run.status == "cancelled":
            run.status = "cancelled"
            run.completed_at = utc_now()
            JobService().complete(job)
            return
        program = session.get(Artifact, run.program_artifact_id)
        inputs = [session.get(Artifact, UUID(item)) for item in run.input_artifact_ids]
        if program is None or any(item is None for item in inputs):
            JobService().fail(job, {"code": "execution_artifact_missing"})
            return
        run.status = "running"
        run.started_at = run.started_at or utc_now()
        program_snapshot = program
        input_snapshots = cast(list[Artifact], inputs)
        manifest_inputs = cast(list[dict[str, object]], run.manifest["inputs"])
        limits = ExecutionLimits(
            cpu=float(cast(int | float, run.limits["cpu"])),
            memory_mb=cast(int, run.limits["memory_mb"]),
            runtime_seconds=cast(int, run.limits["runtime_seconds"]),
            output_bytes=cast(int, run.limits["output_bytes"]),
        )
        language = run.language
        module_key = run.module_key
        run_id = run.id
        study_id = run.study_id

    started = time.monotonic()
    stored_outputs: list[tuple[ExecutionProduct, StoredObject]] = []
    result = None
    failure: dict[str, object] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="aurinara-execution-") as temporary:
            workspace = Path(temporary)
            input_directory = workspace / "inputs"
            output_directory = workspace / "outputs"
            input_directory.mkdir()
            output_directory.mkdir()
            workspace.chmod(0o755)
            input_directory.chmod(0o755)
            output_directory.chmod(0o777)
            program_name = "program.py" if language == "python" else "program.R"
            _copy_object(storage, program_snapshot, workspace / program_name)
            (workspace / program_name).chmod(0o444)
            by_id = {item.id: item for item in input_snapshots}
            for item in manifest_inputs:
                artifact = by_id[UUID(str(item["artifact_id"]))]
                input_path = input_directory / f"{item['dataset']}.csv"
                with storage.open(artifact.object_key) as source:
                    staged_data = tabular_csv_bytes(source.read(), artifact.filename)
                input_path.write_bytes(staged_data)
                input_path.chmod(0o444)
            image = (
                settings.python_runner_image if language == "python" else settings.r_runner_image
            )
            result = executor.execute(
                ExecutionRequest(
                    execution_id=run_id,
                    language=language,
                    workspace=workspace,
                    image=image,
                    limits=limits,
                    cancel_requested=lambda: _cancellation_requested(factory, run_id),
                )
            )
            if result.status == "succeeded":
                entries = tuple(output_directory.iterdir())
                if any(item.is_symlink() or not item.is_file() for item in entries):
                    raise ValueError("execution outputs must be regular top-level files")
                files = {item.name: item.read_bytes() for item in entries}
                output_handler = cast(
                    ExecutionOutputCapability,
                    registry.require_handler(module_key, ModuleCapability.EXECUTION),
                )
                products = output_handler.prepare_execution_outputs(
                    program_snapshot.manifest, files, limits.output_bytes
                )
                stored_outputs = [
                    (
                        product,
                        store_bytes_object(
                            storage,
                            product.data,
                            product.media_type,
                            study_id=study_id,
                            external_reference=(
                                f"execution:{run_id}:{product.artifact_type}:{product.filename}"
                            ),
                        ),
                    )
                    for product in products
                ]
            else:
                failure = result.failure or {"code": "execution_failed"}
    except ProblemException as error:
        failure = {"code": error.code, "detail": error.detail}
    except (KeyError, OSError, UnicodeError, ValueError) as error:
        failure = {"code": "execution_output_invalid", "detail": str(error)}

    duration = time.monotonic() - started
    stdout = (result.stdout if result else b"").decode("utf-8", errors="replace")
    stderr = (result.stderr if result else b"").decode("utf-8", errors="replace")
    metrics: dict[str, object] = {"wall_time_seconds": duration}
    log_payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "execution_run_id": str(run_id),
        "module": module_key,
        "language": language,
        "status": "succeeded" if failure is None else "failed",
        "exit_code": result.exit_code if result else None,
        "stdout": stdout,
        "stderr": stderr,
        "metrics": metrics,
        "failure": failure,
    }
    stored_log = store_json_object(
        storage,
        log_payload,
        study_id=study_id,
        external_reference=f"execution:{run_id}:log",
    )
    with factory.begin() as session:
        job = session.get(Job, job_id)
        run = session.get(ExecutionRun, run_id)
        if job is None or run is None:
            return
        if job.cancellation_requested_at is not None or run.cancellation_requested_at is not None:
            run.status = "cancelled"
            run.completed_at = utc_now()
            JobService().complete(job)
            return
        run.stdout = stdout
        run.stderr = stderr
        run.exit_code = result.exit_code if result else None
        run.metrics = metrics
        artifact_service = ArtifactService()
        artifact_service.record_artifact(
            session,
            stored=stored_log,
            study_id=run.study_id,
            module_key=run.module_key,
            artifact_type=f"{run.module_key}_execution_log",
            owner_type=run.owner_type,
            owner_id=run.owner_id,
            filename=f"{run.module_key}-execution-log.json",
            media_type="application/json",
            manifest={
                **run.manifest,
                "execution_log": {
                    "schema_version": "1.0.0",
                    "execution_run_id": str(run.id),
                    "language": run.language,
                    "status": log_payload["status"],
                },
            },
            input_fingerprint=run.input_fingerprint,
            dependency_selection_revision=program_snapshot.dependency_selection_revision,
            dependency_fingerprint=program_snapshot.dependency_fingerprint,
            generator_name=f"{run.module_key}-{run.language}-execution-log",
            generator_version="1.0.0",
            created_by=run.created_by,
            validation_run_id=run.validation_run_id,
            execution_run_id=run.id,
            input_selection_revision=run.input_selection_revision,
            source_specification_revision=run.source_specification_revision,
            source_specification_fingerprint=program_snapshot.source_specification_fingerprint,
            source_plan_type=run.source_plan_type,
            source_plan_revision=run.source_plan_revision,
            compiler_fingerprint=run.compiler_fingerprint,
        )
        if failure is not None:
            run.failure = failure
            JobService().fail(job, failure)
            run.status = "queued" if job.status == "queued" else "failed"
            run.completed_at = job.completed_at
            return
        output_ids: list[str] = []
        for product, stored in stored_outputs:
            artifact = artifact_service.record_artifact(
                session,
                stored=stored,
                study_id=run.study_id,
                module_key=run.module_key,
                artifact_type=product.artifact_type,
                owner_type=run.owner_type,
                owner_id=run.owner_id,
                filename=product.filename,
                media_type=product.media_type,
                manifest={**run.manifest, **product.manifest},
                input_fingerprint=run.input_fingerprint,
                dependency_selection_revision=program_snapshot.dependency_selection_revision,
                dependency_fingerprint=program_snapshot.dependency_fingerprint,
                generator_name=f"{run.module_key}-{run.language}-execution",
                generator_version="1.0.0",
                created_by=run.created_by,
                validation_run_id=run.validation_run_id,
                execution_run_id=run.id,
                input_selection_revision=run.input_selection_revision,
                source_specification_revision=run.source_specification_revision,
                source_specification_fingerprint=(
                    program_snapshot.source_specification_fingerprint
                ),
                source_plan_type=run.source_plan_type,
                source_plan_revision=run.source_plan_revision,
                compiler_fingerprint=run.compiler_fingerprint,
            )
            output_ids.append(str(artifact.id))
        run.output_artifact_ids = output_ids
        run.status = "succeeded"
        run.completed_at = utc_now()
        JobService().complete(job)
