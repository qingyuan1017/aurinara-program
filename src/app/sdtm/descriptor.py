"""SDTM module registration metadata."""

from fastapi import APIRouter

from app.api.clinical_aggregates import dependency_aggregate_router
from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration
from app.sdtm.acrf import router as acrf_router
from app.sdtm.csdrg import router as csdrg_router
from app.sdtm.define import router as define_router
from app.sdtm.models import SdtmDependencySelection, SdtmWorkbench
from app.sdtm.routes import router as sdtm_router
from app.sdtm.service import SDTM_ARTIFACT_TYPES, SdtmCapability

DESCRIPTOR = ModuleDescriptor(
    module_key="sdtm",
    module_version="0.3.0",
    api_prefix="/api/v1/sdtms",
    content_schema_versions=("1.0.0",),
    dependency_purposes=("sdtm_ig", "define_xml", "controlled_values", "presentation"),
    entity_types=("sdtm_workbench", "sdtm_acrf_annotation", "sdtm_define", "sdtm_csdrg"),
    relationship_types=("annotates",),
    artifact_types=SDTM_ARTIFACT_TYPES,
    source_plan_types=("sdtm_derivation_plan",),
    reconciliation_types=("sdtm_define_outputs",),
    authorization_scopes=("sdtm:read", "sdtm:write"),
    capabilities=frozenset(
        {
            ModuleCapability.DEPENDENCIES,
            ModuleCapability.STALENESS,
            ModuleCapability.ENTITY_RESOLUTION,
            ModuleCapability.ARTIFACTS,
            ModuleCapability.RECONCILIATION_INPUTS,
            ModuleCapability.RECONCILIATION,
            ModuleCapability.CONTEXT_EXPORT,
            ModuleCapability.EXECUTION,
            ModuleCapability.PACKAGING,
        }
    ),
)
HANDLER = SdtmCapability("sdtm", "sdtm_workbench", SdtmWorkbench, SdtmDependencySelection)
router = APIRouter()
router.include_router(
    dependency_aggregate_router("sdtm", "/studies/{study_id}/sdtms", "/sdtms/{sdtm_id}", "sdtm_id")
)
router.include_router(sdtm_router)
router.include_router(acrf_router)
router.include_router(define_router)
router.include_router(csdrg_router)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {
        capability: HANDLER
        for capability in ModuleCapability
        if capability in DESCRIPTOR.capabilities
    },
    router,
)
