"""Opaque optimistic-concurrency tag handling."""

import hmac

from app.common.problems import ProblemException


def etag_for_revision(revision: int) -> str:
    """Create the stable opaque representation for a persisted revision."""

    return f'"revision-{revision}"'


def require_matching_etag(if_match: str | None, revision: int) -> None:
    """Reject missing or stale conditional writes."""

    if if_match is None:
        raise ProblemException(
            status_code=428,
            code="precondition_required",
            title="If-Match is required",
            detail="Supply the current ETag in the If-Match header.",
        )
    expected = etag_for_revision(revision)
    if not hmac.compare_digest(if_match, expected):
        raise ProblemException(
            status_code=412,
            code="precondition_failed",
            title="The resource has changed",
            detail="The supplied ETag does not match the current revision.",
        )
