"""Durable build and reconciliation worker process."""

import hashlib
import logging
import signal
import time
from types import FrameType
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.artifacts.builds import resolve_build_input
from app.artifacts.models import Artifact, ArtifactBuild
from app.artifacts.service import (
    ArtifactService,
    StoredObject,
    store_bytes_object,
    store_json_object,
)
from app.artifacts.storage import ObjectStorage, S3ObjectStorage
from app.common.canonical import fingerprint
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.composition import build_module_registry
from app.config import Settings, get_settings
from app.database import create_database_engine, create_session_factory
from app.execution.jobs import Job, JobService
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import RenderedArtifact
from app.kernel.registry import ModuleRegistry
from app.packaging.models import SubmissionPackage
from app.packaging.service import (
    build_package,
    publish_package,
    resolve_package,
    store_built_package,
)
from app.reconciliation.models import ReconciliationRun
from app.reconciliation.service import ReconciliationCapability
from app.validation.models import ValidationRun

logger = logging.getLogger(__name__)
_stopping = False


def _request_stop(_signal: int, _frame: FrameType | None) -> None:
    global _stopping
    _stopping = True


def _handle_artifact_build(
    factory: sessionmaker[Session],
    registry: ModuleRegistry,
    storage: ObjectStorage,
    job_id: UUID,
) -> None:
    """Resolve inputs, upload bytes outside a transaction, then publish atomically."""

    with factory.begin() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        build = session.get(ArtifactBuild, UUID(str(job.payload["build_id"])))
        if build is None:
            JobService().fail(job, {"code": "artifact_build_missing"})
            return
        if job.cancellation_requested_at is not None or build.status == "cancelled":
            build.status = "cancelled"
            build.completed_at = utc_now()
            JobService().complete(job)
            return
        build.status = "running"
        build.started_at = build.started_at or utc_now()
        _, handler, resolved = resolve_build_input(
            session,
            registry,
            study_id=build.study_id,
            owner_type=build.owner_type,
            owner_id=build.owner_id,
            artifact_types=build.artifact_types,
            options=build.options,
        )
        if fingerprint(resolved) != build.input_fingerprint:
            build.status = "failed"
            build.failure = {"code": "stale_build_inputs"}
            build.completed_at = utc_now()
            JobService().fail(job, build.failure)
            return
        payloads = cast(list[dict[str, object]], resolved["payloads"])

    rendered: list[RenderedArtifact] = [
        handler.render_artifact(payload, storage) for payload in payloads
    ]
    stored: list[StoredObject] = [
        store_bytes_object(storage, product.data, product.media_type) for product in rendered
    ]

    artifact_service = ArtifactService()
    with factory.begin() as session:
        job = session.get(Job, job_id)
        build = session.get(ArtifactBuild, UUID(str(job.payload["build_id"]))) if job else None
        if job is None or build is None:
            return
        if job.cancellation_requested_at is not None or build.status == "cancelled":
            build.status = "cancelled"
            build.completed_at = utc_now()
            JobService().complete(job)
            return
        _, _, current = resolve_build_input(
            session,
            registry,
            study_id=build.study_id,
            owner_type=build.owner_type,
            owner_id=build.owner_id,
            artifact_types=build.artifact_types,
            options=build.options,
        )
        if fingerprint(current) != build.input_fingerprint:
            build.status = "failed"
            build.failure = {"code": "stale_build_inputs"}
            build.completed_at = utc_now()
            JobService().fail(job, build.failure)
            return
        result_ids: list[str] = []
        for artifact_type, payload, product, stored_object in zip(
            build.artifact_types, payloads, rendered, stored, strict=True
        ):
            selection = cast(dict[str, object], payload["dependency_selection"])
            input_selection = cast(dict[str, object] | None, payload.get("input_selection"))
            specification = cast(dict[str, object] | None, payload.get("specification"))
            source_plan = cast(dict[str, object] | None, payload.get("source_plan"))
            compiler = cast(dict[str, object] | None, product.manifest.get("compiler"))
            artifact = artifact_service.record_artifact(
                session,
                stored=stored_object,
                study_id=build.study_id,
                module_key=build.module_key,
                artifact_type=artifact_type,
                owner_type=build.owner_type,
                owner_id=build.owner_id,
                filename=product.filename,
                media_type=product.media_type,
                manifest=product.manifest,
                input_fingerprint=build.input_fingerprint,
                dependency_selection_revision=cast(int, selection["revision"]),
                dependency_fingerprint=str(selection["fingerprint"]),
                generator_name=f"{build.module_key}-artifact-builder",
                generator_version="1.0.0",
                created_by=build.created_by,
                validation_run_id=product.validation_run_id,
                reconciliation_run_id=product.reconciliation_run_id,
                input_selection_revision=(
                    cast(int, input_selection["revision"]) if input_selection is not None else None
                ),
                source_specification_revision=(
                    cast(int, specification["revision"]) if specification is not None else None
                ),
                source_specification_fingerprint=(
                    str(specification["fingerprint"]) if specification is not None else None
                ),
                source_plan_type=(str(source_plan["type"]) if source_plan is not None else None),
                source_plan_revision=(
                    cast(int, source_plan["revision"]) if source_plan is not None else None
                ),
                compiler_fingerprint=(
                    str(compiler["fingerprint"]) if compiler is not None else None
                ),
            )
            if product.validation_run_id is not None and artifact_type.startswith(
                "document_validation_report_"
            ):
                validation_run = session.get(ValidationRun, product.validation_run_id)
                if validation_run is not None:
                    validation_run.report_artifact_ids = [
                        *validation_run.report_artifact_ids,
                        str(artifact.id),
                    ]
            result_ids.append(str(artifact.id))
        build.result_artifact_ids = result_ids
        build.status = "succeeded"
        build.completed_at = utc_now()
        JobService().complete(job)


