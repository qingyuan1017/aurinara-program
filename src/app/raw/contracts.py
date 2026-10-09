"""Strict public contracts for manually maintained Raw metadata."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.validation.contracts import ValidationIssue

# Mirrors ``Settings.raw_bulk_import_max_entries`` so the request contract field
# constraint is a compile-time bound; the settings layer stays the runtime source.
RAW_BULK_IMPORT_MAX_ENTRIES = 500


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawDatasetCreate(StrictModel):
    code: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    source_file_id: UUID


class RawDatasetPatch(StrictModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    source_file_id: UUID | None = None
    status: Literal["active", "retired"] | None = None


class TerminologyBinding(StrictModel):
    terminology_release_id: UUID
    codelist_code: str = Field(min_length=1, max_length=64)
    term_code: str | None = Field(default=None, max_length=128)
    extension_revision_id: UUID | None = None


class RawVariableWrite(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
    label: str | None = Field(default=None, max_length=255)
    physical_type: Literal["string", "integer", "number", "boolean", "date", "datetime"] | None = (
        None
    )
    length: int | None = Field(default=None, ge=1)
    precision: int | None = Field(default=None, ge=0)
    ordinal: int = Field(ge=1)
    role: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    terminology_binding: TerminologyBinding | None = None


class RawVariablePatch(StrictModel):
    label: str | None = Field(default=None, max_length=255)
    physical_type: Literal["string", "integer", "number", "boolean", "date", "datetime"] | None = (
        None
    )
    length: int | None = Field(default=None, ge=1)
    precision: int | None = Field(default=None, ge=0)
    ordinal: int | None = Field(default=None, ge=1)
    role: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    terminology_binding: TerminologyBinding | None = None


class RawPreviewRequest(StrictModel):
    columns: tuple[str, ...] = ()
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=200)

    @model_validator(mode="after")
    def unique_columns(self) -> "RawPreviewRequest":
        if len(self.columns) != len(set(self.columns)):
            raise ValueError("preview columns must be unique")
        return self


class RawPhysicalColumn(StrictModel):
    name: str
    physical_type: str
    length: int | None = None
    precision: int | None = None
    ordinal: int


class RawPhysicalSnapshot(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    columns: tuple[RawPhysicalColumn, ...]
    row_count: int


class RawDatasetImportEntry(StrictModel):
    """One dataset to create and bind in a bulk import request."""

    code: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    source_file_id: UUID
    initialize_variables: bool = False


class RawDatasetImportRequest(StrictModel):
    """Versioned JSON-array envelope for an asynchronous bulk dataset import."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    expected_raw_revision: int | None = Field(default=None, ge=1)
    entries: tuple[RawDatasetImportEntry, ...] = Field(
        min_length=1, max_length=RAW_BULK_IMPORT_MAX_ENTRIES
    )

    @model_validator(mode="after")
    def unique_codes(self) -> "RawDatasetImportRequest":
        codes = [entry.code for entry in self.entries]
        if len(codes) != len(set(codes)):
            raise ValueError("entry codes must be unique within a bulk import")
        return self


ImportStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class RawDatasetImportResponse(BaseModel):
    """Addressable status resource for an asynchronous bulk dataset import."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    raw_id: UUID
    study_id: UUID
    status: ImportStatus
    schema_version: str
    entry_count: int
    files_inspected: int
    input_fingerprint: str
    result_dataset_ids: list[UUID]
    issues: list[ValidationIssue]
    failure: dict[str, object] | None
    started_at: datetime | None
    completed_at: datetime | None
    created_by: str
    created_at: datetime

    @field_validator("issues", mode="before")
    @classmethod
    def _validate_issues(cls, value: object) -> object:
        """Rehydrate stored JSONB issue dicts into typed ``ValidationIssue`` models."""

        if isinstance(value, list):
            return [
                ValidationIssue.model_validate(item) if isinstance(item, dict) else item
                for item in value
            ]
        return value
