"""Phase 3 Raw, SDTM, and aCRF OpenAPI surface."""

from app.main import app
from tests.contract.typed_client_fixture import PHASE3_RAW_SDTM_OPERATIONS


def test_phase3_typed_client_fixture_matches_openapi() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    for path, methods in PHASE3_RAW_SDTM_OPERATIONS.items():
        assert path in paths
        assert methods <= set(paths[path])


def test_sdtm_specification_initializer_contract_exposes_explicit_scope() -> None:
    schema = app.openapi()
    operation = schema["paths"][
        "/api/v1/sdtms/{sdtm_id}/specification/initialize"
    ]["post"]
    request_body = operation["requestBody"]

    assert request_body["required"] is True
    request_schema = schema["components"]["schemas"]["SdtmSpecificationInitialize"]
    assert request_schema["required"] == ["domain_codes"]
    assert request_schema["properties"]["domain_codes"]["minItems"] == 1
    assert request_schema["properties"]["required_expected_only"]["default"] is False

    options_operation = schema["paths"][
        "/api/v1/sdtms/{sdtm_id}/specification/initialization-options"
    ]["get"]
    response_schema = options_operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema["$ref"].endswith(
        "/SdtmSpecificationInitializationOptions"
    )