def _handle_reconciliation(
    factory: sessionmaker[Session],
    registry: ModuleRegistry,
    storage: ObjectStorage,
    job_id: UUID,
) -> None:
    """Resolve exact inputs, compare outside a transaction, and publish immutable evidence."""

    with factory.begin() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        run = session.get(ReconciliationRun, UUID(str(job.payload["run_id"])))
        if run is None:
            JobService().fail(job, {"code": "reconciliation_run_missing"})
            return
        if job.cancellation_requested_at is not None or run.status == "cancelled":
            run.status = "cancelled"
            run.completed_at = utc_now()
            JobService().complete(job)
            return
        run.status = "running"
        run.started_at = run.started_at or utc_now()
        owner = registry.owner_of("reconciliation_types", run.reconciliation_type)
        if owner is None:
            run.status = "failed"
            run.failure = {"code": "reconciliation_type_unsupported"}
            run.completed_at = utc_now()
            JobService().fail(job, run.failure)
            return
        handler = cast(
            ReconciliationCapability,
            registry.require_handler(owner, ModuleCapability.RECONCILIATION),
        )
        resolved = handler.resolve_reconciliation(
            session, run.study_id, run.reconciliation_type, run.inputs, run.options
        )
        resolved_fingerprint = fingerprint(resolved)
        run_id = run.id
        study_id = run.study_id
        created_by = run.created_by
        input_fingerprint = run.input_fingerprint

    evaluation = handler.evaluate_reconciliation(resolved, storage)
    counts = {
        severity: sum(1 for issue in evaluation.issues if issue.get("severity") == severity)
        for severity in ("error", "warning", "info")
    }
    report: dict[str, object] = {
        "schema_version": "1.0.0",
        "reconciliation_run_id": str(run_id),
        "study_id": str(study_id),
        "reconciliation_type": resolved["reconciliation_type"],
        "input_fingerprint": input_fingerprint,
        "resolved_input_fingerprint": resolved_fingerprint,
        "issues": list(evaluation.issues),
        "counts": counts,
        "evidence": evaluation.evidence,
    }

    stored = store_json_object(storage, report)
    with factory.begin() as session:
        job = session.get(Job, job_id)
        run = session.get(ReconciliationRun, run_id)
        if job is None or run is None:
            return
        if job.cancellation_requested_at is not None or run.status == "cancelled":
            run.status = "cancelled"
            run.completed_at = utc_now()
            JobService().complete(job)
            return
        current = handler.resolve_reconciliation(
            session, run.study_id, run.reconciliation_type, run.inputs, run.options
        )
        if fingerprint(current) != resolved_fingerprint:
            run.status = "failed"
            run.failure = {"code": "stale_reconciliation_inputs"}
            run.completed_at = utc_now()
            JobService().fail(job, run.failure)
            return
        artifact = ArtifactService().record_json_artifact(
            session,
            stored=stored,
            study_id=study_id,
            module_key="reconciliation",
            artifact_type="reconciliation_report_json",
            owner_type="reconciliation_run",
            owner_id=run.id,
            payload=report,
            input_fingerprint=input_fingerprint,
            dependency_selection_revision=None,
            dependency_fingerprint=None,
            generator_name="reconciliation-report",
            generator_version="1.0.0",
            created_by=created_by,
            reconciliation_run_id=run.id,
        )
        run.issues = list(evaluation.issues)
        run.error_count = counts["error"]
        run.warning_count = counts["warning"]
        run.info_count = counts["info"]
        run.report_artifact_ids = [str(artifact.id)]
        run.status = "succeeded"
        run.completed_at = utc_now()
        JobService().complete(job)


