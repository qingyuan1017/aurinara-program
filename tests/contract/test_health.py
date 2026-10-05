"""Health and request-correlation contract tests."""

import re

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_liveness_returns_request_id(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "test-request-1"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "test-request-1"


async def test_invalid_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "unsafe value"})

    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


async def test_readiness_includes_module_registry(client: AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["module_registry"]["status"] == "ok"
