"""Immutable contracts used to register application modules."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

ModuleKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]{1,31}$")]
OwnedType = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
EventType = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*)+$"),
]


class ModuleCapability(StrEnum):
    """Capabilities a module may implement for shared platform services."""

    DEPENDENCIES = "dependencies"
    STALENESS = "staleness"
    VALIDATION = "validation"
    ARTIFACTS = "artifacts"
    ENTITY_RESOLUTION = "entity_resolution"
    REVIEW_TARGETS = "review_targets"
    RECONCILIATION_INPUTS = "reconciliation_inputs"
    RECONCILIATION = "reconciliation"
    CONTEXT_EXPORT = "context_export"
    TRACEABILITY = "traceability"
    PACKAGING = "packaging"
    COMPILATION = "compilation"
    EXECUTION = "execution"
    OUTBOUND_EVENTS = "outbound_events"


class ModuleDescriptor(BaseModel):
    """Safe immutable metadata describing one enabled module."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    module_key: ModuleKey
    module_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    api_prefix: str = Field(pattern=r"^/api/v1/[a-z][a-z0-9-]*$")
    content_schema_versions: tuple[str, ...] = ()
    dependency_purposes: tuple[OwnedType, ...] = ()
    entity_types: tuple[OwnedType, ...] = ()
    relationship_types: tuple[OwnedType, ...] = ()
    artifact_types: tuple[OwnedType, ...] = ()
    source_plan_types: tuple[OwnedType, ...] = ()
    reconciliation_types: tuple[OwnedType, ...] = ()
    event_types: tuple[EventType, ...] = ()
    authorization_scopes: tuple[str, ...] = ()
    capabilities: frozenset[ModuleCapability] = frozenset()

    @field_validator(
        "content_schema_versions",
        "dependency_purposes",
        "entity_types",
        "relationship_types",
        "artifact_types",
        "source_plan_types",
        "reconciliation_types",
        "event_types",
        "authorization_scopes",
    )
    @classmethod
    def reject_duplicate_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Make ownership declarations deterministic and unambiguous."""

        if len(value) != len(set(value)):
            raise ValueError("descriptor collections cannot contain duplicates")
        return value


@dataclass(frozen=True, slots=True)
class ModuleRegistration:
    """A descriptor and the typed handlers backing its declared capabilities."""

    descriptor: ModuleDescriptor
    handlers: Mapping[ModuleCapability, Any] = field(default_factory=dict)
    router: Any | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "handlers", MappingProxyType(dict(self.handlers)))
