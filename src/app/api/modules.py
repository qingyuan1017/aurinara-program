"""Read-only module discovery routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import get_module_registry
from app.common.problems import ProblemException
from app.kernel.contracts import ModuleDescriptor, ModuleKey
from app.kernel.registry import ModuleRegistry

router = APIRouter(prefix="/modules", tags=["modules"])


class ModuleCollection(BaseModel):
    """Stable module discovery collection."""

    model_config = ConfigDict(extra="forbid")

    items: tuple[ModuleDescriptor, ...]


class ModuleEventTypes(BaseModel):
    """Public event types exposed by one module."""

    model_config = ConfigDict(extra="forbid")

    module_key: ModuleKey
    event_types: tuple[str, ...]


def _require_descriptor(registry: ModuleRegistry, module_key: ModuleKey) -> ModuleDescriptor:
    descriptor = registry.get(module_key)
    if descriptor is None:
        raise ProblemException(
            status_code=status.HTTP_404_NOT_FOUND,
            code="module_not_registered",
            title="Module is not registered",
            detail=f"module '{module_key}' is not registered",
        )
    return descriptor


@router.get("", response_model=ModuleCollection)
def list_modules(
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
) -> ModuleCollection:
    """List enabled safe module descriptors in stable key order."""

    return ModuleCollection(items=registry.descriptors())


@router.get("/{module_key}", response_model=ModuleDescriptor)
def get_module(
    module_key: ModuleKey,
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
) -> ModuleDescriptor:
    """Return one enabled safe module descriptor."""

    return _require_descriptor(registry, module_key)


@router.get("/{module_key}/event-types", response_model=ModuleEventTypes)
def get_module_event_types(
    module_key: ModuleKey,
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
) -> ModuleEventTypes:
    """List registered public event types without exposing internal outbox schemas."""

    descriptor = _require_descriptor(registry, module_key)
    return ModuleEventTypes(
        module_key=descriptor.module_key,
        event_types=descriptor.event_types,
    )
