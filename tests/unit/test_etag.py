"""Optimistic-concurrency behavior."""

import pytest

from app.common.etag import etag_for_revision, require_matching_etag
from app.common.problems import ProblemException


def test_etag_requires_current_revision() -> None:
    require_matching_etag(etag_for_revision(3), 3)

    with pytest.raises(ProblemException) as missing:
        require_matching_etag(None, 3)
    assert missing.value.status_code == 428

    with pytest.raises(ProblemException) as stale:
        require_matching_etag(etag_for_revision(2), 3)
    assert stale.value.status_code == 412
