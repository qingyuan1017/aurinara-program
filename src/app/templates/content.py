"""Checksum-verified loading for immutable presentation-only template content."""

from pathlib import Path
from typing import cast

from app.artifacts.storage import ObjectStorage
from app.common.asset_content import read_verified_asset_json_object
from app.common.problems import ProblemException
from app.common.repository_assets import verify_repository_asset


def load_presentation_template(
    storage: ObjectStorage, ref: dict[str, object]
) -> dict[str, object]:
    """Load one exact template while enforcing its presentation-only boundary."""

    checksum = str(ref["checksum"])
    asset_path = str(ref["asset_path"])
    renderer_versions = cast(list[str], ref["renderer_versions"])
    local_fallback = (
        (
            lambda: verify_repository_asset(
                Path(__file__).resolve().parents[3],
                asset_path,
                checksum,
                allowed_root="templates",
            )[0]
        )
        if storage.local_fallback_enabled
        else None
    )
    value = read_verified_asset_json_object(storage, checksum, local_fallback=local_fallback)
    allowed_keys = {"schema_version", "renderer", "styles", "blank_structure"}
    if not set(value) <= allowed_keys:
        raise _boundary_problem(
            "Templates may contain only presentation styles and blank structure."
        )
    styles = value.get("styles")
    blank_structure = value.get("blank_structure")
    if (
        not isinstance(styles, dict)
        or any(
            not isinstance(key, str) or not isinstance(item, str) for key, item in styles.items()
        )
        or not isinstance(blank_structure, list)
        or any(not isinstance(item, str) for item in blank_structure)
    ):
        raise _boundary_problem(
            "Template styles and blank structures must be presentation-only strings."
        )
    if "document-1" not in renderer_versions or value.get("renderer") != "document-1":
        raise ProblemException(
            status_code=409,
            code="template_renderer_incompatible",
            title="Template renderer is incompatible",
            detail="The exact Template version does not support this renderer.",
        )
    return value


def _boundary_problem(detail: str) -> ProblemException:
    return ProblemException(
        status_code=409,
        code="template_content_boundary_violation",
        title="Template contains unsupported content",
        detail=detail,
    )
