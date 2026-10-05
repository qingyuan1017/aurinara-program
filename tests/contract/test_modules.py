"""Module discovery and OpenAPI contract tests."""

import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.kernel.contracts import ModuleDescriptor, ModuleRegistration
from app.kernel.registry import ModuleRegistry
from app.main import create_app
from tests.contract.typed_client_fixture import PHASE1_OPERATIONS

pytestmark = pytest.mark.anyio


async def test_module_collection_is_sorted_and_safe(client: AsyncClient) -> None:
    response = await client.get("/api/v1/modules")

    assert response.status_code == 200
    items = response.json()["items"]
    keys = [item["module_key"] for item in items]
    assert keys == sorted(keys)
    assert {"raw", "documents", "sdtm", "adam", "tlf", "integration"} <= set(keys)
    assert all("handlers" not in item for item in items)


async def test_module_member_and_event_types(client: AsyncClient) -> None:
    member = await client.get("/api/v1/modules/raw")
    event_types = await client.get("/api/v1/modules/raw/event-types")

    assert member.status_code == 200
    assert member.json()["api_prefix"] == "/api/v1/raw"
    assert event_types.status_code == 200
    assert event_types.json() == {"module_key": "raw", "event_types": []}


async def test_unknown_module_uses_problem_details(client: AsyncClient) -> None:
    response = await client.get("/api/v1/modules/labs")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "module_not_registered"
    assert body["request_id"] == response.headers["X-Request-ID"]


async def test_invalid_module_key_uses_transport_problem(client: AsyncClient) -> None:
    response = await client.get("/api/v1/modules/bad_module")

    assert response.status_code == 422
    assert response.json()["code"] == "request_validation_failed"


async def test_versioned_openapi_contains_foundation_routes(client: AsyncClient) -> None:
    response = await client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/api/v1/modules" in paths
    assert "/api/v1/modules/{module_key}" in paths
    assert (await client.get("/openapi.json")).status_code == 404

    for path, methods in PHASE1_OPERATIONS.items():
        assert path in paths
        assert methods <= set(paths[path])


async def test_deployment_module_router_composes_without_shared_dispatch_change() -> None:
    labs_router = APIRouter()

    @labs_router.get("/labs/ping")
    def labs_ping() -> dict[str, str]:
        return {"module": "labs"}

    registry = ModuleRegistry()
    registry.register(
        ModuleRegistration(
            ModuleDescriptor(
                module_key="labs",
                module_version="1.0.0",
                api_prefix="/api/v1/labs",
            ),
            router=labs_router,
        )
    )
    registry.seal()
    application = create_app(
        settings=Settings(_env_file=None, app_env="test"), module_registry=registry
    )
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as test_client:
        response = await test_client.get("/api/v1/labs/ping")
        discovered = await test_client.get("/api/v1/modules/labs")

    assert response.json() == {"module": "labs"}
    assert discovered.status_code == 200
