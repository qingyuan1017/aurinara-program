"""Exact-input deterministic submission-package assembly."""

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.artifacts.service import ArtifactService, StoredObject, store_bytes_object
from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.execution.models import ExecutionRun
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry
from app.packaging.contracts import PackageContributionCapability
from app.packaging.models import SubmissionPackage
from app.packaging.paths import normalized_archive_path
from app.reconciliation.models import ReconciliationRun
from app.studies.models import Study
from app.validation.models import ValidationRun


@dataclass(frozen=True, slots=True)
class ResolvedPackageFile:
    artifact_id: UUID
    archive_path: str
    object_key: str
    expected_sha256: str
    size: int
    media_type: str
    module_key: str
    artifact_type: str


@dataclass(frozen=True, slots=True)
class ResolvedPackage:
    fingerprint: str
    public_manifest: dict[str, object]
    files: tuple[ResolvedPackageFile, ...]


@dataclass(frozen=True, slots=True)
class BuiltPackage:
    zip_bytes: bytes
    report_bytes: bytes
    manifest: dict[str, object]
    issues: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class StoredPackage:
    report: StoredObject
    archive: StoredObject | None


def resolve_package(
    session: Session,
    registry: ModuleRegistry,
    *,
    study_id: UUID,
    module_selections: tuple[dict[str, object], ...],
    supporting_artifact_ids: tuple[UUID, ...],
    reconciliation_run_ids: tuple[UUID, ...],
) -> ResolvedPackage:
    """Resolve package policy through typed registered module contributors."""

    study = session.get(Study, study_id)
    if study is None:
        raise ProblemException(
            status_code=404,
            code="study_not_found",
            title="Study not found",
            detail="The study does not exist.",
        )
    modules = [str(item.get("module", "")) for item in module_selections]
    if len(modules) != len(set(modules)):
        raise _invalid("package_module_duplicate", "Each package module may be selected once.")
    seen_artifacts: set[UUID] = set()
    contributions: list[tuple[Artifact, str]] = []
    normalized_modules: list[dict[str, object]] = []
    for selection in module_selections:
        if set(selection) != {"module", "artifact_ids", "options"}:
            raise _invalid(
                "package_module_selection_invalid",
                "Module selections use only module, artifact_ids, and options.",
            )
        module_key = str(selection["module"])
        descriptor = registry.get(module_key)
        if descriptor is None or ModuleCapability.PACKAGING not in descriptor.capabilities:
            raise _invalid(
                "package_module_unsupported",
                f"Module '{module_key}' has no package-contribution capability.",
            )
        raw_ids = selection["artifact_ids"]
        options = selection["options"]
        if not isinstance(raw_ids, list) or not raw_ids or not isinstance(options, dict):
            raise _invalid(
                "package_module_selection_invalid",
                "Each module requires non-empty artifact_ids and a closed options object.",
            )
        try:
            artifact_ids = tuple(UUID(str(value)) for value in raw_ids)
        except ValueError as error:
            raise _invalid("package_artifact_id_invalid", "An artifact ID is malformed.") from error
        if len(artifact_ids) != len(set(artifact_ids)) or seen_artifacts.intersection(artifact_ids):
            raise _invalid(
                "package_artifact_duplicate", "Package artifact IDs must be globally unique."
            )
        seen_artifacts.update(artifact_ids)
        artifacts = tuple(_artifact(session, study_id, artifact_id) for artifact_id in artifact_ids)
        handler = cast(
            PackageContributionCapability,
            registry.require_handler(module_key, ModuleCapability.PACKAGING),
        )
        module_contributions = handler.package_contributions(
            session, study_id, artifacts, cast(dict[str, object], options)
        )
        if {item.artifact_id for item in module_contributions} != set(artifact_ids):
            raise RuntimeError("module package contributor did not account for exact artifacts")
        by_id = {artifact.id: artifact for artifact in artifacts}
        contributions.extend(
            (by_id[item.artifact_id], item.archive_path) for item in module_contributions
        )
        normalized_modules.append(
            {
                "module": module_key,
                "artifact_ids": [str(value) for value in artifact_ids],
                "options": options,
            }
        )
    if len(supporting_artifact_ids) != len(
        set(supporting_artifact_ids)
    ) or seen_artifacts.intersection(supporting_artifact_ids):
        raise _invalid(
            "package_artifact_duplicate", "Package artifact IDs must be globally unique."
        )
    seen_artifacts.update(supporting_artifact_ids)
    for artifact_id in supporting_artifact_ids:
        artifact = _artifact(session, study_id, artifact_id)
        owner_descriptor = registry.get(artifact.module_key)
        if (
            owner_descriptor is not None
            and ModuleCapability.PACKAGING in owner_descriptor.capabilities
        ):
            raise _invalid(
                "package_module_selection_required",
                "Clinical artifacts must be supplied through their module selection.",
            )
        contributions.append(
            (
                artifact,
                f"supporting/{artifact.module_key}/{artifact.artifact_type}/{artifact.artifact_type}"
                f"{_safe_suffix(artifact.filename)}",
            )
        )
    reconciliations: list[dict[str, object]] = []
    for run_id in reconciliation_run_ids:
        run = session.get(ReconciliationRun, run_id)
        if (
            run is None
            or run.study_id != study_id
            or run.status != "succeeded"
            or run.error_count != 0
        ):
            raise _invalid(
                "package_reconciliation_invalid",
                "Every selected reconciliation must be completed without errors.",
            )
        referenced = {
            UUID(str(item["artifact_id"]))
            for item in run.inputs
            if item.get("artifact_id") is not None
        }
        if not referenced.issubset(seen_artifacts):
            raise _invalid(
                "package_reconciliation_inputs_mismatch",
                "Reconciliation artifact inputs must be part of the exact package selection.",
            )
        reconciliations.append(
            {
                "id": str(run.id),
                "type": run.reconciliation_type,
                "input_fingerprint": run.input_fingerprint,
            }
        )
    files: list[ResolvedPackageFile] = []
    collision_keys: set[str] = set()
    manifest_entries: list[dict[str, object]] = []
    for artifact, proposed_path in contributions:
        path, collision_key = _archive_path(proposed_path)
        if collision_key in collision_keys:
            raise _invalid(
                "package_path_duplicate",
                "Selected artifacts produce duplicate case-insensitive or "
                "Unicode-normalized paths.",
            )
        collision_keys.add(collision_key)
        _validate_evidence(session, study_id, artifact, reconciliation_run_ids)
        _validate_artifact_references(session, study_id, artifact)
        files.append(
            ResolvedPackageFile(
                artifact_id=artifact.id,
                archive_path=path,
                object_key=artifact.object_key,
                expected_sha256=artifact.sha256,
                size=artifact.size,
                media_type=artifact.media_type,
                module_key=artifact.module_key,
                artifact_type=artifact.artifact_type,
            )
        )
        manifest_entries.append(
            {
                "artifact_id": str(artifact.id),
                "module": artifact.module_key,
                "artifact_type": artifact.artifact_type,
                "path": path,
                "sha256": artifact.sha256,
                "size": artifact.size,
                "media_type": artifact.media_type,
                "input_fingerprint": artifact.input_fingerprint,
                "dependency_fingerprint": artifact.dependency_fingerprint,
                "validation_run_id": (
                    str(artifact.validation_run_id) if artifact.validation_run_id else None
                ),
                "reconciliation_run_id": (
                    str(artifact.reconciliation_run_id) if artifact.reconciliation_run_id else None
                ),
                "execution_run_id": (
                    str(artifact.execution_run_id) if artifact.execution_run_id else None
                ),
            }
        )
    manifest: dict[str, object] = {
        "schema_version": "1.0.0",
        "study": {"id": str(study.id), "revision": study.revision},
        "module_selections": normalized_modules,
        "supporting_artifact_ids": [str(value) for value in supporting_artifact_ids],
        "reconciliations": sorted(reconciliations, key=lambda item: str(item["id"])),
        "entries": sorted(manifest_entries, key=lambda item: str(item["path"])),
    }
    return ResolvedPackage(
        fingerprint=fingerprint(manifest),
        public_manifest=manifest,
        files=tuple(sorted(files, key=lambda item: item.archive_path)),
    )


