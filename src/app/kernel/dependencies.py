"""Typed dependency-selection contracts and module capability handler."""

import json
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.etag import require_matching_etag
from app.common.problems import ProblemException
from app.reference.models import ReferenceRecord, ReferenceRevision
from app.standards.models import StandardVersion, StandardVersionCompatibility
from app.templates.models import TemplateVersion
from app.terminology.models import (
    TerminologyExtension,
    TerminologyExtensionRevision,
    TerminologyRelease,
    TerminologyReleaseCompatibility,
)


class StandardSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    purpose: str
    standard_version_id: UUID


class TerminologySelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: str
    terminology_release_id: UUID
    terminology_extension_revision_ids: tuple[UUID, ...] = ()


class ReferenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    purpose: str
    reference_id: UUID
    reference_revision_id: UUID


class TemplateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    purpose: str
    artifact_type: str | None = None
    template_version_id: UUID


class DependencySelectionInput(BaseModel):
    """Complete exact dependency replacement authored by a user."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    standards: tuple[StandardSelection, ...] = ()
    terminology: tuple[TerminologySelection, ...] = ()
    references: tuple[ReferenceSelection, ...] = ()
    templates: tuple[TemplateSelection, ...] = ()
    reaffirmation_reason: str | None = None


class DependencySelectionResponse(DependencySelectionInput):
    """Persisted dependency snapshot and compatibility decision."""

    revision: int
    state: str
    fingerprint: str


class AggregateCreate(BaseModel):
    """Minimal Phase 1 clinical aggregate shell."""

    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    document_type: str | None = None


class AggregateResponse(BaseModel):
    """Common clinical aggregate identity envelope."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    study_id: UUID
    code: str
    name: str
    status: str
    revision: int
    document_type: str | None = None


