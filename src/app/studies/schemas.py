"""Study transport contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StudyCreate(BaseModel):
    """Create one study and owner membership."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    name: str = Field(min_length=1, max_length=255)


class StudyPatch(BaseModel):
    """Product-owned study lifecycle metadata."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "closed"] | None = None


class StudyResponse(BaseModel):
    """Public study representation."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    code: str
    name: str
    sponsor: str | None
    status: str
    revision: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class StudyCollection(BaseModel):
    """Study collection visible to a principal."""

    items: tuple[StudyResponse, ...]
    next_cursor: str | None = None
