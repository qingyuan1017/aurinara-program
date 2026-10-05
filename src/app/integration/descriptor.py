"""Integration module registration metadata."""

from app.integration.events import IntegrationEventProjector
from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration

DESCRIPTOR = ModuleDescriptor(
    module_key="integration",
    module_version="0.1.0",
    api_prefix="/api/v1/integrations",
    event_types=("studies.created",),
    authorization_scopes=("integration:read", "integration:write"),
    capabilities=frozenset({ModuleCapability.OUTBOUND_EVENTS}),
)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {ModuleCapability.OUTBOUND_EVENTS: IntegrationEventProjector()},
)
