"""Background renewal for PostgreSQL-backed worker leases."""

import logging
import threading
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.common.metrics import emit_metric
from app.config import get_settings
from app.execution.jobs import Job, JobService, LeaseLostError

logger = logging.getLogger(__name__)


class LeaseHeartbeat:
    """Renew one claimed job until processing leaves the guarded context."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        lease_seconds: int,
        heartbeat_seconds: int,
    ) -> None:
        self._factory = factory
        self._job_id = job_id
        self._worker_id = worker_id
        self._lease_token = lease_token
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"lease-heartbeat-{job_id}",
            daemon=True,
        )

    def __enter__(self) -> "LeaseHeartbeat":
        self._thread.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1, self._heartbeat_seconds + 1))

    @property
    def lost(self) -> bool:
        """Return whether renewal proved that another claimant owns the job."""

        return self._lost.is_set()

    def _run(self) -> None:
        while not self._stop.wait(self._heartbeat_seconds):
            try:
                with self._factory.begin() as session:
                    job = session.get(Job, self._job_id)
                    if job is None:
                        raise LeaseLostError("job was removed while processing")
                    JobService().renew(
                        job,
                        worker_id=self._worker_id,
                        lease_token=self._lease_token,
                        lease_seconds=self._lease_seconds,
                    )
            except LeaseLostError:
                self._lost.set()
                emit_metric("ExpiredLeases", 1, environment=get_settings().app_env)
                logger.warning("job lease lost", extra={"job_id": str(self._job_id)})
                return
            except Exception:
                logger.exception("job lease renewal failed", extra={"job_id": str(self._job_id)})
