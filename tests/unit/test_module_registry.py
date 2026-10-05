"""Module registry invariant tests."""

import pytest
from pydantic import ValidationError

from app.composition import BUILTIN_DESCRIPTORS, build_module_registry
from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration
from app.kernel.registry import ModuleRegistry, ModuleRegistryError


def descriptor(
    key: str,
    *,
    prefix: str | None = None,
    artifact_types: tuple[str, ...] = (),
    capabilities: frozenset[ModuleCapability] = frozenset(),
) -> ModuleDescriptor:
    return ModuleDescriptor(
        module_key=key,
        module_version="1.0.0",
        api_prefix=prefix or f"/api/v1/{key}",
        artifact_types=artifact_types,
        capabilities=capabilities,
    )


def test_builtin_registry_is_sealed_and_sorted() -> None:
    registry = build_module_registry()

    keys = [item.module_key for item in registry.descriptors()]
    assert registry.is_sealed is True
    assert keys == sorted(keys)
    assert len(keys) == len(BUILTIN_DESCRIPTORS)
    assert "raw" in keys
    assert "integration" in keys


def test_module_key_is_one_lowercase_word() -> None:
    with pytest.raises(ValidationError):
        descriptor("bad_module")


def test_duplicate_module_key_fails_without_replacing_original() -> None:
    registry = ModuleRegistry()
    registry.register(ModuleRegistration(descriptor("labs")))

    with pytest.raises(ModuleRegistryError) as error:
        registry.register(ModuleRegistration(descriptor("labs", prefix="/api/v1/other-labs")))

    assert error.value.code == "duplicate_module_key"
    assert registry.require("labs").api_prefix == "/api/v1/labs"


def test_duplicate_api_prefix_is_rejected() -> None:
    registry = ModuleRegistry()
    registry.register(ModuleRegistration(descriptor("labs")))

    with pytest.raises(ModuleRegistryError) as error:
        registry.register(ModuleRegistration(descriptor("ecg", prefix="/api/v1/labs")))

    assert error.value.code == "duplicate_api_prefix"


def test_duplicate_owned_type_is_rejected_atomically() -> None:
    registry = ModuleRegistry()
    registry.register(ModuleRegistration(descriptor("labs", artifact_types=("labs_report",))))

    with pytest.raises(ModuleRegistryError) as error:
        registry.register(ModuleRegistration(descriptor("ecg", artifact_types=("labs_report",))))

    assert error.value.code == "duplicate_owned_type"
    assert registry.get("ecg") is None


def test_declared_capability_requires_exact_handler_set() -> None:
    registry = ModuleRegistry()
    module = descriptor(
        "labs",
        capabilities=frozenset({ModuleCapability.VALIDATION}),
    )

    with pytest.raises(ModuleRegistryError) as error:
        registry.register(ModuleRegistration(module))

    assert error.value.code == "capability_handler_mismatch"


def test_runtime_registration_after_seal_is_rejected() -> None:
    registry = ModuleRegistry()
    registry.register(ModuleRegistration(descriptor("labs")))
    registry.seal()

    with pytest.raises(ModuleRegistryError) as error:
        registry.register(ModuleRegistration(descriptor("ecg")))

    assert error.value.code == "module_registry_sealed"
