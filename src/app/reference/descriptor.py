"""Reference module registration metadata."""

from app.integration.events import IntegrationEventProjector
from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration

DESCRIPTOR = ModuleDescriptor(
    module_key="reference",
    module_version="0.1.0",
    api_prefix="/api/v1/references",
    event_types=("references.revised",),
    authorization_scopes=("reference:read", "reference:write"),
    capabilities=frozenset({ModuleCapability.OUTBOUND_EVENTS}),
)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {
        ModuleCapability.OUTBOUND_EVENTS: IntegrationEventProjector(
            frozenset(DESCRIPTOR.event_types)
        )
    },
)
