"""Typed repository-manifest contract for CDISC standard packages."""

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CdiscProduct(BaseModel):
    """Stable CDISC product identity independent of a release version."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=255)
    family: str = Field(min_length=1, max_length=64)
    product_type: Literal[
        "model",
        "implementation_guide",
        "data_exchange",
        "data_collection",
        "analysis",
        "therapeutic_area",
        "measure",
        "foundational",
    ]
    scope: Literal["clinical", "nonclinical", "cross_domain"]


class CdiscStandardRelease(BaseModel):
    """Exact immutable standard release metadata."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: str = Field(min_length=1, max_length=64)
    publication_date: date
    lifecycle: Literal["active", "deprecated", "withdrawn"] = "active"
    library_href: str | None = Field(default=None, max_length=1000)
    applicable_modules: list[str] = Field(min_length=1)
    purposes: list[str] = Field(min_length=1)
    provenance: dict[str, object]


class CdiscStandardAsset(BaseModel):
    """One checked repository asset in a CDISC release package."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    role: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    media_type: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required: bool = True


class CdiscStandardCompatibility(BaseModel):
    """Relationship from this release to another exact release."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    target_standard_version_id: UUID
    relationship: Literal["implements", "based_on", "supersedes", "supports", "requires", "uses"]
    required: bool = False
    evidence: dict[str, object] = Field(default_factory=dict)


class CdiscStandardManifest(BaseModel):
    """Reviewed manifest for importing one pinned CDISC standard release."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    provider: Literal["CDISC"]
    product: CdiscProduct
    release: CdiscStandardRelease
    assets: list[CdiscStandardAsset] = Field(min_length=1)
    compatibilities: list[CdiscStandardCompatibility] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_uniqueness(self) -> Self:
        paths = [(item.role, item.path) for item in self.assets]
        if len(paths) != len(set(paths)):
            raise ValueError("asset role/path pairs must be unique")
        relationships = [
            (item.target_standard_version_id, item.relationship) for item in self.compatibilities
        ]
        if len(relationships) != len(set(relationships)):
            raise ValueError("compatibility target/relationship pairs must be unique")
        if any(item.target_standard_version_id == self.release.id for item in self.compatibilities):
            raise ValueError("a standard release cannot be compatible with itself")
        return self