def build_package(resolved: ResolvedPackage, storage: ObjectStorage) -> BuiltPackage:
    """Recalculate checksums, then create byte-for-byte deterministic ZIP evidence."""

    content: list[tuple[str, bytes, str]] = []
    issues: list[dict[str, object]] = []
    for item in resolved.files:
        with storage.open(item.object_key) as body:
            data = body.read()
        observed = hashlib.sha256(data).hexdigest()
        if observed != item.expected_sha256 or len(data) != item.size:
            issues.append(
                {
                    "code": "package_artifact_checksum_mismatch",
                    "severity": "error",
                    "artifact_id": str(item.artifact_id),
                    "path": item.archive_path,
                    "expected_sha256": item.expected_sha256,
                    "observed_sha256": observed,
                }
            )
        content.append((item.archive_path, data, observed))
    report = {
        "schema_version": "1.0.0",
        "input_fingerprint": resolved.fingerprint,
        "counts": {
            "error": sum(1 for issue in issues if issue["severity"] == "error"),
            "warning": 0,
            "info": 0,
        },
        "issues": issues,
    }
    report_bytes = _canonical_bytes(report)
    if issues:
        return BuiltPackage(b"", report_bytes, resolved.public_manifest, tuple(issues))
    manifest_bytes = _canonical_bytes(resolved.public_manifest)
    checksums = [f"{digest}  {path}" for path, _, digest in content]
    checksums.append(f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json")
    checksums.append(f"{hashlib.sha256(report_bytes).hexdigest()}  package-validation-report.json")
    checksum_bytes = ("\n".join(sorted(checksums)) + "\n").encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, data, _ in sorted(content):
            _write_zip_entry(archive, path, data)
        _write_zip_entry(archive, "manifest.json", manifest_bytes)
        _write_zip_entry(archive, "package-validation-report.json", report_bytes)
        _write_zip_entry(archive, "checksums.sha256", checksum_bytes)
    return BuiltPackage(buffer.getvalue(), report_bytes, resolved.public_manifest, ())


def publish_package(
    session: Session,
    package: SubmissionPackage,
    built: BuiltPackage,
    stored: StoredPackage,
) -> SubmissionPackage:
    """Publish package report and, only on success, the deterministic ZIP artifact."""

    artifact_service = ArtifactService()
    report = artifact_service.record_artifact(
        session,
        stored=stored.report,
        study_id=package.study_id,
        module_key="packaging",
        artifact_type="submission_package_validation_report",
        owner_type="submission_package",
        owner_id=package.id,
        filename="package-validation-report.json",
        media_type="application/json",
        manifest={
            "schema_version": "1.0.0",
            "package_id": str(package.id),
            "input_fingerprint": package.input_fingerprint,
            "issues": list(built.issues),
        },
        input_fingerprint=package.input_fingerprint,
        dependency_selection_revision=None,
        dependency_fingerprint=None,
        generator_name="submission-package-validator",
        generator_version="1.0.0",
        created_by=package.created_by,
    )
    package.report_artifact_id = report.id
    package.issues = list(built.issues)
    package.manifest = built.manifest
    package.completed_at = utc_now()
    if built.issues:
        package.status = "failed"
        return package
    if stored.archive is None:
        raise RuntimeError("successful package bytes were not stored")
    archive = artifact_service.record_artifact(
        session,
        stored=stored.archive,
        study_id=package.study_id,
        module_key="packaging",
        artifact_type="submission_package_zip",
        owner_type="submission_package",
        owner_id=package.id,
        filename="submission-package.zip",
        media_type="application/zip",
        manifest=built.manifest,
        input_fingerprint=package.input_fingerprint,
        dependency_selection_revision=None,
        dependency_fingerprint=None,
        generator_name="submission-package-builder",
        generator_version="1.0.0",
        created_by=package.created_by,
    )
    package.zip_artifact_id = archive.id
    package.status = "succeeded"
    return package


def store_built_package(storage: ObjectStorage, built: BuiltPackage) -> StoredPackage:
    """Upload verified terminal bytes without holding a database transaction."""

    report = store_bytes_object(storage, built.report_bytes, "application/json")
    archive = (
        None if built.issues else store_bytes_object(storage, built.zip_bytes, "application/zip")
    )
    return StoredPackage(report=report, archive=archive)


def _artifact(session: Session, study_id: UUID, artifact_id: UUID) -> Artifact:
    artifact = session.get(Artifact, artifact_id)
    if artifact is None or artifact.study_id != study_id or artifact.status != "available":
        raise _invalid(
            "package_artifact_invalid",
            "Every selected artifact must be available and belong to the selected study.",
        )
    return artifact


def _validate_evidence(
    session: Session,
    study_id: UUID,
    artifact: Artifact,
    reconciliation_run_ids: tuple[UUID, ...],
) -> None:
    if artifact.validation_run_id is not None:
        validation = session.get(ValidationRun, artifact.validation_run_id)
        if (
            validation is None
            or validation.study_id != study_id
            or validation.status != "succeeded"
            or validation.error_count != 0
        ):
            raise _invalid(
                "package_validation_invalid",
                "A selected artifact is not backed by successful zero-error validation.",
            )
    if (
        artifact.reconciliation_run_id is not None
        and artifact.reconciliation_run_id not in reconciliation_run_ids
    ):
        raise _invalid(
            "package_reconciliation_required",
            "Select the completed reconciliation bound to every reconciled artifact.",
        )
    if artifact.execution_run_id is not None:
        execution = session.get(ExecutionRun, artifact.execution_run_id)
        if execution is None or execution.study_id != study_id or execution.status != "succeeded":
            raise _invalid(
                "package_execution_invalid",
                "A selected execution output is not backed by a successful exact run.",
            )


def _validate_artifact_references(
    session: Session, study_id: UUID, artifact: Artifact
) -> None:
    """Resolve standard frozen provenance references without module-name dispatch."""

    references: list[tuple[UUID, str | None]] = []

    def collect(items: object) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            identity = item.get("artifact_id", item.get("id"))
            if identity is None:
                continue
            try:
                artifact_id = UUID(str(identity))
            except ValueError as error:
                raise _invalid(
                    "package_provenance_invalid",
                    "A frozen artifact provenance identity is malformed.",
                ) from error
            checksum = item.get("checksum", item.get("sha256"))
            references.append((artifact_id, str(checksum) if checksum is not None else None))

    collect(artifact.manifest.get("inputs"))
    collect(artifact.manifest.get("output_artifacts"))
    result = artifact.manifest.get("result")
    if isinstance(result, dict):
        collect([result])
    selection = artifact.manifest.get("input_selection")
    payload = selection.get("payload") if isinstance(selection, dict) else None
    if isinstance(payload, dict):
        collect(payload.get("source_artifacts"))
        collect(payload.get("xpt_artifacts"))
    for referenced_id, checksum in references:
        referenced = session.get(Artifact, referenced_id)
        if (
            referenced is None
            or referenced.study_id != study_id
            or referenced.status != "available"
            or (checksum is not None and referenced.sha256 != checksum)
        ):
            raise _invalid(
                "package_provenance_unavailable",
                "A frozen upstream, result, or reconciliation artifact is unavailable or changed.",
            )


def _safe_suffix(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return f".{suffix}" if suffix.isalnum() and len(suffix) <= 10 else ""


def _archive_path(value: str) -> tuple[str, str]:
    try:
        return normalized_archive_path(value)
    except ValueError as error:
        raise _invalid("package_path_invalid", str(error)) from error


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _write_zip_entry(archive: zipfile.ZipFile, path: str, data: bytes) -> None:
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    archive.writestr(info, data)


def _invalid(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=422,
        code=code,
        title="Submission package selection is invalid",
        detail=detail,
    )
