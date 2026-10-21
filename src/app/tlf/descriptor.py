"""TLF module registration metadata."""

from fastapi import APIRouter

from app.api.clinical_aggregates import dependency_aggregate_router
from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration
from app.tlf.models import TlfDependencySelection, TlfWorkbench
from app.tlf.routes import router as tlf_router
from app.tlf.service import TLF_ARTIFACT_TYPES, TlfCapability

DESCRIPTOR = ModuleDescriptor(
    module_key="tlf",
    module_version="0.5.0",
    api_prefix="/api/v1/tlfs",
    content_schema_versions=("1.0.0",),
    dependency_purposes=(
        "analysis_reporting_standard",
        "controlled_values",
        "study_context",
        "presentation",
    ),
    entity_types=("tlf_workbench", "tlf_output"),
    artifact_types=TLF_ARTIFACT_TYPES,
    source_plan_types=("tlf_program_plan",),
    authorization_scopes=("aurinara.tlf.read", "aurinara.tlf.write"),
    capabilities=frozenset(
        {
            ModuleCapability.DEPENDENCIES,
            ModuleCapability.STALENESS,
            ModuleCapability.VALIDATION,
            ModuleCapability.ARTIFACTS,
            ModuleCapability.ENTITY_RESOLUTION,
            ModuleCapability.RECONCILIATION_INPUTS,
            ModuleCapability.COMPILATION,
            ModuleCapability.EXECUTION,
            ModuleCapability.PACKAGING,
        }
    ),
)
HANDLER = TlfCapability("tlf", "tlf_workbench", TlfWorkbench, TlfDependencySelection)
router = APIRouter()
router.include_router(
    dependency_aggregate_router("tlf", "/studies/{study_id}/tlfs", "/tlfs/{tlf_id}", "tlf_id")
)
router.include_router(tlf_router)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {
        capability: HANDLER
        for capability in ModuleCapability
        if capability in DESCRIPTOR.capabilities
    },
    router,
)
