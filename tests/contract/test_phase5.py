"""Phase 5 TLF and submission-package OpenAPI contract coverage."""

from app.main import app
from tests.contract.typed_client_fixture import PHASE5_TLF_PACKAGING_OPERATIONS


def test_phase5_typed_client_fixture_matches_openapi() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    for path, methods in PHASE5_TLF_PACKAGING_OPERATIONS.items():
        assert path in paths
        assert methods <= set(paths[path])


def test_internal_analysis_ir_is_not_publicly_mutable() -> None:
    paths = app.openapi()["paths"]
    assert not any("analysis-ir" in path or "analysis_ir" in path for path in paths)
