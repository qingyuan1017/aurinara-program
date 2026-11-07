"""Stable OpenAPI operation identifiers derived from route ownership."""

import re
from enum import Enum

from fastapi.routing import APIRoute

_ACTION_PREFIXES = frozenset(
    {
        "archive",
        "build",
        "cancel",
        "compile",
        "create",
        "delete",
        "download",
        "execute",
        "export",
        "generate",
        "get",
        "import",
        "initialize",
        "list",
        "preview",
        "publish",
        "patch",
        "put",
        "reconcile",
        "render",
        "replace",
        "retire",
        "test",
        "update",
        "validate",
        "write",
    }
)


def _identifier(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def stable_operation_id(route: APIRoute) -> str:
    """Return a deterministic ``<owner>_<resource>_<action>`` identifier."""

    tag = route.tags[0] if route.tags else "api"
    tag_value = tag.value if isinstance(tag, Enum) else tag
    tag_parts = _identifier(str(tag_value)).split("_")
    owner = tag_parts[0]
    scope_parts = tag_parts[1:]
    endpoint_name = _identifier(route.name)
    parts = endpoint_name.split("_")
    action = parts[0] if parts and parts[0] in _ACTION_PREFIXES else ""
    if action:
        resource_parts = parts[1:]
    else:
        action = _identifier(sorted(route.methods or {"get"})[0])
        resource_parts = parts
    if resource_parts and resource_parts[0] in {owner, owner.rstrip("s")}:
        resource_parts = resource_parts[1:]
    if scope_parts and resource_parts[: len(scope_parts)] != scope_parts:
        resource_parts = [*scope_parts, *resource_parts]
    resource = "_".join(resource_parts) or "root"
    return f"{owner}_{resource}_{action}"
