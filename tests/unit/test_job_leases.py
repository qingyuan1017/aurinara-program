"""Lease-token fencing invariants for durable workers."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.execution.jobs import Job, JobService, LeaseLostError, claimed_job


def _running_job() -> tuple[Job, UUID]:
    now = datetime.now(UTC)
    token = uuid4()
    job = Job(
        operation_id=uuid4(),
        job_type="execution",
        status="running",
        payload={},
        attempt_count=1,
        max_attempts=3,
        lease_owner="worker-a",
        lease_token=token,
        claim_generation=2,
        lease_expires_at=now + timedelta(minutes=1),
        available_at=now,
        created_at=now,
    )
    return job, token


def test_matching_claim_token_allows_terminal_transition() -> None:
    job, token = _running_job()

    with claimed_job(token):
        JobService().complete(job)

    assert job.status == "succeeded"
    assert job.lease_token is None
    assert job.lease_owner is None


def test_superseded_claim_cannot_publish_completion() -> None:
    job, old_token = _running_job()
    job.lease_token = uuid4()
    job.claim_generation += 1

    with claimed_job(old_token), pytest.raises(LeaseLostError, match="no longer owned"):
        JobService().complete(job)

    assert job.status == "running"


def test_expired_claim_cannot_be_renewed() -> None:
    job, token = _running_job()
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(LeaseLostError, match="no longer owned"):
        JobService().renew(
            job,
            worker_id="worker-a",
            lease_token=token,
            lease_seconds=60,
        )
