"""Phase 3 Raw, SDTM, and aCRF OpenAPI surface."""

from app.main import app
from tests.contract.typed_client_fixture import PHASE3_RAW_SDTM_OPERATIONS


def test_phase3_typed_client_fixture_matches_openapi() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    for path, methods in PHASE3_RAW_SDTM_OPERATIONS.items():
        assert path in paths
        assert methods <= set(paths[path])
