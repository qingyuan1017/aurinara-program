"""SDTM module registration metadata."""

from app.api.clinical_aggregates import dependency_aggregate_router
from app.kernel.contracts import ModuleCapability, ModuleRegistration
from app.kernel.dependencies import SqlDependencyCapability
from app.kernel.descriptors import dependency_consumer_descriptor
from app.sdtm.models import SdtmDependencySelection, SdtmWorkbench

DESCRIPTOR = dependency_consumer_descriptor("sdtm", "/api/v1/sdtms", "sdtm_workbench")
HANDLER = SqlDependencyCapability("sdtm", "sdtm_workbench", SdtmWorkbench, SdtmDependencySelection)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {
        capability: HANDLER
        for capability in ModuleCapability
        if capability in DESCRIPTOR.capabilities
    },
    dependency_aggregate_router("sdtm", "/studies/{study_id}/sdtms", "/sdtms/{sdtm_id}", "sdtm_id"),
)
