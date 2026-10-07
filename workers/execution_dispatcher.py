"""Isolated Python/R execution dispatcher process."""

import signal
import time
from types import FrameType

from app.artifacts.storage import S3ObjectStorage
from app.composition import build_module_registry
from app.config import get_settings
from app.database import create_database_engine, create_session_factory
from app.execution.adapters import DockerExecutor
from app.execution.jobs import JobService
from app.execution.worker import process_execution_job

_stopping = False


def _request_stop(_signal: int, _frame: FrameType | None) -> None:
    global _stopping
    _stopping = True


def main() -> None:
    """Claim only execution jobs and dispatch each through the configured adapter."""

    settings = get_settings()
    if settings.executor_adapter != "docker":
        raise RuntimeError(f"unsupported local executor adapter: {settings.executor_adapter}")
    factory = create_session_factory(create_database_engine(settings))
    storage = S3ObjectStorage(settings)
    registry = build_module_registry()
    executor = DockerExecutor(
        network_disabled=settings.execution_network_disabled,
        log_limit_bytes=settings.execution_log_limit_bytes,
    )
    service = JobService()
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    while not _stopping:
        with factory.begin() as session:
            job = service.claim(
                session,
                worker_id="execution-dispatcher",
                lease_seconds=settings.job_lease_seconds,
                job_types=("execution",),
            )
        if job is None:
            time.sleep(1)
            continue
        process_execution_job(factory, registry, storage, executor, settings, job.id)


if __name__ == "__main__":
    main()
