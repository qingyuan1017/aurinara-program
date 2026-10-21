"""Documents module registration metadata."""

from app.documents.models import Document, DocumentDependencySelection
from app.documents.routes import router
from app.documents.service import DOCUMENT_ARTIFACT_TYPES, DocumentsCapability
from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration

DESCRIPTOR = ModuleDescriptor(
    module_key="documents",
    module_version="0.2.0",
    api_prefix="/api/v1/documents",
    content_schema_versions=("1.0.0",),
    dependency_purposes=(
        "dependency_contract",
        "usdm_schema",
        "controlled_values",
        "study_context",
        "presentation",
    ),
    entity_types=(
        "document",
        "protocol_evidence",
        "protocol_objective",
        "protocol_endpoint",
        "sap_objective",
        "sap_endpoint",
        "sap_estimand",
        "sap_population",
        "sap_method",
        "document_record",
    ),
    relationship_types=("supports", "addresses", "analyzes", "references", "depends_on"),
    artifact_types=DOCUMENT_ARTIFACT_TYPES,
    authorization_scopes=("aurinara.documents.read", "aurinara.documents.write"),
    capabilities=frozenset(
        {
            ModuleCapability.DEPENDENCIES,
            ModuleCapability.STALENESS,
            ModuleCapability.VALIDATION,
            ModuleCapability.ARTIFACTS,
            ModuleCapability.ENTITY_RESOLUTION,
            ModuleCapability.REVIEW_TARGETS,
            ModuleCapability.RECONCILIATION_INPUTS,
            ModuleCapability.CONTEXT_EXPORT,
            ModuleCapability.TRACEABILITY,
            ModuleCapability.PACKAGING,
        }
    ),
)
HANDLER = DocumentsCapability(
    "documents", "document", Document, DocumentDependencySelection, requires_document_type=True
)
REGISTRATION = ModuleRegistration(
    DESCRIPTOR,
    {
        capability: HANDLER
        for capability in ModuleCapability
        if capability in DESCRIPTOR.capabilities
    },
    router,
)
