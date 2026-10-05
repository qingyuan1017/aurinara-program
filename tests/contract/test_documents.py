"""Documents route and OpenAPI contract tests."""

import pytest
from httpx import AsyncClient

from tests.contract.typed_client_fixture import PHASE2_DOCUMENT_OPERATIONS


@pytest.mark.anyio
async def test_phase2_document_routes_are_published(client: AsyncClient) -> None:
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    for path, methods in PHASE2_DOCUMENT_OPERATIONS.items():
        assert path in paths
        assert methods <= set(paths[path])


@pytest.mark.anyio
async def test_documents_module_advertises_phase2_capabilities(client: AsyncClient) -> None:
    response = await client.get("/api/v1/modules")
    assert response.status_code == 200
    documents = next(item for item in response.json()["items"] if item["module_key"] == "documents")
    assert "protocol_usdm" in documents["artifact_types"]
    assert "statistical_analysis_plan_pdf" in documents["artifact_types"]
    assert "actions_report_xlsx" in documents["artifact_types"]
    assert "validation" in documents["capabilities"]
    assert "context_export" in documents["capabilities"]
