"""PostgreSQL-backed durable job model and lifecycle service."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Uuid, and_, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.common.persistence import UuidPrimaryKey
from app.common.time import utc_now
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
        job.status = "running"
        job.lease_owner = worker_id
        job.lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
        job.attempt_count += 1
        job.started_at = job.started_at or claimed_at
        session.flush()
        return job

    def complete(self, job: Job, *, now: datetime | None = None) -> None:
        """Idempotently complete a running job."""

        if job.status == "succeeded":
            return
        if job.status != "running":
            raise ValueError("only running jobs may complete")
        job.status = "succeeded"
        job.completed_at = now or utc_now()
        job.lease_owner = None
        job.lease_expires_at = None

    def fail(
        self,
        job: Job,
        failure: dict[str, object],
        *,
        retry_at: datetime | None = None,
        now: datetime | None = None,
    ) -> None:
        """Record a typed failure and requeue while attempts remain."""

        failed_at = now or utc_now()
        job.failure = failure
        job.lease_owner = None
        job.lease_expires_at = None
        if job.attempt_count < job.max_attempts:
            job.status = "queued"
            job.available_at = retry_at or failed_at
        else:
            job.status = "failed"
            job.completed_at = failed_at
