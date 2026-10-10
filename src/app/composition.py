"""Application composition root for reviewed module registrations."""

from app.adam.descriptor import REGISTRATION as ADAM_REGISTRATION
from app.documents.descriptor import REGISTRATION as DOCUMENTS_REGISTRATION
from app.integration.descriptor import REGISTRATION as INTEGRATION_REGISTRATION
from app.kernel.contracts import ModuleRegistration
from app.kernel.registry import ModuleRegistry
from app.packaging.descriptor import REGISTRATION as PACKAGING_REGISTRATION
from app.raw.descriptor import REGISTRATION as RAW_REGISTRATION
from app.reconciliation.descriptor import REGISTRATION as RECONCILIATION_REGISTRATION
from app.reference.descriptor import REGISTRATION as REFERENCE_REGISTRATION
from app.review.descriptor import DESCRIPTOR as REVIEW_DESCRIPTOR
from app.sdtm.descriptor import REGISTRATION as SDTM_REGISTRATION
from app.standards.descriptor import DESCRIPTOR as STANDARDS_DESCRIPTOR
from app.templates.descriptor import DESCRIPTOR as TEMPLATES_DESCRIPTOR
from app.terminology.descriptor import REGISTRATION as TERMINOLOGY_REGISTRATION
from app.tlf.descriptor import REGISTRATION as TLF_REGISTRATION
from app.validation.descriptor import DESCRIPTOR as VALIDATION_DESCRIPTOR

BUILTIN_REGISTRATIONS = (
    ADAM_REGISTRATION,
    DOCUMENTS_REGISTRATION,
    INTEGRATION_REGISTRATION,
    PACKAGING_REGISTRATION,
    RAW_REGISTRATION,
    RECONCILIATION_REGISTRATION,
    REFERENCE_REGISTRATION,
    REVIEW_DESCRIPTOR,
    SDTM_REGISTRATION,
    STANDARDS_DESCRIPTOR,
    TEMPLATES_DESCRIPTOR,
    TERMINOLOGY_REGISTRATION,
    TLF_REGISTRATION,
    VALIDATION_DESCRIPTOR,
)

BUILTIN_DESCRIPTORS = tuple(
    registration.descriptor if isinstance(registration, ModuleRegistration) else registration
    for registration in BUILTIN_REGISTRATIONS
)


def build_module_registry() -> ModuleRegistry:
    """Compose, validate, and seal all reviewed built-in modules."""

    registry = ModuleRegistry()
    registry.register_all(
        registration
        if isinstance(registration, ModuleRegistration)
        else ModuleRegistration(registration)
        for registration in BUILTIN_REGISTRATIONS
    )
    registry.seal()
    return registry
