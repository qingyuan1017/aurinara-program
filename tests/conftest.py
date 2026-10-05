"""Shared deterministic test fixtures."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Return isolated settings without reading developer environment overrides."""

    return Settings(
        _env_file=None,
        app_env="test",
        app_log_level="WARNING",
        integration_allow_loopback_callbacks=True,
    )


@pytest.fixture
def anyio_backend() -> str:
    """Keep async contract tests on the runtime supported by the application."""

    return "asyncio"


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """Create an in-process API client."""

    transport = ASGITransport(app=create_app(settings=settings))
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        yield test_client
