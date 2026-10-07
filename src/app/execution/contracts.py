"""Typed module boundary for validating and materializing execution outputs."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionProduct:
    """One verified immutable product prepared by the owning clinical module."""

    artifact_type: str
    filename: str
    media_type: str
    data: bytes
    manifest: dict[str, object]
