"""Opaque cursor pagination invariants."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.common.pagination import paginate
from app.common.problems import ProblemException


@dataclass(frozen=True)
class Record:
    id: UUID
    created_at: datetime


def test_cursor_pages_stably_and_is_bound_to_filters() -> None:
    now = datetime.now(UTC)
    records = tuple(
        Record(UUID(int=index + 1), now - timedelta(seconds=index)) for index in range(3)
    )
    first, cursor = paginate(records, limit=2, after=None, filters={"study": "one"})
    second, final_cursor = paginate(records, limit=2, after=cursor, filters={"study": "one"})

    assert len(first) == 2
    assert second == (records[2],)
    assert final_cursor is None
    with pytest.raises(ProblemException) as error:
        paginate(records, limit=2, after=cursor, filters={"study": "two"})
    assert error.value.code == "invalid_cursor"
