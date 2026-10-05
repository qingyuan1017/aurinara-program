"""Raw module registration metadata."""

from app.api.clinical_aggregates import dependency_aggregate_router
from app.kernel.contracts import ModuleCapability, ModuleRegistration
from app.kernel.dependencies import SqlDependencyCapability
from app.kernel.descriptors import dependency_consumer_descriptor
from app.raw.models import RawDependencySelection, RawWorkbench

DESCRIPTOR = dependency_consumer_descriptor("raw", "/api/v1/raw", "raw_workbench")
HANDLER = SqlDependencyCapability("raw", "raw_workbench", RawWorkbench, RawDependencySelection)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {
        capability: HANDLER
        for capability in ModuleCapability
        if capability in DESCRIPTOR.capabilities
    },
    dependency_aggregate_router("raw", "/studies/{study_id}/raw", "/raw/{raw_id}", "raw_id"),
)
