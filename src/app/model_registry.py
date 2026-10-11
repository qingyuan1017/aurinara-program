"""Import all persistence models for Alembic metadata discovery."""

from app.adam.models import (
    AdamAdrgRevision,
    AdamDefineRevision,
    AdamDependencySelection,
    AdamDerivationPlanRevision,
    AdamInputSelection,
    AdamSpecificationRevision,
    AdamWorkbench,
)
from app.artifacts.models import Artifact, ArtifactBuild, SourceFile
from app.common.idempotency import IdempotencyRecord
from app.common.outbox import OutboxEvent
from app.common.traceability import TraceLink
from app.documents.models import (
    Document,
    DocumentContent,
    DocumentDependencySelection,
    ProtocolEvidence,
    ProtocolUsdmDocument,
)
from app.execution.jobs import Job
from app.execution.models import ExecutionRun
from app.integration.models import (
    ExternalIdentifier,
    Integration,
    IntegrationDeliveryAttempt,
    IntegrationSecretVersion,
    IntegrationSubscription,
)
from app.packaging.models import SubmissionPackage
from app.platform.models import PlatformProjectionEvent
from app.raw.models import (
    RawDataset,
    RawDatasetFileBinding,
    RawDependencySelection,
    RawVariable,
    RawWorkbench,
)
from app.reconciliation.models import ReconciliationRun
from app.reference.models import ReferenceImportBatch, ReferenceRecord, ReferenceRevision
from app.review.models import ReviewComment, ReviewItem
from app.sdtm.models import (
    SdtmAcrfAnnotation,
    SdtmCsdrgRevision,
    SdtmDefineRevision,
    SdtmDependencySelection,
    SdtmDerivationPlanRevision,
    SdtmInputSelection,
    SdtmSpecificationRevision,
    SdtmWorkbench,
)
from app.standards.models import (
    StandardAsset,
    StandardProduct,
    StandardVersion,
    StandardVersionCompatibility,
)
from app.studies.models import Study, StudyMembership
from app.templates.models import TemplateFamily, TemplateVersion
from app.terminology.models import (
    TerminologyAsset,
    TerminologyCodelist,
    TerminologyExtension,
    TerminologyExtensionRevision,
    TerminologyExtensionTerm,
    TerminologyRelease,
    TerminologyReleaseCompatibility,
    TerminologyTerm,
)
from app.tlf.models import TlfAuthoringRevision, TlfDependencySelection, TlfWorkbench
from app.validation.models import ValidationRule, ValidationRulePack, ValidationRun

__all__ = [
    "Artifact",
    "ArtifactBuild",
    "AdamAdrgRevision",
    "AdamDependencySelection",
    "AdamDefineRevision",
    "AdamDerivationPlanRevision",
    "AdamInputSelection",
    "AdamSpecificationRevision",
    "AdamWorkbench",
    "Document",
    "DocumentContent",
    "DocumentDependencySelection",
    "ProtocolEvidence",
    "ProtocolUsdmDocument",
    "ExternalIdentifier",
    "Integration",
    "IntegrationDeliveryAttempt",
    "IntegrationSecretVersion",
    "IntegrationSubscription",
    "IdempotencyRecord",
    "Job",
    "ExecutionRun",
    "OutboxEvent",
    "PlatformProjectionEvent",
    "ReconciliationRun",
    "ReferenceRecord",
    "ReferenceImportBatch",
    "ReferenceRevision",
    "ReviewComment",
    "ReviewItem",
    "RawDependencySelection",
    "RawDataset",
    "RawDatasetFileBinding",
    "RawVariable",
    "RawWorkbench",
    "SdtmDependencySelection",
    "SdtmAcrfAnnotation",
    "SdtmCsdrgRevision",
    "SdtmDefineRevision",
    "SdtmDerivationPlanRevision",
    "SdtmInputSelection",
    "SdtmSpecificationRevision",
    "SdtmWorkbench",
    "SubmissionPackage",
    "StandardProduct",
    "StandardAsset",
    "StandardVersion",
    "StandardVersionCompatibility",
    "SourceFile",
    "Study",
    "StudyMembership",
    "TemplateFamily",
    "TemplateVersion",
    "TerminologyExtension",
    "TerminologyExtensionRevision",
    "TerminologyExtensionTerm",
    "TerminologyRelease",
    "TerminologyReleaseCompatibility",
    "TerminologyAsset",
    "TerminologyCodelist",
    "TerminologyTerm",
    "TlfDependencySelection",
    "TlfAuthoringRevision",
    "TlfWorkbench",
    "TraceLink",
    "ValidationRun",
    "ValidationRule",
    "ValidationRulePack",
]
