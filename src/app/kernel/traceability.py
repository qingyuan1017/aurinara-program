"""Verified cross-module traceability operations over registered capabilities."""

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.common.traceability import TraceLink
from app.kernel.contracts import ModuleCapability
from app.kernel.dependencies import DependencyCapability
from app.kernel.registry import ModuleRegistry, ModuleRegistryError


@dataclass(frozen=True, slots=True)
class TraceEndpoint:
    """One exact entity endpoint owned by a registered module."""

    module: str
    entity_type: str
    entity_id: UUID


@dataclass(frozen=True, slots=True)
class TraceCommand:
    """One requested directed relationship between typed endpoints."""

    relationship_type: str
    source: TraceEndpoint
    target: TraceEndpoint


class TraceabilityError(RuntimeError):
    """Raised when an endpoint or relationship is not registered and resolvable."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class TraceabilityService:
    """Validate and persist normalized trace links without committing transactions."""

    @staticmethod
    def _resolve(
        session: Session,
        registry: ModuleRegistry,
        endpoint: TraceEndpoint,
    ) -> UUID | None:
        if registry.owner_of("entity_types", endpoint.entity_type) != endpoint.module:
            return None
        try:
            handler = cast(
                DependencyCapability,
                registry.require_handler(endpoint.module, ModuleCapability.ENTITY_RESOLUTION),
            )
        except ModuleRegistryError:
            return None
        return handler.resolve_entity(session, endpoint.entity_type, endpoint.entity_id)

    def validate(
        self,
        session: Session,
        registry: ModuleRegistry,
        study_id: UUID,
        command: TraceCommand,
    ) -> None:
        """Verify relationship ownership plus exact same-study endpoints."""

        relationship_owner = registry.owner_of("relationship_types", command.relationship_type)
        if relationship_owner is None:
            raise TraceabilityError(
                "trace_relationship_invalid",
                "The relationship type is not registered.",
            )
        descriptor = registry.get(relationship_owner)
        if descriptor is None or ModuleCapability.TRACEABILITY not in descriptor.capabilities:
            raise TraceabilityError(
                "trace_relationship_invalid",
                "The relationship owner does not expose traceability capability.",
            )
        if (
            self._resolve(session, registry, command.source) != study_id
            or self._resolve(session, registry, command.target) != study_id
        ):
            raise TraceabilityError(
                "trace_endpoint_invalid",
                "Both endpoints must exist in the same study.",
            )

    @staticmethod
    def _matching_statement(study_id: UUID, command: TraceCommand) -> Select[TraceLink]:
        return select(TraceLink).where(
            TraceLink.study_id == study_id,
            TraceLink.relationship_type == command.relationship_type,
            TraceLink.source_module == command.source.module,
            TraceLink.source_entity_type == command.source.entity_type,
            TraceLink.source_entity_id == command.source.entity_id,
            TraceLink.target_module == command.target.module,
            TraceLink.target_entity_type == command.target.entity_type,
            TraceLink.target_entity_id == command.target.entity_id,
        )

    def add(
        self,
        session: Session,
        registry: ModuleRegistry,
        study_id: UUID,
        command: TraceCommand,
        created_by: str,
        *,
        allow_existing: bool = False,
    ) -> TraceLink:
        """Validate and add a link, returning an existing exact link idempotently."""

        self.validate(session, registry, study_id, command)
        existing = session.scalar(self._matching_statement(study_id, command))
        if existing is not None:
            if allow_existing:
                return existing
            raise TraceabilityError(
                "duplicate_trace_link", "The exact relationship already exists."
            )
        link = TraceLink(
            study_id=study_id,
            relationship_type=command.relationship_type,
            source_module=command.source.module,
            source_entity_type=command.source.entity_type,
            source_entity_id=command.source.entity_id,
            target_module=command.target.module,
            target_entity_type=command.target.entity_type,
            target_entity_id=command.target.entity_id,
            created_by=created_by,
        )
        session.add(link)
        return link

    def replace(
        self,
        session: Session,
        registry: ModuleRegistry,
        study_id: UUID,
        previous: tuple[TraceCommand, ...],
        current: tuple[TraceCommand, ...],
        created_by: str,
    ) -> tuple[TraceLink, ...]:
        """Atomically replace one aggregate revision's declared normalized links."""

        for command in current:
            self.validate(session, registry, study_id, command)
        current_keys = set(current)
        for command in previous:
            if command in current_keys:
                continue
            link = session.scalar(self._matching_statement(study_id, command))
            if link is not None:
                session.delete(link)
        return tuple(
            self.add(
                session,
                registry,
                study_id,
                command,
                created_by,
                allow_existing=True,
            )
            for command in current
        )