def _handle_validation(
    factory: sessionmaker[Session], storage: ObjectStorage, job_id: UUID
) -> None:
    """Recalculate immutable artifact bytes outside the database transaction."""

    with factory.begin() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        run = session.get(ValidationRun, UUID(str(job.payload["run_id"])))
        if run is None:
            JobService().fail(job, {"code": "validation_run_missing"})
            return
        if job.cancellation_requested_at is not None or run.status == "cancelled":
            run.status = "cancelled"
            run.completed_at = utc_now()
            JobService().complete(job)
            return
        artifact = session.get(Artifact, run.owner_id)
        if artifact is None:
            JobService().fail(job, {"code": "artifact_not_found"})
            return
        run.status = "running"
        run.started_at = run.started_at or utc_now()
        object_key, expected_checksum, artifact_id = (
            artifact.object_key,
            artifact.sha256,
            artifact.id,
        )

    digest = hashlib.sha256()
    with storage.open(object_key) as body:
        while chunk := body.read(1024 * 1024):
            digest.update(chunk)
    observed = digest.hexdigest()

    with factory.begin() as session:
        job = session.get(Job, job_id)
        run = session.get(ValidationRun, UUID(str(job.payload["run_id"]))) if job else None
        if job is None or run is None:
            return
        if job.cancellation_requested_at is not None or run.status == "cancelled":
            run.status = "cancelled"
            run.completed_at = utc_now()
            JobService().complete(job)
            return
        issues: list[dict[str, object]] = []
        if observed != expected_checksum:
            issues.append(
                {
                    "id": f"artifact-checksum-{artifact_id}",
                    "code": "artifact_checksum_mismatch",
                    "severity": "error",
                    "message": "Stored artifact bytes do not match immutable metadata.",
                    "suggestion": "Quarantine the object store and restore verified bytes.",
                    "module": run.module_key,
                    "entity_type": "artifact",
                    "entity_id": str(artifact_id),
                    "field_path": "sha256",
                    "dataset": None,
                    "variable": None,
                    "artifact_id": str(artifact_id),
                }
            )
        run.issues = issues
        run.error_count = len(issues)
        run.warning_count = 0
        run.info_count = 0
        run.status = "failed" if issues else "succeeded"
        run.completed_at = utc_now()
        if issues:
            run.failure = {"code": "artifact_integrity_failed"}
            JobService().fail(job, run.failure)
        else:
            JobService().complete(job)


def _handle_submission_package(
    factory: sessionmaker[Session],
    registry: ModuleRegistry,
    storage: ObjectStorage,
    job_id: UUID,
) -> None:
    """Resolve, assemble, upload, and atomically publish one exact package."""

    with factory.begin() as session:
        job = session.get(Job, job_id)
        package = (
            session.get(SubmissionPackage, UUID(str(job.payload["package_id"])))
            if job is not None
            else None
        )
        if job is None or package is None:
            return
        if job.cancellation_requested_at is not None:
            package.status = "cancelled"
            package.completed_at = utc_now()
            JobService().complete(job)
            return
        package.status = "running"
        resolved = resolve_package(
            session,
            registry,
            study_id=package.study_id,
            module_selections=tuple(package.module_selections),
            supporting_artifact_ids=tuple(UUID(value) for value in package.artifact_ids),
            reconciliation_run_ids=tuple(UUID(value) for value in package.reconciliation_run_ids),
        )
        if resolved.fingerprint != package.input_fingerprint:
            raise ProblemException(
                status_code=409,
                code="stale_package_inputs",
                title="Package inputs are stale",
                detail="The exact package selection changed before assembly.",
            )

    built = build_package(resolved, storage)
    stored = store_built_package(storage, built)

    with factory.begin() as session:
        job = session.get(Job, job_id)
        package = (
            session.get(SubmissionPackage, UUID(str(job.payload["package_id"])))
            if job is not None
            else None
        )
        if job is None or package is None:
            return
        if job.cancellation_requested_at is not None:
            package.status = "cancelled"
            package.completed_at = utc_now()
            JobService().complete(job)
            return
        current = resolve_package(
            session,
            registry,
            study_id=package.study_id,
            module_selections=tuple(package.module_selections),
            supporting_artifact_ids=tuple(UUID(value) for value in package.artifact_ids),
            reconciliation_run_ids=tuple(UUID(value) for value in package.reconciliation_run_ids),
        )
        if current.fingerprint != resolved.fingerprint:
            raise ProblemException(
                status_code=409,
                code="stale_package_inputs",
                title="Package inputs are stale",
                detail="The exact package selection changed during assembly.",
            )
        publish_package(session, package, built, stored)
        JobService().complete(job)


