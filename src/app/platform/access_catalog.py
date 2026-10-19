"""Reviewed Aurinara permissions and the default study-owner role."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

AURINARA_STUDY_OWNER_ROLE_ID: UUID = uuid5(NAMESPACE_URL, "aurinara:role:Aurinara Study Owner")

AURINARA_STUDY_PERMISSIONS = (
    "artifact.study.read",
    "artifact.study.write",
    "artifact.object.upload",
    "artifact.object.download",
    "artifact.object.reference",
    "artifact.execution.run",
    "artifact.validation.run",
    "artifact.reconciliation.run",
    "artifact.package.build",
)


def permission_catalog() -> list[dict[str, object]]:
    """Return the explicit study-scoped capability catalog owned by Aurinara."""

    return [
        {
            "code": code,
            "description": code.replace(".", " · "),
            "module": "aurinara",
            "allowed_scope_levels": ["system", "study"],
        }
        for code in AURINARA_STUDY_PERMISSIONS
    ]


def role_catalog() -> list[dict[str, object]]:
    """Return the stable role assigned to a canonical study creator."""

    return [
        {
            "source_role_id": str(AURINARA_STUDY_OWNER_ROLE_ID),
            "name": "Aurinara Study Owner",
            "description": "Full Aurinara authoring access within one assigned study",
            "scope_level": "study",
            "permissions": list(AURINARA_STUDY_PERMISSIONS),
        }
    ]
