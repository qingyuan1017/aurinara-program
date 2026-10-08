"""Shared artifact-build fingerprint helper invariants."""

from uuid import UUID

from app.artifacts import builds
from app.common.canonical import fingerprint


def test_resolve_build_fingerprint_matches_resolved_input(monkeypatch) -> None:
    study_id = UUID("11111111-1111-1111-1111-111111111111")
    owner_id = UUID("22222222-2222-2222-2222-222222222222")
    sentinel_handler = object()
    resolved: dict[str, object] = {
        "study_id": str(study_id),
        "owner_type": "raw_workbench",
        "owner_id": str(owner_id),
        "artifact_types": ["raw_metadata_json"],
        "options": {},
        "payloads": [{"kind": "raw_metadata_json"}],
    }
    captured: dict[str, object] = {}

    def fake_resolve_build_input(session, registry, **kwargs):
        captured.update(kwargs)
        return "raw", sentinel_handler, resolved

    monkeypatch.setattr(builds, "resolve_build_input", fake_resolve_build_input)

    input_fingerprint, module_key, handler, returned = builds.resolve_build_fingerprint(
        session=object(),
        registry=object(),
        study_id=study_id,
        owner_type="raw_workbench",
        owner_id=owner_id,
        artifact_types=("raw_metadata_json",),
        options={},
    )

    assert input_fingerprint == fingerprint(resolved)
    assert module_key == "raw"
    assert handler is sentinel_handler
    assert returned is resolved
    assert captured == {
        "study_id": study_id,
        "owner_type": "raw_workbench",
        "owner_id": owner_id,
        "artifact_types": ("raw_metadata_json",),
        "options": {},
    }
