"""Opaque stable cursor pagination primitives."""

import base64
import json
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.common.canonical import canonical_json, fingerprint
from app.common.problems import ProblemException


class CursorRecord(Protocol):
    id: UUID
    created_at: datetime


def paginate[RecordT: CursorRecord](
    records: tuple[RecordT, ...],
    *,
    limit: int,
    after: str | None,
    filters: dict[str, object],
) -> tuple[tuple[RecordT, ...], str | None]:
    """Page newest-first records and bind a cursor to the active filters."""

    filtered = records
    if after is not None:
        cursor = _decode(after)
        if cursor.get("filters") != fingerprint(filters):
            raise _invalid_cursor("The cursor cannot be reused with different filters.")
        try:
            created_at = datetime.fromisoformat(str(cursor["created_at"]))
            identifier = UUID(str(cursor["id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise _invalid_cursor("The cursor payload is invalid.") from error
        filtered = tuple(
            item for item in records if (item.created_at, item.id) < (created_at, identifier)
        )
    items = filtered[:limit]
    next_cursor = None
    if len(filtered) > limit and items:
        last = items[-1]
        next_cursor = _encode(
            {
                "version": 1,
                "created_at": last.created_at.isoformat(),
                "id": str(last.id),
                "filters": fingerprint(filters),
            }
        )
    return items, next_cursor


def _encode(payload: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(canonical_json(payload)).decode("ascii").rstrip("=")


def _decode(value: str) -> dict[str, object]:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding)
        payload = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _invalid_cursor("The cursor is malformed.") from error
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise _invalid_cursor("The cursor version is unsupported.")
    return payload


def _invalid_cursor(detail: str) -> ProblemException:
    return ProblemException(
        status_code=400,
        code="invalid_cursor",
        title="Pagination cursor is invalid",
        detail=detail,
    )
