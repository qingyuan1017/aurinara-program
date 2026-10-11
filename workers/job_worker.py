"""Durable build and reconciliation worker process."""

import hashlib
import logging
import signal
import time
from types import FrameType
from typing import cast
from uuid import UUID, uuid5

from sqlalchemy.exc import IntegrityError
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
from app.raw.contracts import RawDatasetImportEntry, RawPhysicalSnapshot
from app.raw.files import inspect_file
from app.raw.models import RawDatasetImport, RawWorkbench
from app.raw.service import (
    ISSUE_NAMESPACE,
    ResolvedSource,
    apply_bulk_dataset_import,
    resolve_bulk_sources,
)
from app.reconciliation.models import ReconciliationRun
from app.reconciliation.service import ReconciliationCapability
from app.validation.contracts import IssueSeverity, ValidationIssue
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
        package_id = package.id
        study_id = package.study_id

    built = build_package(resolved, storage)
    stored = store_built_package(
        storage,
        built,
        study_id=study_id,
        package_id=package_id,
    )

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


def _import_issue(
    code: str, message: str, raw_id: UUID, *, dataset: str | None = None
) -> ValidationIssue:
    """Build a typed bulk-import issue aligned with Raw issue identity rules."""

    key = f"{raw_id}:{code}:{dataset}:None:None"
    return ValidationIssue(
        id=uuid5(ISSUE_NAMESPACE, key),
        code=code,
        severity=IssueSeverity.ERROR,
        message=message,
        suggestion="Correct the source binding or maintained Raw metadata and revalidate.",
        module="raw",
        entity_type="raw_workbench",
        entity_id=raw_id,
        dataset=dataset,
    )


def _handle_raw_dataset_import(
    factory: sessionmaker[Session],
    registry: ModuleRegistry,
    storage: ObjectStorage,
    settings: Settings,
    job_id: UUID,
) -> None:
    """Validate a JSON-array bulk import outside any transaction, then apply atomically.

    Follows the T1 / untransacted-middle / T2 skeleton: a content rejection is a
    *completed* job (never requeued); only transient infra errors propagate to
    ``_process_job`` and use ``fail()``.
    """

    # T1 (short): claim-time state, terminal/cancel guards, resolve sources.
    with factory.begin() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        record = session.get(RawDatasetImport, UUID(str(job.payload["import_id"])))
        if record is None:
            JobService().fail(job, {"code": "raw_dataset_import_missing"})
            return
        if record.status in {"succeeded", "failed", "cancelled"}:
            JobService().complete(job)
            return
        if job.cancellation_requested_at is not None or record.status == "cancelled":
            record.status = "cancelled"
            record.completed_at = utc_now()
            JobService().complete(job)
            return
        raw = session.get(RawWorkbench, record.raw_id)
        if raw is None:
            record.status = "failed"
            record.failure = {"code": "raw_not_found"}
            record.completed_at = utc_now()
            JobService().complete(job)
            return
        record.status = "running"
        record.started_at = record.started_at or utc_now()
        entries = [RawDatasetImportEntry.model_validate(item) for item in record.entries]
        resolved_sources, issues = resolve_bulk_sources(
            session, study_id=record.study_id, entries=entries
        )
        raw_id = raw.id
        pin = job.payload.get("expected_raw_revision")
        pinned_revision = int(cast(int, pin)) if pin is not None else None

    # Middle (no transaction): size cap, then inspect each distinct file once.
    snapshots: list[RawPhysicalSnapshot | None] = [None] * len(entries)
    if not issues:
        total_bytes = sum(source.size for source in resolved_sources if source is not None)
        if total_bytes > settings.raw_bulk_import_max_total_bytes:
            issues.append(
                _import_issue(
                    "raw_bulk_import_too_large",
                    "The summed size of referenced source files exceeds the import limit.",
                    raw_id,
                )
            )
        else:
            cache: dict[UUID, RawPhysicalSnapshot] = {}
            for index, source in enumerate(resolved_sources):
                if source is None:
                    continue
                snapshot = cache.get(source.id)
                if snapshot is None:
                    snapshot = _inspect_resolved(storage, source, entries[index], raw_id, issues)
                    if snapshot is None:
                        continue
                    cache[source.id] = snapshot
                snapshots[index] = snapshot

    # T2 (short, atomic): re-guard, then fail-with-issues or apply.
    with factory.begin() as session:
        job = session.get(Job, job_id)
        record = session.get(RawDatasetImport, UUID(str(job.payload["import_id"]))) if job else None
        if job is None or record is None:
            return
        if record.status in {"succeeded", "failed", "cancelled"}:
            JobService().complete(job)
            return
        if job.cancellation_requested_at is not None or record.status == "cancelled":
            record.status = "cancelled"
            record.completed_at = utc_now()
            JobService().complete(job)
            return
        raw = session.get(RawWorkbench, record.raw_id)
        if raw is None:
            record.status = "failed"
            record.failure = {"code": "raw_not_found"}
            record.completed_at = utc_now()
            JobService().complete(job)
            return
        if pinned_revision is not None and raw.revision != pinned_revision:
            record.issues = [
                _import_issue(
                    "stale_raw_revision",
                    "The Raw workbench revision moved since the import was requested.",
                    raw.id,
                ).model_dump(mode="json")
            ]
            record.status = "failed"
            record.failure = {"code": "stale_raw_revision"}
            record.completed_at = utc_now()
            JobService().complete(job)
            return
        if issues:
            record.issues = [issue.model_dump(mode="json") for issue in issues]
            record.status = "failed"
            record.failure = {"code": "raw_bulk_import_failed"}
            record.completed_at = utc_now()
            JobService().complete(job)
            return
        try:
            datasets = apply_bulk_dataset_import(
                session,
                registry,
                raw=raw,
                entries=entries,
                resolved_sources=resolved_sources,
                snapshots=snapshots,
                created_by=record.created_by,
            )
            session.flush()
        except IntegrityError:
            session.rollback()
            with factory.begin() as fresh:
                fresh_job = fresh.get(Job, job_id)
                fresh_record = (
                    fresh.get(RawDatasetImport, UUID(str(fresh_job.payload["import_id"])))
                    if fresh_job
                    else None
                )
                if fresh_job is None or fresh_record is None:
                    return
                fresh_record.issues = [
                    _import_issue(
                        "duplicate_raw_dataset_code",
                        "A dataset code already exists in the Raw workbench.",
                        raw_id,
                    ).model_dump(mode="json")
                ]
                fresh_record.status = "failed"
                fresh_record.failure = {"code": "duplicate_raw_dataset_code"}
                fresh_record.completed_at = utc_now()
                JobService().complete(fresh_job)
            return
        record.result_dataset_ids = [str(dataset.id) for dataset in datasets]
        record.files_inspected = len({source.id for source in resolved_sources if source})
        record.status = "succeeded"
        record.completed_at = utc_now()
        JobService().complete(job)


