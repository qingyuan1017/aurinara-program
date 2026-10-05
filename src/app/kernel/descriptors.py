"""Factories for concise reviewed module descriptors."""

from app.kernel.contracts import ModuleCapability, ModuleDescriptor


def foundation_descriptor(module_key: str, api_prefix: str) -> ModuleDescriptor:
    """Create a descriptor that intentionally declares no unfinished capability."""

    return ModuleDescriptor(
        module_key=module_key,
        module_version="0.1.0",
        api_prefix=api_prefix,
    )


def dependency_consumer_descriptor(
    module_key: str, api_prefix: str, entity_type: str
) -> ModuleDescriptor:
    """Describe a clinical aggregate with implemented dependency and resolver handlers."""

    return ModuleDescriptor(
        module_key=module_key,
        module_version="0.1.0",
        api_prefix=api_prefix,
        content_schema_versions=("1.0.0",),
        entity_types=(entity_type,),
        artifact_types=(f"{module_key}_dependency_manifest",),
        authorization_scopes=(f"{module_key}:read", f"{module_key}:write"),
        capabilities=frozenset(
            {
                ModuleCapability.DEPENDENCIES,
                ModuleCapability.STALENESS,
                ModuleCapability.ENTITY_RESOLUTION,
                ModuleCapability.ARTIFACTS,
                ModuleCapability.RECONCILIATION_INPUTS,
            }
        ),
    )
