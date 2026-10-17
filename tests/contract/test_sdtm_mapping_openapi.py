"""Breaking SDTM mapping/workarea API surface."""

import app.model_registry as _model_registry  # noqa: F401
from app.database import Base
from app.main import app


def test_sdtm_mapping_and_workarea_routes_replace_graph_routes() -> None:
    paths = app.openapi()["paths"]
    required = {
        "/api/v1/sdtms/{sdtm_id}/domain-mappings",
        "/api/v1/sdtms/{sdtm_id}/domains/{domain}/domain-mapping",
        "/api/v1/sdtms/{sdtm_id}/domains/{domain}/variable-mapping",
        "/api/v1/sdtms/{sdtm_id}/code-workareas",
        "/api/v1/sdtms/{sdtm_id}/code-workareas/{workarea_id}",
        "/api/v1/sdtms/{sdtm_id}/code-workareas/{workarea_id}/test",
        "/api/v1/sdtms/{sdtm_id}/code-workareas/{workarea_id}/generate",
        "/api/v1/sdtm-code-runs/{run_id}",
        "/api/v1/sdtms/{sdtm_id}/output-selection",
        "/api/v1/sdtms/{sdtm_id}/program-artifact-readiness",
    }
    assert required <= set(paths)
    assert "/api/v1/sdtms/{sdtm_id}/derivation-plans" not in paths
    assert "/api/v1/sdtms/{sdtm_id}/compile" not in paths
    assert "/api/v1/sdtms/{sdtm_id}/execute" not in paths


def test_graph_plan_table_is_absent_from_current_metadata() -> None:
    assert "sdtm_derivation_plan_revisions" not in Base.metadata.tables
    assert {
        "sdtm_domain_mapping_revisions",
        "sdtm_variable_mapping_revisions",
        "sdtm_code_workareas",
        "sdtm_code_revisions",
        "sdtm_output_selections",
    } <= set(Base.metadata.tables)
