"""Typed repository-manifest contract for CDISC Controlled Terminology."""

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CdiscTerm(BaseModel):
    """One NCI EVS concept published in a CDISC codelist."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    concept_id: str = Field(pattern=r"^C[0-9]+$", max_length=64)
    submission_value: str = Field(min_length=1, max_length=255)
    decode: str = Field(min_length=1, max_length=1000)
    definition: str | None = Field(default=None, max_length=4000)
    preferred_term: str | None = Field(default=None, max_length=1000)
    synonyms: list[str] = Field(default_factory=list)
    status: Literal["active", "retired"] = "active"


class CdiscCodelist(BaseModel):
    """One published CDISC codelist including its extension policy."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    concept_id: str = Field(pattern=r"^C[0-9]+$", max_length=64)
    name: str = Field(min_length=1, max_length=255)
    submission_value: str = Field(min_length=1, max_length=255)
    definition: str | None = Field(default=None, max_length=4000)
    preferred_term: str | None = Field(default=None, max_length=1000)
    synonyms: list[str] = Field(default_factory=list)
    extensible: bool
    terms: list[CdiscTerm] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_terms(self) -> Self:
        concept_ids = [item.concept_id for item in self.terms]
        submission_values = [item.submission_value for item in self.terms]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("term concept IDs must be unique within a codelist")
        if len(submission_values) != len(set(submission_values)):
            raise ValueError("term submission values must be unique within a codelist")
        return self


class CdiscTerminologyRelease(BaseModel):
    """Exact immutable CDISC Controlled Terminology package metadata."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")
    product: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")
    version: str = Field(min_length=1, max_length=64)
    publication_date: date
    lifecycle: Literal["active", "deprecated", "withdrawn"] = "active"
    library_href: str | None = Field(default=None, max_length=1000)
    applicable_modules: list[str] = Field(min_length=1)
    provenance: dict[str, object]


class CdiscTerminologyCompatibility(BaseModel):
    """Compatibility between the CT package and an exact standard release."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    standard_version_id: UUID
    terminology_scope: str = Field(min_length=1, max_length=64)
    standard_purpose: str = Field(min_length=1, max_length=64)
    relationship: Literal["supports", "required_by"] = "supports"
    evidence: dict[str, object] = Field(default_factory=dict)


class CdiscTerminologyManifest(BaseModel):
    """Reviewed manifest for importing one pinned CDISC CT package."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    provider: Literal["CDISC"]
    release: CdiscTerminologyRelease
    codelists: list[CdiscCodelist] = Field(min_length=1)
    compatibilities: list[CdiscTerminologyCompatibility] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_codelists(self) -> Self:
        concept_ids = [item.concept_id for item in self.codelists]
        submission_values = [item.submission_value for item in self.codelists]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("codelist concept IDs must be unique within a release")
        if len(submission_values) != len(set(submission_values)):
            raise ValueError("codelist submission values must be unique within a release")
        return self
