"""Raw module registration metadata."""

from fastapi import APIRouter

from app.api.clinical_aggregates import dependency_aggregate_router
from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration
from app.raw.models import RawDependencySelection, RawWorkbench
from app.raw.routes import router as raw_router
from app.raw.service import RAW_ARTIFACT_TYPES, RawCapability

DESCRIPTOR = ModuleDescriptor(
    module_key="raw",
    module_version="0.4.0",
    api_prefix="/api/v1/raw",
    content_schema_versions=("1.0.0",),
    dependency_purposes=("raw_metadata", "controlled_values", "study_context", "presentation"),
    entity_types=("raw_workbench", "raw_dataset", "raw_variable"),
    relationship_types=("contains", "maps_to", "derived_from"),
    artifact_types=RAW_ARTIFACT_TYPES,
    reconciliation_types=("raw_source_schema",),
    authorization_scopes=("raw:read", "raw:write"),
    capabilities=frozenset(
        {
            ModuleCapability.DEPENDENCIES,
            ModuleCapability.STALENESS,
            ModuleCapability.VALIDATION,
            ModuleCapability.ARTIFACTS,
            ModuleCapability.ENTITY_RESOLUTION,
            ModuleCapability.REVIEW_TARGETS,
            ModuleCapability.RECONCILIATION_INPUTS,
            ModuleCapability.RECONCILIATION,
            ModuleCapability.CONTEXT_EXPORT,
            ModuleCapability.TRACEABILITY,
            ModuleCapability.PACKAGING,
        }
    ),
)
HANDLER = RawCapability("raw", "raw_workbench", RawWorkbench, RawDependencySelection)
router = APIRouter()
router.include_router(
    dependency_aggregate_router("raw", "/studies/{study_id}/raw", "/raw/{raw_id}", "raw_id")
)
router.include_router(raw_router)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {
        capability: HANDLER
        for capability in ModuleCapability
        if capability in DESCRIPTOR.capabilities
    },
    router,
)
