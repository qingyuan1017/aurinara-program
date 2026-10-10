"""Source-file and artifact transport contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.artifacts.models import Artifact


class ArtifactResponse(BaseModel):
    """Public artifact metadata without an object-store locator."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    study_id: UUID
    module: str
    artifact_type: str
    owner_type: str
    owner_id: UUID
    filename: str
    media_type: str
    sha256: str
    size: int
    input_fingerprint: str
    dependency_selection_revision: int | None
    dependency_fingerprint: str | None
    input_selection_revision: int | None
    source_specification_revision: int | None
    source_specification_fingerprint: str | None
    source_plan_type: str | None
    source_plan_revision: int | None
    compiler_fingerprint: str | None
    generator_name: str
    generator_version: str
    status: str
    validation_run_id: UUID | None
    reconciliation_run_id: UUID | None
    execution_run_id: UUID | None
    created_by: str
    created_at: datetime

    @classmethod
    def from_record(cls, record: Artifact) -> "ArtifactResponse":
        """Translate the internal module-key column to the public field."""

        return cls(
            id=record.id,
            study_id=record.study_id,
            module=record.module_key,
            artifact_type=record.artifact_type,
            owner_type=record.owner_type,
            owner_id=record.owner_id,
            filename=record.filename,
            media_type=record.media_type,
            sha256=record.sha256,
            size=record.size,
            input_fingerprint=record.input_fingerprint,
            dependency_selection_revision=record.dependency_selection_revision,
            dependency_fingerprint=record.dependency_fingerprint,
            input_selection_revision=record.input_selection_revision,
            source_specification_revision=record.source_specification_revision,
            source_specification_fingerprint=record.source_specification_fingerprint,
            source_plan_type=record.source_plan_type,
            source_plan_revision=record.source_plan_revision,
            compiler_fingerprint=record.compiler_fingerprint,
            generator_name=record.generator_name,
            generator_version=record.generator_version,
            status=record.status,
            validation_run_id=record.validation_run_id,
            reconciliation_run_id=record.reconciliation_run_id,
            execution_run_id=record.execution_run_id,
            created_by=record.created_by,
            created_at=record.created_at,
        )


class SourceFileResponse(BaseModel):
    """Immutable source-file metadata."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    study_id: UUID
    artifact_id: UUID
    filename: str
    media_type: str
    sha256: str
    size: int
    created_by: str
    created_at: datetime


class SourceFileCollection(BaseModel):
    """Source-file collection."""

    items: tuple[SourceFileResponse, ...]
    next_cursor: str | None = None


class SourceFileBulkResponse(BaseModel):
    """Atomic bulk-upload result: one source file per request part, in order."""

    items: tuple[SourceFileResponse, ...]


class ArtifactCollection(BaseModel):
    """Artifact collection."""

    items: tuple[ArtifactResponse, ...]
    next_cursor: str | None = None
