"""Normalized route and operation-ID inventory."""

import re

from app.main import app


def test_clinical_workbench_roots_replace_legacy_roots() -> None:
    paths = app.openapi()["paths"]
    required = {
        "/api/v1/studies/{study_id}/raw-workbenches",
        "/api/v1/raw-workbenches/{raw_id}",
        "/api/v1/studies/{study_id}/sdtm-workbenches",
        "/api/v1/sdtm-workbenches/{sdtm_id}",
        "/api/v1/studies/{study_id}/adam-workbenches",
        "/api/v1/adam-workbenches/{adam_id}",
        "/api/v1/studies/{study_id}/tlf-workbenches",
        "/api/v1/tlf-workbenches/{tlf_id}",
    }
    assert required <= set(paths)
    assert not any(
        path.startswith(("/api/v1/raw/", "/api/v1/sdtms/", "/api/v1/adams/", "/api/v1/tlfs/"))
        for path in paths
    )


def test_commands_use_colon_suffixes_and_links_use_put() -> None:
    paths = app.openapi()["paths"]
    commands = {
        "archive",
        "build",
        "cancel",
        "compile",
        "execute",
        "export",
        "generate",
        "import",
        "initialize",
        "preview",
        "reconcile",
        "render",
        "test",
        "validate",
    }
    assert not any(path.rsplit("/", 1)[-1] in commands for path in paths)
    assert "post" in paths["/api/v1/sdtm-workbenches/{sdtm_id}/specification:import"]
    assert "post" in paths["/api/v1/adam-workbenches/{adam_id}:compile"]
    assert "post" in paths["/api/v1/tlf-workbenches/{tlf_id}:execute"]
    assert "post" in paths["/api/v1/raw-workbenches/{raw_id}/artifacts:build"]
    assert set(paths["/api/v1/acrf-annotations/{annotation_id}/links"]) >= {"put"}
    assert "post" not in paths["/api/v1/acrf-annotations/{annotation_id}/links"]


def test_every_operation_id_is_unique_and_stably_shaped() -> None:
    operations = [
        operation
        for path in app.openapi()["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    operation_ids = [operation["operationId"] for operation in operations]
    assert len(operation_ids) == len(set(operation_ids))
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*_[a-z0-9]+", item) for item in operation_ids)
