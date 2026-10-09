"""Phase 4 ADaM foundation OpenAPI surface."""

from app.main import app
from tests.contract.typed_client_fixture import PHASE4_ADAM_FOUNDATION_OPERATIONS


def test_phase4_adam_foundation_fixture_matches_openapi() -> None:
    paths = app.openapi()["paths"]

    for path, methods in PHASE4_ADAM_FOUNDATION_OPERATIONS.items():
        assert path in paths
        assert methods <= set(paths[path])
