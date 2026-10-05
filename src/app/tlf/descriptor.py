"""TLF module registration metadata."""

from app.api.clinical_aggregates import dependency_aggregate_router
from app.kernel.contracts import ModuleCapability, ModuleRegistration
from app.kernel.dependencies import SqlDependencyCapability
from app.kernel.descriptors import dependency_consumer_descriptor
from app.tlf.models import TlfDependencySelection, TlfWorkbench

DESCRIPTOR = dependency_consumer_descriptor("tlf", "/api/v1/tlfs", "tlf_workbench")
HANDLER = SqlDependencyCapability("tlf", "tlf_workbench", TlfWorkbench, TlfDependencySelection)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {
        capability: HANDLER
        for capability in ModuleCapability
        if capability in DESCRIPTOR.capabilities
    },
    dependency_aggregate_router("tlf", "/studies/{study_id}/tlfs", "/tlfs/{tlf_id}", "tlf_id"),
)
