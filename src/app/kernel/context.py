"""Typed immutable context DTOs shared across module capability boundaries."""

from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentContentContext(BaseModel):
    """Exact accepted document content exposed without repository access."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    content_id: UUID
    document_type: str
    document_revision: int
    content_revision: int
    fingerprint: str
    content: dict[str, object]


class DocumentContextExporter(Protocol):
    """Capability contract for resolving exact document evidence."""

    def content_context(
        self,
        session: Any,
        study_id: UUID,
        content_id: UUID,
        *,
        expected_document_type: str | None = None,
        expected_fingerprint: str | None = None,
    ) -> DocumentContentContext | None: ...
