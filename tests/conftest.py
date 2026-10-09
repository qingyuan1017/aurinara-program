"""Shared deterministic test fixtures."""

import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app

#: Database name used by the integration suite when the configured URL is not
#: already a test database. Integration fixtures TRUNCATE tables, so they must
#: never run against the developer's working database.
_DEFAULT_TEST_DATABASE_NAME = "clinical_test"


def _derive_test_database_url(configured_url: str) -> str:
    """Return a database URL guaranteed to point at an isolated test database.

    Resolution order:

    1. An explicit ``AURINARA_TEST_DATABASE_URL`` is honored verbatim so a CI or
       developer can point the suite anywhere.
    2. Otherwise the configured application URL has its database name swapped to
       :data:`_DEFAULT_TEST_DATABASE_NAME` (unless it already ends in
       ``_test``), so the destructive integration fixtures can never truncate
       the working database named in ``DATABASE_URL``.
    """

    explicit = os.environ.get("AURINARA_TEST_DATABASE_URL")
    if explicit:
        return explicit

    parts = urlsplit(configured_url)
    database_name = parts.path.lstrip("/")
    if database_name.endswith("_test"):
        return configured_url
    return urlunsplit(
        parts._replace(path=f"/{database_name}_test" if database_name else "/clinical_test")
    )


def make_test_settings(**overrides: object) -> Settings:
    """Build isolated ``app_env=test`` settings for the integration DB suites.

    The database URL is forced to an isolated test database (see
    :func:`_derive_test_database_url`) so the TRUNCATE-based integration
    fixtures cannot destroy the developer's working data. The in-process API
    client and all other application behavior are otherwise unchanged.
    """

    base = Settings(_env_file=None, app_env="test")
    database_url = _derive_test_database_url(base.database_url)
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=database_url,
        **overrides,
    )


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
