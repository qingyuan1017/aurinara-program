"""Common immutable validation issue contracts."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IssueSeverity(StrEnum):
    """Stable issue severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(BaseModel):
    """Machine-readable issue shared by validation and reconciliation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    code: str
    severity: IssueSeverity
    message: str
    suggestion: str | None = None
    module: str
    entity_type: str
    entity_id: UUID | None = None
    field_path: str | None = None
    dataset: str | None = None
    variable: str | None = None
    artifact_id: UUID | None = None
