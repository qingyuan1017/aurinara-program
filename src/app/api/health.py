"""Operational liveness and readiness routes."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_module_registry
from app.artifacts.storage import ObjectStorage
from app.kernel.registry import ModuleRegistry

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    """Process liveness response."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"


class ReadinessCheck(BaseModel):
    """One named readiness result."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "error"]
    detail: str


class ReadinessResponse(BaseModel):
    """Aggregate readiness response."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    checks: dict[str, ReadinessCheck]


@router.get("/health/live", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    """Confirm that the API process can serve requests."""

    return LivenessResponse()


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def readiness(
    request: Request,
    response: Response,
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
) -> ReadinessResponse:
    """Report currently installed readiness probes."""

    registry_ready, detail = registry.readiness()
    checks = {
        "module_registry": ReadinessCheck(
            status="ok" if registry_ready else "error",
            detail=detail,
        )
    }
    ready = registry_ready
    if request.app.state.infrastructure_readiness_enabled:
        database_ready, database_detail = _database_readiness(request.app.state.session_factory)
        storage_ready, storage_detail = _storage_readiness(request.app.state.object_storage)
        checks["database"] = ReadinessCheck(
            status="ok" if database_ready else "error", detail=database_detail
        )
        checks["object_storage"] = ReadinessCheck(
            status="ok" if storage_ready else "error", detail=storage_detail
        )
        ready = ready and database_ready and storage_ready
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        checks=checks,
    )


def _database_readiness(factory: sessionmaker[Session]) -> tuple[bool, str]:
    try:
        with factory() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        return False, "database is unavailable"
    return True, "database connection succeeded"


def _storage_readiness(storage: ObjectStorage) -> tuple[bool, str]:
    try:
        storage.check()
    except Exception:
        return False, "object-store bucket is unavailable"
    return True, "object-store bucket is available"
