"""Strict public contracts for manually maintained Raw metadata."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
