"""ADaM module registration metadata."""

from app.adam.models import AdamDependencySelection, AdamWorkbench
from app.api.clinical_aggregates import dependency_aggregate_router
from app.kernel.contracts import ModuleCapability, ModuleRegistration
from app.kernel.dependencies import SqlDependencyCapability
from app.kernel.descriptors import dependency_consumer_descriptor

DESCRIPTOR = dependency_consumer_descriptor("adam", "/api/v1/adams", "adam_workbench")
HANDLER = SqlDependencyCapability("adam", "adam_workbench", AdamWorkbench, AdamDependencySelection)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {
        capability: HANDLER
        for capability in ModuleCapability
        if capability in DESCRIPTOR.capabilities
    },
    dependency_aggregate_router("adam", "/studies/{study_id}/adams", "/adams/{adam_id}", "adam_id"),
)
