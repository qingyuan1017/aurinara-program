"""Isolated Python/R execution dispatcher process."""

import logging
import os
import signal
import socket
import time
from types import FrameType

from app.artifacts.storage import S3ObjectStorage
from app.common.logging import configure_logging
from app.composition import build_module_registry
from app.config import get_settings
from app.database import create_database_engine, create_session_factory
from app.execution.adapters import DockerExecutor, Executor
from app.execution.jobs import JobService, LeaseLostError, claimed_job
from app.execution.leases import LeaseHeartbeat
from app.execution.worker import process_execution_job

_stopping = False
logger = logging.getLogger(__name__)


def _request_stop(_signal: int, _frame: FrameType | None) -> None:
    global _stopping
    _stopping = True


def main() -> None:
    """Claim only execution jobs and dispatch each through the configured adapter."""

    settings = get_settings()
    configure_logging(settings.app_log_level)
    factory = create_session_factory(create_database_engine(settings))
    storage = S3ObjectStorage(settings)
    registry = build_module_registry()
    if settings.executor_adapter == "docker":
        executor: Executor = DockerExecutor(
            network_disabled=settings.execution_network_disabled,
            log_limit_bytes=settings.execution_log_limit_bytes,
        )
    else:
        from app.execution.ecs import EcsExecutor

        executor = EcsExecutor.from_settings(settings)
    service = JobService()
    worker_id = f"execution-dispatcher:{socket.gethostname()}:{os.getpid()}"
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    while not _stopping:
        with factory.begin() as session:
            job = service.claim(
                session,
                worker_id=worker_id,
                lease_seconds=settings.job_lease_seconds,
                job_types=("execution",),
            )
        if job is None:
            time.sleep(1)
            continue
        if job.lease_token is None:
            raise RuntimeError("claimed job did not receive a lease token")
        with claimed_job(job.lease_token), LeaseHeartbeat(
            factory,
            job_id=job.id,
            worker_id=worker_id,
            lease_token=job.lease_token,
            lease_seconds=settings.job_lease_seconds,
            heartbeat_seconds=settings.job_lease_heartbeat_seconds,
        ):
            try:
                process_execution_job(factory, registry, storage, executor, settings, job.id)
            except LeaseLostError:
                logger.warning(
                    "execution lease lost before publication",
                    extra={"job_id": str(job.id)},
                )


if __name__ == "__main__":
    main()
