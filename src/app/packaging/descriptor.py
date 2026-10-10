"""Packaging module registration metadata."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration
from app.packaging.models import SubmissionPackage
from app.packaging.routes import router


@dataclass(frozen=True, slots=True)
class PackagingCapability:
    """Resolve immutable package records through their owning module boundary."""

    def resolve_entity(self, session: Session, entity_type: str, entity_id: UUID) -> UUID | None:
        if entity_type != "submission_package":
            return None
        package = session.get(SubmissionPackage, entity_id)
        return package.study_id if package is not None else None


DESCRIPTOR = ModuleDescriptor(
    module_key="packaging",
    module_version="0.5.0",
    api_prefix="/api/v1/submission-packages",
    content_schema_versions=("1.0.0",),
    entity_types=("submission_package",),
    artifact_types=("submission_package_zip", "submission_package_validation_report"),
    authorization_scopes=("packaging:read", "packaging:write"),
    capabilities=frozenset({ModuleCapability.ENTITY_RESOLUTION}),
)
HANDLER = PackagingCapability()
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {ModuleCapability.ENTITY_RESOLUTION: HANDLER},
    router,
)