def _record_failure(
    factory: sessionmaker[Session], job_id: UUID, failure: dict[str, object]
) -> None:
    with factory.begin() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        JobService().fail(job, failure)
        if job.job_type == "artifact_build":
            build = session.get(ArtifactBuild, UUID(str(job.payload["build_id"])))
            if build is not None and job.status == "failed":
                build.status = "failed"
                build.failure = failure
                build.completed_at = utc_now()
        elif job.job_type == "reconciliation":
            run = session.get(ReconciliationRun, UUID(str(job.payload["run_id"])))
            if run is not None and job.status == "failed":
                run.status = "failed"
                run.failure = failure
                run.completed_at = utc_now()
        elif job.job_type == "validation":
            validation_run = session.get(ValidationRun, UUID(str(job.payload["run_id"])))
            if validation_run is not None and job.status == "failed":
                validation_run.status = "failed"
                validation_run.failure = failure
                validation_run.completed_at = utc_now()
        elif job.job_type == "submission_package":
            package = session.get(SubmissionPackage, UUID(str(job.payload["package_id"])))
            if package is not None and job.status == "failed":
                package.status = "failed"
                package.issues = [
                    {
                        "code": str(failure.get("code", "package_failed")),
                        "severity": "error",
                        "message": str(failure.get("detail", "Package assembly failed.")),
                    }
                ]
                package.completed_at = utc_now()


def _process_job(
    factory: sessionmaker[Session],
    registry: ModuleRegistry,
    storage: ObjectStorage,
    job: Job,
) -> None:
    try:
        if job.job_type == "artifact_build":
            _handle_artifact_build(factory, registry, storage, job.id)
        elif job.job_type == "reconciliation":
            _handle_reconciliation(factory, registry, storage, job.id)
        elif job.job_type == "validation":
            _handle_validation(factory, storage, job.id)
        elif job.job_type == "submission_package":
            _handle_submission_package(factory, registry, storage, job.id)
        else:
            _record_failure(
                factory,
                job.id,
                {
                    "code": "job_handler_not_registered",
                    "detail": f"No handler is registered for '{job.job_type}'.",
                },
            )
    except ProblemException as error:
        _record_failure(factory, job.id, {"code": error.code, "detail": error.detail})
    except Exception as error:  # worker boundary records a typed, non-sensitive failure
        logger.exception("job processing failed", extra={"job_id": str(job.id)})
        _record_failure(
            factory,
            job.id,
            {"code": "job_processing_failed", "detail": type(error).__name__},
        )


def main() -> None:
    """Claim jobs briefly and process registered handlers outside the claim lock."""

    settings: Settings = get_settings()
    factory = create_session_factory(create_database_engine(settings))
    registry = build_module_registry()
    storage = S3ObjectStorage(settings)
    service = JobService()
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    while not _stopping:
        with factory.begin() as session:
            job = service.claim(
                session,
                worker_id="build-worker",
                lease_seconds=settings.job_lease_seconds,
                job_types=(
                    "artifact_build",
                    "reconciliation",
                    "validation",
                    "submission_package",
                ),
            )
        if job is None:
            time.sleep(1)
            continue
        _process_job(factory, registry, storage, job)


if __name__ == "__main__":
    main()
