"""SDTM module registration metadata."""

from fastapi import APIRouter

from app.api.clinical_aggregates import dependency_aggregate_router
from app.integration.cdisc_library import CdiscLibraryReaderFactory
from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration
from app.sdtm.models import SdtmDependencySelection, SdtmWorkbench
from app.sdtm.proposals import SDTM_PROPOSAL_TYPES, SdtmProposalCapability
from app.sdtm.routes import router as feature_router
from app.sdtm.service import SDTM_ARTIFACT_TYPES, SdtmCapability

DESCRIPTOR = ModuleDescriptor(
    module_key="sdtm",
    module_version="0.3.0",
    api_prefix="/api/v1/sdtm-workbenches",
    content_schema_versions=("2.0.0",),
    dependency_purposes=("sdtm_ig", "define_xml", "controlled_values", "presentation"),
    entity_types=(
        "sdtm_workbench",
        "sdtm_imported_domain",
        "sdtm_acrf_annotation",
        "sdtm_define",
        "sdtm_csdrg",
    ),
    relationship_types=("annotates",),
    artifact_types=SDTM_ARTIFACT_TYPES,
    source_plan_types=("sdtm_code_revision", "sdtm_imported_domain"),
    proposal_types=SDTM_PROPOSAL_TYPES,
    reconciliation_types=("sdtm_define_outputs",),
    authorization_scopes=("aurinara.sdtm.read", "aurinara.sdtm.write"),
    capabilities=frozenset(
        {
            ModuleCapability.DEPENDENCIES,
            ModuleCapability.STALENESS,
            ModuleCapability.PROPOSALS,
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
    dependency_aggregate_router(
        "sdtm",
        "/studies/{study_id}/sdtm-workbenches",
        "/sdtm-workbenches/{sdtm_id}",
        "sdtm_id",
    )
)
router.include_router(feature_router)

def build_registration(
    reader_factory: CdiscLibraryReaderFactory | None = None,
) -> ModuleRegistration:
    """Build an SDTM registration with the deployment's live CDISC boundary."""

    proposal_handler = SdtmProposalCapability(reader_factory)
    return ModuleRegistration(
        DESCRIPTOR,
        {
            capability: (
                proposal_handler if capability == ModuleCapability.PROPOSALS else HANDLER
            )
            for capability in ModuleCapability
            if capability in DESCRIPTOR.capabilities
        },
        router,
    )


REGISTRATION = build_registration()
