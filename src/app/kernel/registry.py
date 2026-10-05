"""Conflict-checked startup registry for application modules."""

from collections.abc import Iterable

from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleKey, ModuleRegistration


class ModuleRegistryError(RuntimeError):
    """Raised when module composition violates a registry invariant."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ModuleRegistry:
    """Own module descriptors and globally unique extension identifiers."""

    _OWNED_COLLECTIONS = (
        "entity_types",
        "relationship_types",
        "artifact_types",
        "source_plan_types",
        "event_types",
    )

    def __init__(self) -> None:
        self._registrations: dict[str, ModuleRegistration] = {}
        self._api_prefixes: dict[str, str] = {}
        self._owned_values: dict[str, dict[str, str]] = {
            name: {} for name in self._OWNED_COLLECTIONS
        }
        self._sealed = False

    @property
    def is_sealed(self) -> bool:
        """Whether startup registration has completed."""

        return self._sealed

    def register(self, registration: ModuleRegistration) -> None:
        """Register one module or fail without partially mutating the registry."""

        if self._sealed:
            raise ModuleRegistryError(
                "module_registry_sealed", "modules cannot be registered after startup"
            )

        descriptor = registration.descriptor
        key = descriptor.module_key
        if key in self._registrations:
            raise ModuleRegistryError(
                "duplicate_module_key", f"module key '{key}' is already registered"
            )
        prefix_owner = self._api_prefixes.get(descriptor.api_prefix)
        if prefix_owner is not None:
            raise ModuleRegistryError(
                "duplicate_api_prefix",
                f"API prefix '{descriptor.api_prefix}' is already owned by '{prefix_owner}'",
            )

        declared = set(descriptor.capabilities)
        provided = set(registration.handlers)
        if declared != provided:
            missing = sorted(item.value for item in declared - provided)
            unexpected = sorted(item.value for item in provided - declared)
            raise ModuleRegistryError(
                "capability_handler_mismatch",
                f"module '{key}' missing handlers {missing} and provided undeclared handlers "
                f"{unexpected}",
            )

        conflicts: list[str] = []
        for collection_name in self._OWNED_COLLECTIONS:
            owners = self._owned_values[collection_name]
            for value in getattr(descriptor, collection_name):
                if value in owners:
                    conflicts.append(
                        f"{collection_name}.{value} is already owned by '{owners[value]}'"
                    )
        if conflicts:
            raise ModuleRegistryError("duplicate_owned_type", "; ".join(conflicts))

        self._registrations[key] = registration
        self._api_prefixes[descriptor.api_prefix] = key
        for collection_name in self._OWNED_COLLECTIONS:
            owners = self._owned_values[collection_name]
            for value in getattr(descriptor, collection_name):
                owners[value] = key

    def register_all(self, registrations: Iterable[ModuleRegistration]) -> None:
        """Register a deterministic collection of modules."""

        for registration in registrations:
            self.register(registration)

    def seal(self) -> None:
        """Prevent runtime plugin installation after composition."""

        self._sealed = True

    def descriptors(self) -> tuple[ModuleDescriptor, ...]:
        """Return safe descriptors sorted by stable module key."""

        return tuple(self._registrations[key].descriptor for key in sorted(self._registrations))

    def routers(self) -> tuple[object, ...]:
        """Return reviewed module routers in stable module-key order."""

        return tuple(
            registration.router
            for key in sorted(self._registrations)
            if (registration := self._registrations[key]).router is not None
        )

    def get(self, module_key: ModuleKey | str) -> ModuleDescriptor | None:
        """Resolve one descriptor without exposing its handlers."""

        registration = self._registrations.get(module_key)
        return registration.descriptor if registration is not None else None

    def require(self, module_key: ModuleKey | str) -> ModuleDescriptor:
        """Resolve one descriptor or raise a typed registry error."""

        descriptor = self.get(module_key)
        if descriptor is None:
            raise ModuleRegistryError(
                "module_not_registered", f"module '{module_key}' is not registered"
            )
        return descriptor

    def require_handler(self, module_key: ModuleKey | str, capability: ModuleCapability) -> object:
        """Resolve one declared capability without exposing registrations publicly."""

        registration = self._registrations.get(module_key)
        if registration is None:
            raise ModuleRegistryError(
                "module_not_registered", f"module '{module_key}' is not registered"
            )
        handler = registration.handlers.get(capability)
        if handler is None:
            raise ModuleRegistryError(
                "module_capability_missing",
                f"module '{module_key}' does not implement '{capability.value}'",
            )
        return handler

    def owner_of(self, collection: str, value: str) -> str | None:
        """Resolve the module owning one globally registered extension identifier."""

        owners = self._owned_values.get(collection)
        return owners.get(value) if owners is not None else None

    def readiness(self) -> tuple[bool, str]:
        """Report whether composition completed with at least one module."""

        if not self._sealed:
            return False, "registry is not sealed"
        if not self._registrations:
            return False, "registry contains no modules"
        return True, f"{len(self._registrations)} modules registered"
