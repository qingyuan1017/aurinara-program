"""ADaM module registration metadata."""

from fastapi import APIRouter

from app.adam.adrg import router as adrg_router
from app.adam.define import router as define_router
from app.adam.models import AdamDependencySelection, AdamWorkbench
from app.adam.routes import router as adam_router
from app.adam.service import ADAM_ARTIFACT_TYPES, AdamCapability
from app.api.clinical_aggregates import dependency_aggregate_router
from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration

DESCRIPTOR = ModuleDescriptor(
    module_key="adam",
    module_version="0.4.0",
    api_prefix="/api/v1/adams",
    content_schema_versions=("1.0.0",),
    dependency_purposes=(
        "adam_ig",
        "define_xml",
        "controlled_values",
        "study_context",
        "presentation",
    ),
    entity_types=(
        "adam_workbench",
        "adam_dataset",
        "adam_variable",
        "adam_parameter",
        "adam_value_level",
        "adam_define",
        "adam_adrg",
    ),
    artifact_types=ADAM_ARTIFACT_TYPES,
    source_plan_types=("adam_derivation_plan",),
    reconciliation_types=("adam_define_outputs",),
    authorization_scopes=("adam:read", "adam:write"),
    capabilities=frozenset(
        {
            ModuleCapability.DEPENDENCIES,
            ModuleCapability.STALENESS,
            ModuleCapability.ENTITY_RESOLUTION,
            ModuleCapability.TRACEABILITY,
            ModuleCapability.ARTIFACTS,
            ModuleCapability.EXECUTION,
            ModuleCapability.RECONCILIATION_INPUTS,
            ModuleCapability.RECONCILIATION,
            ModuleCapability.PACKAGING,
        }
    ),
)
HANDLER = AdamCapability("adam", "adam_workbench", AdamWorkbench, AdamDependencySelection)
router = APIRouter()
router.include_router(
    dependency_aggregate_router("adam", "/studies/{study_id}/adams", "/adams/{adam_id}", "adam_id")
)
router.include_router(adam_router)
router.include_router(define_router)
router.include_router(adrg_router)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {
        capability: HANDLER
        for capability in ModuleCapability
        if capability in DESCRIPTOR.capabilities
    },
    router,
)
