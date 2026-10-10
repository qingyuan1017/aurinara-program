"""Immutable upload, artifact lookup, and staleness services."""

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal
from app.artifacts.models import Artifact, SourceFile
from app.artifacts.storage import ObjectStorage, checksum_object_key
from app.common.problems import ProblemException
from app.config import Settings
from app.studies.service import StudyService


@dataclass(frozen=True, slots=True)
class StoredJsonObject:
    """Verified immutable object uploaded before metadata publication."""

    object_key: str
    sha256: str
    size: int


StoredObject = StoredJsonObject


class ArtifactService:
    """Own immutable artifact metadata and authorized byte access."""

    def __init__(self) -> None:
        self._studies = StudyService()

    async def create_source_file(
        self,
        session: Session,
        storage: ObjectStorage,
        settings: Settings,
        study_id: UUID,
        upload: UploadFile,
        principal: Principal,
    ) -> SourceFile:
        """Stream, validate, checksum, upload, and commit one immutable source file."""

        self._studies.require_access(session, study_id, principal)
        allowed = frozenset(settings.source_file_allowed_media_types.split(","))
        filename, media_type = _validate_upload_metadata(upload, allowed)
        stored = await _stream_upload(upload, storage, settings, media_type)
        artifact, source_file = _build_source_file_rows(
            study_id=study_id,
            filename=filename,
            media_type=media_type,
            stored=stored,
            created_by=principal.subject,
        )
        session.add_all((artifact, source_file))
        session.commit()
        return source_file

    async def create_source_files_bulk(
        self,
        session: Session,
        storage: ObjectStorage,
        settings: Settings,
        study_id: UUID,
        uploads: list[UploadFile],
        principal: Principal,
    ) -> list[SourceFile]:
        """Stream, validate, and atomically commit many immutable source files.

        The whole request is all-or-nothing: every part's filename and media type is
        validated before any byte is streamed, each part is streamed to its own temp
        file one at a time (at most one temp file on disk at a moment), and the staged
        metadata rows are committed exactly once.
        """

        self._studies.require_access(session, study_id, principal)
        if not uploads:
            raise ProblemException(
                status_code=422,
                code="raw_bulk_upload_empty",
                title="No files to upload",
                detail="The bulk upload request must include at least one file part.",
            )
        if len(uploads) > settings.raw_bulk_upload_max_files:
            raise ProblemException(
                status_code=413,
                code="raw_bulk_upload_too_many",
                title="Too many files",
                detail=(
                    "The bulk upload request exceeds the configured "
                    f"maximum of {settings.raw_bulk_upload_max_files} files."
                ),
            )

        allowed = frozenset(settings.source_file_allowed_media_types.split(","))
        # Metadata pass: validate every part before streaming any bytes.
        validated = [_validate_upload_metadata(upload, allowed) for upload in uploads]

        # Upload pass: stream strictly one part at a time; at most one temp file exists.
        staged: list[tuple[Artifact, SourceFile]] = []
        source_files: list[SourceFile] = []
        for upload, (filename, media_type) in zip(uploads, validated, strict=True):
            stored = await _stream_upload(upload, storage, settings, media_type)
            artifact, source_file = _build_source_file_rows(
                study_id=study_id,
                filename=filename,
                media_type=media_type,
                stored=stored,
                created_by=principal.subject,
            )
            staged.append((artifact, source_file))
            source_files.append(source_file)

        for artifact, source_file in staged:
            session.add_all((artifact, source_file))
        session.commit()
        return source_files

    def list_source_files(
        self, session: Session, study_id: UUID, principal: Principal
    ) -> tuple[SourceFile, ...]:
        """List immutable uploads in stable newest-first order."""

        self._studies.require_access(session, study_id, principal)
        statement = (
            select(SourceFile)
            .where(SourceFile.study_id == study_id)
            .order_by(SourceFile.created_at.desc(), SourceFile.id.desc())
        )
        return tuple(session.scalars(statement))

    def require_source_file(
        self, session: Session, source_file_id: UUID, principal: Principal
    ) -> SourceFile:
        """Resolve an upload after enforcing its study boundary."""

        source_file = session.get(SourceFile, source_file_id)
        if source_file is None:
            raise _not_found("source_file_not_found", "Source file not found")
        self._studies.require_access(session, source_file.study_id, principal)
        return source_file

    def require_artifact(
        self, session: Session, artifact_id: UUID, principal: Principal
    ) -> Artifact:
        """Resolve an artifact after enforcing its study boundary."""

        artifact = session.get(Artifact, artifact_id)
        if artifact is None:
            raise _not_found("artifact_not_found", "Artifact not found")
        self._studies.require_access(session, artifact.study_id, principal)
        return artifact

    def list_artifacts(
        self, session: Session, study_id: UUID, principal: Principal
    ) -> tuple[Artifact, ...]:
        """List study artifacts in stable newest-first order."""

        self._studies.require_access(session, study_id, principal)
        statement = (
            select(Artifact)
            .where(Artifact.study_id == study_id)
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
        return tuple(session.scalars(statement))

    def mark_owner_stale(
        self,
        session: Session,
        *,
        owner_type: str,
        owner_id: UUID,
        artifact_types: tuple[str, ...] | None = None,
    ) -> int:
        """Mark available artifacts stale without deleting immutable evidence."""

        statement = select(Artifact).where(
            Artifact.owner_type == owner_type,
            Artifact.owner_id == owner_id,
            Artifact.status == "available",
        )
        if artifact_types is not None:
            statement = statement.where(Artifact.artifact_type.in_(artifact_types))
        records = tuple(session.scalars(statement))
        for record in records:
            record.status = "stale"
        return len(records)

    def publish_json_artifact(
        self,
        session: Session,
        storage: ObjectStorage,
        *,
        study_id: UUID,
        module_key: str,
        artifact_type: str,
        owner_type: str,
        owner_id: UUID,
        payload: dict[str, object],
        input_fingerprint: str,
        dependency_selection_revision: int | None,
        dependency_fingerprint: str | None,
        generator_name: str,
        generator_version: str,
        created_by: str,
        reconciliation_run_id: UUID | None = None,
    ) -> Artifact:
        """Canonicalize, checksum, upload, and register one immutable JSON artifact."""

        stored = store_json_object(storage, payload)
        return self.record_json_artifact(
            session,
            stored=stored,
            study_id=study_id,
            module_key=module_key,
            artifact_type=artifact_type,
            owner_type=owner_type,
            owner_id=owner_id,
            payload=payload,
            input_fingerprint=input_fingerprint,
            dependency_selection_revision=dependency_selection_revision,
            dependency_fingerprint=dependency_fingerprint,
            generator_name=generator_name,
            generator_version=generator_version,
            created_by=created_by,
            reconciliation_run_id=reconciliation_run_id,
        )

    def record_json_artifact(
        self,
        session: Session,
        *,
        stored: StoredJsonObject,
        study_id: UUID,
        module_key: str,
        artifact_type: str,
        owner_type: str,
        owner_id: UUID,
        payload: dict[str, object],
        input_fingerprint: str,
        dependency_selection_revision: int | None,
        dependency_fingerprint: str | None,
        generator_name: str,
        generator_version: str,
        created_by: str,
        reconciliation_run_id: UUID | None = None,
    ) -> Artifact:
        """Publish metadata for bytes that were already uploaded and verified."""

        return self.record_artifact(
            session,
            stored=stored,
            study_id=study_id,
            module_key=module_key,
            artifact_type=artifact_type,
            owner_type=owner_type,
            owner_id=owner_id,
            filename=f"{artifact_type}.json",
            media_type="application/json",
            manifest=payload,
            input_fingerprint=input_fingerprint,
            dependency_selection_revision=dependency_selection_revision,
            dependency_fingerprint=dependency_fingerprint,
            generator_name=generator_name,
            generator_version=generator_version,
            created_by=created_by,
            reconciliation_run_id=reconciliation_run_id,
        )

    def record_artifact(
        self,
        session: Session,
        *,
        stored: StoredObject,
        study_id: UUID,
        module_key: str,
        artifact_type: str,
        owner_type: str,
        owner_id: UUID,
        filename: str,
        media_type: str,
        manifest: dict[str, object],
        input_fingerprint: str,
        dependency_selection_revision: int | None,
        dependency_fingerprint: str | None,
        generator_name: str,
        generator_version: str,
        created_by: str,
        validation_run_id: UUID | None = None,
        reconciliation_run_id: UUID | None = None,
        execution_run_id: UUID | None = None,
        input_selection_revision: int | None = None,
        source_specification_revision: int | None = None,
        source_specification_fingerprint: str | None = None,
        source_plan_type: str | None = None,
        source_plan_revision: int | None = None,
        compiler_fingerprint: str | None = None,
    ) -> Artifact:
        """Publish metadata for arbitrary verified immutable bytes."""

        artifact = Artifact(
            study_id=study_id,
            module_key=module_key,
            artifact_type=artifact_type,
            owner_type=owner_type,
            owner_id=owner_id,
            filename=filename,
            media_type=media_type,
            object_key=stored.object_key,
            sha256=stored.sha256,
            size=stored.size,
            input_fingerprint=input_fingerprint,
            dependency_selection_revision=dependency_selection_revision,
            dependency_fingerprint=dependency_fingerprint,
            input_selection_revision=input_selection_revision,
            source_specification_revision=source_specification_revision,
            source_specification_fingerprint=source_specification_fingerprint,
            source_plan_type=source_plan_type,
            source_plan_revision=source_plan_revision,
            compiler_fingerprint=compiler_fingerprint,
            manifest=manifest,
            generator_name=generator_name,
            generator_version=generator_version,
            validation_run_id=validation_run_id,
            reconciliation_run_id=reconciliation_run_id,
            execution_run_id=execution_run_id,
            created_by=created_by,
        )
        session.add(artifact)
        session.flush()
        return artifact


def store_json_object(storage: ObjectStorage, payload: dict[str, object]) -> StoredJsonObject:
    """Canonicalize and upload JSON without holding a database transaction."""

    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return store_bytes_object(storage, data, "application/json")


def store_bytes_object(storage: ObjectStorage, data: bytes, media_type: str) -> StoredObject:
    """Upload verified immutable bytes without holding a database transaction."""

    sha256 = hashlib.sha256(data).hexdigest()
    object_key = checksum_object_key(sha256)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(data)
        storage.put_file(object_key, temporary_path, media_type)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return StoredJsonObject(object_key=object_key, sha256=sha256, size=len(data))


def _validate_upload_metadata(
    upload: UploadFile, allowed_media_types: frozenset[str]
) -> tuple[str, str]:
    """Validate the display filename and media type before any bytes are streamed."""

    filename = _safe_display_filename(upload.filename)
    media_type = upload.content_type or "application/octet-stream"
    if media_type not in allowed_media_types:
        raise ProblemException(
            status_code=415,
            code="unsupported_media_type",
            title="Unsupported source-file media type",
            detail=f"Media type '{media_type}' is not allowed.",
        )
    return filename, media_type


async def _stream_upload(
    upload: UploadFile,
    storage: ObjectStorage,
    settings: Settings,
    media_type: str,
) -> StoredObject:
    """Stream one upload to a temp file, checksum, and publish its immutable bytes."""

    digest = hashlib.sha256()
    size = 0
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as temporary:
            temporary_path = Path(temporary.name)
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > settings.source_file_max_bytes:
                    raise ProblemException(
                        status_code=413,
                        code="source_file_too_large",
                        title="Source file is too large",
                        detail="The upload exceeds the configured byte limit.",
                    )
                digest.update(chunk)
                temporary.write(chunk)
        sha256 = digest.hexdigest()
        object_key = checksum_object_key(sha256)
        storage.put_file(object_key, temporary_path, media_type)
    finally:
        await upload.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return StoredJsonObject(object_key=object_key, sha256=sha256, size=size)


def _build_source_file_rows(
    *,
    study_id: UUID,
    filename: str,
    media_type: str,
    stored: StoredObject,
    created_by: str,
) -> tuple[Artifact, SourceFile]:
    """Build the immutable Artifact + SourceFile metadata rows for a stored upload."""

    artifact_id = uuid4()
    source_file_id = uuid4()
    artifact = Artifact(
        id=artifact_id,
        study_id=study_id,
        module_key="raw",
        artifact_type="source_file",
        owner_type="source_file",
        owner_id=source_file_id,
        filename=filename,
        media_type=media_type,
        object_key=stored.object_key,
        sha256=stored.sha256,
        size=stored.size,
        input_fingerprint=stored.sha256,
        manifest={"schema_version": "1.0.0", "source": "upload"},
        generator_name="source-file-upload",
        generator_version="1.0.0",
        created_by=created_by,
    )
    source_file = SourceFile(
        id=source_file_id,
        study_id=study_id,
        artifact_id=artifact_id,
        filename=filename,
        media_type=media_type,
        object_key=stored.object_key,
        sha256=stored.sha256,
        size=stored.size,
        created_by=created_by,
    )
    return artifact, source_file


def _safe_display_filename(value: str | None) -> str:
    if value is None or not value.strip():
        raise ProblemException(
            status_code=422,
            code="filename_required",
            title="A filename is required",
            detail="The upload must include a display filename.",
        )
    filename = PurePath(value).name
    unsafe_characters = {'"', "\\", "\r", "\n", "\x00"}
    if (
        filename != value
        or filename in {".", ".."}
        or any(character in filename for character in unsafe_characters)
    ):
        raise ProblemException(
            status_code=422,
            code="invalid_filename",
            title="Invalid filename",
            detail="The filename contains a path or unsafe characters.",
        )
    return filename


def _not_found(code: str, title: str) -> ProblemException:
    return ProblemException(status_code=404, code=code, title=title, detail=title)
