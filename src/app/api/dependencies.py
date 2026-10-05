"""HTTP dependencies for application-composed services."""

from collections.abc import Iterator
from typing import cast

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from app.artifacts.storage import ObjectStorage
from app.kernel.registry import ModuleRegistry


def get_module_registry(request: Request) -> ModuleRegistry:
    """Resolve the sealed module registry from application state."""

    return cast(ModuleRegistry, request.app.state.module_registry)


def get_session(request: Request) -> Iterator[Session]:
    """Provide one request-scoped database session without implicit commits."""

    factory = cast(sessionmaker[Session], request.app.state.session_factory)
    with factory() as session:
        yield session


def get_object_storage(request: Request) -> ObjectStorage:
    """Resolve the configured storage adapter."""

    return cast(ObjectStorage, request.app.state.object_storage)