def _inspect_resolved(
    storage: ObjectStorage,
    source: ResolvedSource,
    entry: RawDatasetImportEntry,
    raw_id: UUID,
    issues: list[ValidationIssue],
) -> RawPhysicalSnapshot | None:
    """Verify checksum and inspect one resolved file; record a typed issue on failure."""

    digest = hashlib.sha256()
    with storage.open(source.object_key) as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != source.sha256:
        issues.append(
            _import_issue(
                "raw_source_checksum_mismatch",
                "The bound source bytes do not match their immutable checksum.",
                raw_id,
                dataset=entry.code,
            )
        )
        return None
    try:
        with storage.open(source.object_key) as stream:
            return inspect_file(stream, source.filename)
    except ProblemException as error:
        issues.append(_import_issue(error.code, error.detail, raw_id, dataset=entry.code))
        return None


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
        elif job.job_type == "raw_dataset_import":
            record = session.get(RawDatasetImport, UUID(str(job.payload["import_id"])))
            if record is not None and job.status == "failed":
                record.status = "failed"
                record.failure = failure
                record.completed_at = utc_now()


def _process_job(
    factory: sessionmaker[Session],
    registry: ModuleRegistry,
    storage: ObjectStorage,
    job: Job,
    settings: Settings | None = None,
) -> None:
    resolved_settings = settings or get_settings()
    try:
        if job.job_type == "artifact_build":
            _handle_artifact_build(factory, registry, storage, job.id)
        elif job.job_type == "reconciliation":
            _handle_reconciliation(factory, registry, storage, job.id)
        elif job.job_type == "validation":
            _handle_validation(factory, storage, job.id)
        elif job.job_type == "submission_package":
            _handle_submission_package(factory, registry, storage, job.id)
        elif job.job_type == "raw_dataset_import":
            _handle_raw_dataset_import(factory, registry, storage, resolved_settings, job.id)
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
                    "raw_dataset_import",
                ),
            )
        if job is None:
            time.sleep(1)
            continue
        _process_job(factory, registry, storage, job, settings)


if __name__ == "__main__":
    main()
