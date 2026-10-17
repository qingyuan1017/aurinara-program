"""PostgreSQL-backed durable job model and lifecycle service."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, Uuid, and_, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.common.metrics import emit_metric
from app.common.persistence import UuidPrimaryKey
from app.common.time import utc_now
from app.config import get_settings
from app.database import Base


class Job(UuidPrimaryKey, Base):
    """Retryable leased unit of asynchronous work."""

    __tablename__ = "jobs"

    operation_id: Mapped[UUID] = mapped_column(Uuid, unique=True, nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    claim_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


_claim_token_context: ContextVar[UUID | None] = ContextVar("job_claim_token", default=None)


class LeaseLostError(RuntimeError):
    """Raised when a stale worker attempts to publish a terminal job transition."""


@contextmanager
def claimed_job(token: UUID) -> Iterator[None]:
    """Fence job transitions to the token issued by the active claim."""

    context_token = _claim_token_context.set(token)
    try:
        yield
    finally:
        _claim_token_context.reset(context_token)


class JobService:
    """Perform short transactional job lifecycle transitions."""

    def claim(
        self,
        session: Session,
        *,
        worker_id: str,
        lease_seconds: int,
        job_types: tuple[str, ...] | None = None,
        now: datetime | None = None,
    ) -> Job | None:
        """Claim one eligible job using a skip-locked row lock."""

        claimed_at = now or utc_now()
        conditions = [
            Job.attempt_count < Job.max_attempts,
            Job.available_at <= claimed_at,
            or_(
                Job.status == "queued",
                and_(Job.status == "running", Job.lease_expires_at < claimed_at),
            ),
        ]
        if job_types is not None:
            conditions.append(Job.job_type.in_(job_types))
        statement = (
            select(Job)
            .where(*conditions)
            .order_by(Job.available_at, Job.created_at, Job.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = session.scalar(statement)
        if job is None:
            return None
        expired_lease = job.status == "running"
        queue_age_seconds = max(0.0, (claimed_at - job.created_at).total_seconds())
        job.status = "running"
        job.lease_owner = worker_id
        job.lease_token = uuid4()
        job.claim_generation += 1
        job.lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
        job.attempt_count += 1
        job.started_at = job.started_at or claimed_at
        session.flush()
        environment = get_settings().app_env
        emit_metric(
            "OldestQueuedJobSeconds",
            queue_age_seconds,
            environment=environment,
            unit="Seconds",
        )
        worker_queue = "execution" if job_types == ("execution",) else "build"
        queue_conditions = [Job.status == "queued"]
        if job_types is not None:
            queue_conditions.append(Job.job_type.in_(job_types))
        queue_depth = session.scalar(
            select(func.count(Job.id)).where(*queue_conditions)
        ) or 0
        emit_metric(
            "QueuedJobs",
            float(queue_depth),
            environment=environment,
            dimensions={"WorkerQueue": worker_queue},
        )
        if expired_lease:
            emit_metric("ExpiredLeases", 1, environment=environment)
        return job

    def renew(
        self,
        job: Job,
        *,
        worker_id: str,
        lease_token: UUID,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> None:
        """Extend an active lease only for its current owner and claim token."""

        renewed_at = now or utc_now()
        self._require_lease(job, lease_token=lease_token, worker_id=worker_id, now=renewed_at)
        job.lease_expires_at = renewed_at + timedelta(seconds=lease_seconds)

    def complete(
        self,
        job: Job,
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        """Idempotently complete a running job."""

        if job.status == "succeeded":
            return
        completed_at = now or utc_now()
        self._require_lease(job, lease_token=lease_token, now=completed_at)
        job.status = "succeeded"
        job.completed_at = completed_at
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None

    def fail(
        self,
        job: Job,
        failure: dict[str, object],
        *,
        lease_token: UUID | None = None,
        retry_at: datetime | None = None,
        now: datetime | None = None,
    ) -> None:
        """Record a typed failure and requeue while attempts remain."""

        failed_at = now or utc_now()
        self._require_lease(job, lease_token=lease_token, now=failed_at)
        job.failure = failure
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        if job.attempt_count < job.max_attempts:
            job.status = "queued"
            job.available_at = retry_at or failed_at
        else:
            job.status = "failed"
            job.completed_at = failed_at
            environment = get_settings().app_env
            emit_metric("TerminalJobFailures", 1, environment=environment)
            if job.job_type == "execution":
                emit_metric("ExecutionFailures", 1, environment=environment)

    @staticmethod
    def _require_lease(
        job: Job,
        *,
        lease_token: UUID | None,
        worker_id: str | None = None,
        now: datetime,
    ) -> None:
        expected = lease_token or _claim_token_context.get()
        if expected is None:
            raise LeaseLostError("a claim token is required for job transition")
        if (
            job.status != "running"
            or job.lease_token != expected
            or job.lease_owner is None
            or (worker_id is not None and job.lease_owner != worker_id)
            or job.lease_expires_at is None
            or job.lease_expires_at < now
        ):
            raise LeaseLostError("job lease is no longer owned by this worker")