class DependencyCapability(Protocol):
    """Service boundary implemented by every dependency-consuming module."""

    module_key: str
    entity_type: str

    def create(self, session: Session, study_id: UUID, command: AggregateCreate) -> Any: ...
    def list(self, session: Session, study_id: UUID) -> tuple[Any, ...]: ...
    def require(self, session: Session, aggregate_id: UUID, study_id: UUID) -> Any: ...
    def get_selection(
        self, session: Session, aggregate_id: UUID, study_id: UUID
    ) -> DependencySelectionResponse: ...
    def replace_selection(
        self,
        session: Session,
        aggregate_id: UUID,
        study_id: UUID,
        command: DependencySelectionInput,
        if_match: str | None,
    ) -> tuple[Any, DependencySelectionResponse]: ...
    def resolve_entity(
        self, session: Session, entity_type: str, entity_id: UUID
    ) -> UUID | None: ...
    def resolve_reconciliation_input(
        self, session: Session, entity_type: str, entity_id: UUID, revision: int
    ) -> UUID | None: ...
    def mark_dependency_refresh(
        self, session: Session, dependency_id: UUID
    ) -> tuple[UUID, ...]: ...

    def build_artifact_payload(
        self, session: Session, aggregate_id: UUID, study_id: UUID, artifact_type: str
    ) -> dict[str, object]: ...

    def render_artifact(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> "RenderedArtifact": ...


@dataclass(frozen=True, slots=True)
class RenderedArtifact:
    """Module-rendered immutable bytes plus safe publication metadata."""

    data: bytes
    filename: str
    media_type: str
    manifest: dict[str, object]
    validation_run_id: UUID | None = None
    reconciliation_run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SqlDependencyCapability:
    """Typed adapter over module-owned aggregate and selection tables."""

    module_key: str
    entity_type: str
    aggregate_model: Any
    selection_model: Any
    requires_document_type: bool = False

    def create(self, session: Session, study_id: UUID, command: AggregateCreate) -> Any:
        values: dict[str, object] = {
            "study_id": study_id,
            "code": command.code,
            "name": command.name,
        }
        if self.requires_document_type:
            if command.document_type is None:
                raise ProblemException(
                    status_code=422,
                    code="document_type_required",
                    title="Document type is required",
                    detail="Documents require an explicit document_type.",
                )
            values["document_type"] = command.document_type
        aggregate = self.aggregate_model(**values)
        session.add(aggregate)
        session.flush()
        selection = self.selection_model(
            aggregate_id=aggregate.id,
            study_id=study_id,
            revision=1,
            state="current",
            payload=DependencySelectionInput().model_dump(mode="json"),
            fingerprint=fingerprint(DependencySelectionInput().model_dump(mode="json")),
        )
        session.add(selection)
        return aggregate

    def list(self, session: Session, study_id: UUID) -> tuple[Any, ...]:
        model = self.aggregate_model
        return tuple(
            session.scalars(
                select(model)
                .where(model.study_id == study_id)
                .order_by(model.created_at.desc(), model.id.desc())
            )
        )

    def require(self, session: Session, aggregate_id: UUID, study_id: UUID) -> Any:
        aggregate = session.get(self.aggregate_model, aggregate_id)
        if aggregate is None or aggregate.study_id != study_id:
            raise ProblemException(
                status_code=404,
                code=f"{self.module_key}_not_found",
                title="Clinical aggregate not found",
                detail="The aggregate does not exist in this study.",
            )
        return aggregate

    def _selection(self, session: Session, aggregate_id: UUID, study_id: UUID) -> Any:
        model = self.selection_model
        selection = session.scalar(
            select(model).where(model.aggregate_id == aggregate_id, model.study_id == study_id)
        )
        if selection is None:
            raise RuntimeError("aggregate has no dependency selection")
        return selection

    def get_selection(
        self, session: Session, aggregate_id: UUID, study_id: UUID
    ) -> DependencySelectionResponse:
        self.require(session, aggregate_id, study_id)
        record = self._selection(session, aggregate_id, study_id)
        payload = dict(record.payload)
        payload.pop("reaffirmation_reason", None)
        return DependencySelectionResponse(
            **payload,
            reaffirmation_reason=None,
            revision=record.revision,
            state=record.state,
            fingerprint=record.fingerprint,
        )

    def replace_selection(
        self,
        session: Session,
        aggregate_id: UUID,
        study_id: UUID,
        command: DependencySelectionInput,
        if_match: str | None,
    ) -> tuple[Any, DependencySelectionResponse]:
        aggregate = self.require(session, aggregate_id, study_id)
        require_matching_etag(if_match, aggregate.revision)
        self._validate_exact_selection(session, study_id, command)
        record = self._selection(session, aggregate_id, study_id)
        record.revision += 1
        record.state = "current"
        record.payload = command.model_dump(mode="json", exclude={"reaffirmation_reason"})
        record.fingerprint = fingerprint(record.payload)
        aggregate.revision += 1
        return aggregate, self.get_selection(session, aggregate_id, study_id)

    def _validate_exact_selection(
        self, session: Session, study_id: UUID, command: DependencySelectionInput
    ) -> None:
        errors: list[dict[str, object]] = []
        if len({item.purpose for item in command.standards}) != len(command.standards):
            errors.append({"code": "duplicate_standard_purpose"})
        if len({item.scope for item in command.terminology}) != len(command.terminology):
            errors.append({"code": "duplicate_terminology_scope"})
        if len({item.purpose for item in command.references}) != len(command.references):
            errors.append({"code": "duplicate_reference_purpose"})
        template_keys = [(item.purpose, item.artifact_type) for item in command.templates]
        if len(set(template_keys)) != len(template_keys):
            errors.append({"code": "duplicate_template_purpose"})
        for standard_item in command.standards:
            version = session.get(StandardVersion, standard_item.standard_version_id)
            if (
                version is None
                or self.module_key not in version.applicable_modules
                or standard_item.purpose not in version.purposes
            ):
                errors.append(
                    {
                        "code": "standard_version_invalid",
                        "id": str(standard_item.standard_version_id),
                    }
                )
            elif version.lifecycle not in {"active", "deprecated"}:
                raise _dependency_unavailable("standard", standard_item.standard_version_id)
        selected_standard_ids = {item.standard_version_id for item in command.standards}
        if selected_standard_ids:
            required_relationships = session.scalars(
                select(StandardVersionCompatibility).where(
                    StandardVersionCompatibility.source_version_id.in_(selected_standard_ids),
                    StandardVersionCompatibility.required.is_(True),
                )
            )
            for relationship in required_relationships:
                if relationship.target_version_id not in selected_standard_ids:
                    errors.append(
                        {
                            "code": "required_standard_version_missing",
                            "source_id": str(relationship.source_version_id),
                            "required_id": str(relationship.target_version_id),
                            "relationship": relationship.relationship,
                        }
                    )
        selected_standard_by_purpose = {
            item.purpose: item.standard_version_id for item in command.standards
        }
        for terminology_item in command.terminology:
            release = session.get(TerminologyRelease, terminology_item.terminology_release_id)
            if release is None or self.module_key not in release.applicable_modules:
                errors.append(
                    {
                        "code": "terminology_release_invalid",
                        "id": str(terminology_item.terminology_release_id),
                    }
                )
            elif release.lifecycle not in {"active", "deprecated"}:
                raise _dependency_unavailable(
                    "terminology", terminology_item.terminology_release_id
                )
            compatibility_rows = list(
                session.scalars(
                    select(TerminologyReleaseCompatibility).where(
                        TerminologyReleaseCompatibility.release_id
                        == terminology_item.terminology_release_id,
                        TerminologyReleaseCompatibility.terminology_scope == terminology_item.scope,
                    )
                )
            )
            if compatibility_rows and not any(
                selected_standard_by_purpose.get(item.standard_purpose) == item.standard_version_id
                for item in compatibility_rows
            ):
                errors.append(
                    {
                        "code": "terminology_standard_incompatible",
                        "id": str(terminology_item.terminology_release_id),
                        "scope": terminology_item.scope,
                    }
                )
            for revision_id in terminology_item.terminology_extension_revision_ids:
                extension_revision = session.get(TerminologyExtensionRevision, revision_id)
                extension = (
                    session.get(TerminologyExtension, extension_revision.extension_id)
                    if extension_revision is not None
                    else None
                )
                if (
                    extension_revision is None
                    or extension_revision.study_id != study_id
                    or extension is None
                    or extension.study_id != study_id
                    or extension.base_release_id != terminology_item.terminology_release_id
                    or extension.status != "active"
                ):
                    errors.append(
                        {"code": "terminology_extension_revision_invalid", "id": str(revision_id)}
                    )
        for reference_item in command.references:
            reference = session.get(ReferenceRecord, reference_item.reference_id)
            reference_revision = session.get(
                ReferenceRevision, reference_item.reference_revision_id
            )
            if (
                reference is None
                or reference_revision is None
                or reference.study_id != study_id
                or reference_revision.study_id != study_id
                or reference_revision.reference_id != reference.id
                or reference.status != "active"
            ):
                errors.append(
                    {
                        "code": "reference_revision_invalid",
                        "id": str(reference_item.reference_revision_id),
                    }
                )
        for template_item in command.templates:
            template_version = session.get(TemplateVersion, template_item.template_version_id)
            if (
                template_version is None
                or self.module_key not in template_version.applicable_modules
                or (
                    template_item.artifact_type is not None
                    and template_item.artifact_type not in template_version.artifact_types
                )
                or "1.0.0" not in template_version.content_schema_versions
            ):
                errors.append(
                    {
                        "code": "template_version_invalid",
                        "id": str(template_item.template_version_id),
                    }
                )
            elif template_version.lifecycle not in {"active", "deprecated"}:
                raise _dependency_unavailable("template", template_item.template_version_id)
        if errors:
            raise ProblemException(
                status_code=422,
                code="dependency_selection_invalid",
                title="Dependency selection is invalid",
                detail="One or more exact dependency selections cannot be resolved.",
                issues=errors,
            )

    def resolve_entity(self, session: Session, entity_type: str, entity_id: UUID) -> UUID | None:
        if entity_type != self.entity_type:
            return None
        aggregate = session.get(self.aggregate_model, entity_id)
        return cast(UUID, aggregate.study_id) if aggregate is not None else None

    def resolve_reconciliation_input(
        self, session: Session, entity_type: str, entity_id: UUID, revision: int
    ) -> UUID | None:
        if entity_type != self.entity_type:
            return None
        aggregate = session.get(self.aggregate_model, entity_id)
        if aggregate is None or int(aggregate.revision) != revision:
            return None
        return cast(UUID, aggregate.study_id)

    def mark_dependency_refresh(self, session: Session, dependency_id: UUID) -> tuple[UUID, ...]:
        model = self.selection_model
        affected: list[UUID] = []
        records: Any = session.scalars(select(model))
        for record in records:
            if str(dependency_id) in str(record.payload):
                record.state = "dependency_refresh_required"
                affected.append(cast(UUID, record.aggregate_id))
        return tuple(affected)

    def build_artifact_payload(
        self, session: Session, aggregate_id: UUID, study_id: UUID, artifact_type: str
    ) -> dict[str, object]:
        """Build a deterministic dependency manifest owned by this module."""

        expected_type = f"{self.module_key}_dependency_manifest"
        if artifact_type != expected_type:
            raise ProblemException(
                status_code=422,
                code="artifact_type_unsupported",
                title="Artifact type is unsupported",
                detail=f"The module does not build '{artifact_type}'.",
            )
        aggregate = self.require(session, aggregate_id, study_id)
        selection = self.get_selection(session, aggregate_id, study_id)
        if selection.state != "current":
            raise ProblemException(
                status_code=409,
                code="dependency_refresh_required",
                title="Dependency refresh is required",
                detail="Refresh or explicitly reaffirm the exact dependency selection first.",
            )
        return {
            "schema_version": "1.0.0",
            "module": self.module_key,
            "owner": {
                "entity_type": self.entity_type,
                "entity_id": str(aggregate.id),
                "revision": aggregate.revision,
            },
            "dependency_selection": selection.model_dump(mode="json"),
            "resolved_dependencies": self._resolve_manifest(session, selection),
        }

    def _resolve_manifest(
        self, session: Session, selection: DependencySelectionResponse
    ) -> dict[str, object]:
        """Freeze provider versions, lifecycle decisions, and checksums for an operation."""

        standards = []
        for standard_selection in selection.standards:
            standard_version = session.get(StandardVersion, standard_selection.standard_version_id)
            if standard_version is None:
                raise RuntimeError("validated standard version is missing")
            relationships = [
                {
                    "target_version_id": str(item.target_version_id),
                    "relationship": item.relationship,
                    "required": item.required,
                    "evidence": item.evidence,
                }
                for item in session.scalars(
                    select(StandardVersionCompatibility).where(
                        StandardVersionCompatibility.source_version_id == standard_version.id
                    )
                )
            ]
            standards.append(
                {
                    "purpose": standard_selection.purpose,
                    "id": str(standard_version.id),
                    "version": standard_version.version,
                    "lifecycle": standard_version.lifecycle,
                    "checksum": standard_version.checksum,
                    "compatibility": {
                        "legacy": standard_version.compatibility,
                        "relationships": relationships,
                    },
                }
            )
        terminology = []
        for terminology_selection in selection.terminology:
            release = session.get(TerminologyRelease, terminology_selection.terminology_release_id)
            if release is None:
                raise RuntimeError("validated terminology release is missing")
            extensions = []
            for revision_id in terminology_selection.terminology_extension_revision_ids:
                extension_revision = session.get(TerminologyExtensionRevision, revision_id)
                if extension_revision is None:
                    raise RuntimeError("validated terminology extension revision is missing")
                extensions.append(
                    {
                        "id": str(extension_revision.id),
                        "revision": extension_revision.revision,
                        "fingerprint": extension_revision.fingerprint,
                    }
                )
            compatibility = [
                {
                    "standard_version_id": str(item.standard_version_id),
                    "terminology_scope": item.terminology_scope,
                    "standard_purpose": item.standard_purpose,
                    "relationship": item.relationship,
                    "evidence": item.evidence,
                }
                for item in session.scalars(
                    select(TerminologyReleaseCompatibility).where(
                        TerminologyReleaseCompatibility.release_id == release.id,
                        TerminologyReleaseCompatibility.terminology_scope
                        == terminology_selection.scope,
                    )
                )
            ]
            terminology.append(
                {
                    "scope": terminology_selection.scope,
                    "id": str(release.id),
                    "version": release.version,
                    "lifecycle": release.lifecycle,
                    "checksum": release.checksum,
                    "compatibility": compatibility,
                    "extensions": extensions,
                }
            )
        references = []
        for reference_selection in selection.references:
            reference_revision = session.get(
                ReferenceRevision, reference_selection.reference_revision_id
            )
            if reference_revision is None:
                raise RuntimeError("validated Reference revision is missing")
            references.append(
                {
                    "purpose": reference_selection.purpose,
                    "reference_id": str(reference_selection.reference_id),
                    "revision_id": str(reference_revision.id),
                    "revision": reference_revision.revision,
                    "fingerprint": reference_revision.fingerprint,
                }
            )
        templates = []
        for template_selection in selection.templates:
            template_version = session.get(TemplateVersion, template_selection.template_version_id)
            if template_version is None:
                raise RuntimeError("validated Template version is missing")
            templates.append(
                {
                    "purpose": template_selection.purpose,
                    "artifact_type": template_selection.artifact_type,
                    "id": str(template_version.id),
                    "version": template_version.version,
                    "lifecycle": template_version.lifecycle,
                    "checksum": template_version.checksum,
                    "renderer_versions": template_version.renderer_versions,
                }
            )
        return {
            "compatibility_decision": "compatible",
            "standards": standards,
            "terminology": terminology,
            "references": references,
            "templates": templates,
        }

    def render_artifact(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> RenderedArtifact:
        """Render the foundation dependency manifest as canonical JSON."""

        del storage
        data = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        artifact_type = str(payload.get("artifact_type", f"{self.module_key}_dependency_manifest"))
        return RenderedArtifact(
            data=data,
            filename=f"{artifact_type}.json",
            media_type="application/json",
            manifest=payload,
        )


def _dependency_unavailable(kind: str, identifier: UUID) -> ProblemException:
    return ProblemException(
        status_code=409,
        code="dependency_unavailable",
        title="Selected dependency is unavailable",
        detail=f"The selected {kind} version '{identifier}' is unavailable.",
    )
