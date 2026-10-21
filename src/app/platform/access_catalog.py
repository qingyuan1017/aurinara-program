"""Aurinara-owned permission vocabulary.

Role definitions intentionally do not live in this product. The shared
Platform composes these permissions into built-in and custom roles.
"""

from __future__ import annotations

_MODULE_ACTIONS: dict[str, tuple[str, ...]] = {
    "study": ("read", "manage"),
    "raw": ("read", "write"),
    "documents": ("read", "write"),
    "standards": ("read", "manage"),
    "terminology": ("read", "manage"),
    "reference": ("read", "manage"),
    "templates": ("read", "manage"),
    "sdtm": ("read", "write"),
    "adam": ("read", "write"),
    "tlf": ("read", "write"),
    "review": ("read", "write"),
    "validation": ("read", "run"),
    "reconciliation": ("read", "run"),
    "execution": ("read", "run", "manage"),
    "artifacts": ("read", "write"),
    "packaging": ("read", "run"),
    "integration": ("read", "manage"),
}

_SYSTEM_AND_STUDY_MODULES = frozenset(
    {"standards", "terminology", "reference", "templates", "integration"}
)

AURINARA_PERMISSION_CODES = tuple(
    f"aurinara.{module}.{action}"
    for module, actions in _MODULE_ACTIONS.items()
    for action in actions
)


def permission_catalog() -> list[dict[str, object]]:
    """Return the complete, canonical Aurinara permission catalog."""

    catalog: list[dict[str, object]] = []
    for module, actions in _MODULE_ACTIONS.items():
        scopes = ["system", "study"] if module in _SYSTEM_AND_STUDY_MODULES else ["study"]
        for action in actions:
            catalog.append(
                {
                    "code": f"aurinara.{module}.{action}",
                    "description": f"{action.title()} Aurinara {module} resources",
                    "module": module,
                    "allowed_scope_levels": scopes,
                }
            )
    return catalog
