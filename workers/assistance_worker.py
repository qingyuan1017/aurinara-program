"""Dedicated durable worker with the only model-provider network boundary."""

import argparse
import logging
import os
import signal
import socket
import time
from types import FrameType
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.assistance.models import AiGenerationRun, AuthoringProposal
from app.assistance.provider import ProviderError, create_proposal_provider
from app.assistance.service import AssistanceService, ProposalCapability
from app.common.logging import configure_logging
from app.composition import build_module_registry
from app.config import Settings, get_settings
from app.database import create_database_engine, create_session_factory
from app.execution.jobs import Job, JobService, claimed_job
from app.execution.leases import LeaseHeartbeat
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry

logger = logging.getLogger(__name__)
_stopping = False


def _request_stop(_signal: int, _frame: FrameType | None) -> None:
    global _stopping
    _stopping = True


def _proposal_for_run(session: Session, run: AiGenerationRun) -> AuthoringProposal | None:
    return session.scalar(
        select(AuthoringProposal).where(AuthoringProposal.generation_run_id == run.id)
    )


def _record_failure(
    factory: sessionmaker[Session], job_id: UUID, failure: dict[str, object]
) -> None:
    with factory.begin() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        JobService().fail(job, failure)
        run = session.get(AiGenerationRun, UUID(str(job.payload["generation_run_id"])))
        proposal = _proposal_for_run(session, run) if run is not None else None
        if run is not None and proposal is not None and job.status == "failed":
            AssistanceService.fail(
                run,
                proposal,
                str(failure.get("code", "ai_proposal_failed")),
                str(failure.get("detail", "AI proposal generation failed.")),
            )


def _handle(
    factory: sessionmaker[Session],
    registry: ModuleRegistry,
    settings: Settings,
    job_id: UUID,
) -> None:
    assistance = AssistanceService()
    with factory.begin() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        run = session.get(AiGenerationRun, UUID(str(job.payload["generation_run_id"])))
        proposal = _proposal_for_run(session, run) if run is not None else None
        if run is None or proposal is None:
            JobService().fail(job, {"code": "ai_proposal_missing"})
            return
        handler = cast(
            ProposalCapability,
            registry.require_handler(run.module_key, ModuleCapability.PROPOSALS),
        )
        request = assistance.begin_generation(
            session,
            run=run,
            proposal=proposal,
            handler=handler,
            registry=registry,
        )
        if request is None:
            JobService().complete(job)
            return

    try:
        result = create_proposal_provider(settings).generate(
            request,
            operation_id=run.id,
            agent_id=UUID(str(run.generation_parameters["platform_agent_id"])),
            agent_revision=int(str(run.generation_parameters["platform_agent_revision"])),
        )
    except ProviderError as error:
        _record_failure(factory, job_id, {"code": error.code, "detail": error.detail})
        return

    with factory.begin() as session:
        job = session.get(Job, job_id)
        run = (
            session.get(AiGenerationRun, UUID(str(job.payload["generation_run_id"])))
            if job is not None
            else None
        )
        proposal = _proposal_for_run(session, run) if run is not None else None
        if job is None or run is None or proposal is None:
            return
        handler = cast(
            ProposalCapability,
            registry.require_handler(run.module_key, ModuleCapability.PROPOSALS),
        )
        assistance.complete_generation(
            session,
            run=run,
            proposal=proposal,
            result=result,
            handler=handler,
        )
        JobService().complete(job)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process durable Aurinara AI proposal jobs")
    parser.add_argument("--drain", action="store_true")
    arguments = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.app_log_level)
    factory = create_session_factory(create_database_engine(settings))
    registry = build_module_registry()
    jobs = JobService()
    worker_id = f"assistance-worker:{socket.gethostname()}:{os.getpid()}"
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    while not _stopping:
        with factory.begin() as session:
            job = jobs.claim(
                session,
                worker_id=worker_id,
                lease_seconds=settings.job_lease_seconds,
                job_types=("ai_proposal",),
            )
        if job is None:
            if arguments.drain:
                return
            time.sleep(1)
            continue
        if job.lease_token is None:
            raise RuntimeError("claimed job did not receive a lease token")
        with (
            claimed_job(job.lease_token),
            LeaseHeartbeat(
                factory,
                job_id=job.id,
                worker_id=worker_id,
                lease_token=job.lease_token,
                lease_seconds=settings.job_lease_seconds,
                heartbeat_seconds=settings.job_lease_heartbeat_seconds,
            ),
        ):
            try:
                _handle(factory, registry, settings, job.id)
            except Exception as error:  # worker boundary records no provider body or prompt
                logger.exception("AI proposal processing failed", extra={"job_id": str(job.id)})
                _record_failure(
                    factory,
                    job.id,
                    {"code": "ai_proposal_processing_failed", "detail": type(error).__name__},
                )


if __name__ == "__main__":
    main()
