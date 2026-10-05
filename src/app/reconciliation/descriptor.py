"""Reconciliation module registration metadata."""

from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration


class ReconciliationArtifactCapability:
    """Marker for worker-owned immutable reconciliation report builders."""


DESCRIPTOR = ModuleDescriptor(
    module_key="reconciliation",
    module_version="0.1.0",
    api_prefix="/api/v1/reconciliation-runs",
    artifact_types=("reconciliation_report_json",),
    authorization_scopes=("reconciliation:read", "reconciliation:write"),
    capabilities=frozenset({ModuleCapability.ARTIFACTS}),
)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {ModuleCapability.ARTIFACTS: ReconciliationArtifactCapability()},
)
