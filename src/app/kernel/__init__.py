"""Typed module-extension kernel."""

from app.kernel.contracts import ModuleCapability, ModuleDescriptor, ModuleRegistration
from app.kernel.registry import ModuleRegistry, ModuleRegistryError

__all__ = [
    "ModuleCapability",
    "ModuleDescriptor",
    "ModuleRegistration",
    "ModuleRegistry",
    "ModuleRegistryError",
]
