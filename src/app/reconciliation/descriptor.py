"""Reconciliation module registration metadata."""

from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration
from app.reconciliation.service import ExactInputReconciliationCapability


class ReconciliationArtifactCapability:
    """Marker for worker-owned immutable reconciliation report builders."""


DESCRIPTOR = ModuleDescriptor(
    module_key="reconciliation",
    module_version="0.1.0",
    api_prefix="/api/v1/reconciliation-runs",
    artifact_types=("reconciliation_report_json",),
    reconciliation_types=("dependency_snapshot",),
    authorization_scopes=("reconciliation:read", "reconciliation:write"),
    capabilities=frozenset({ModuleCapability.ARTIFACTS, ModuleCapability.RECONCILIATION}),
)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {
        ModuleCapability.ARTIFACTS: ReconciliationArtifactCapability(),
        ModuleCapability.RECONCILIATION: ExactInputReconciliationCapability(),
    },
)
