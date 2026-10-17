"""Strict SDTM-owned authoring contracts and Raw input selection."""

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.transformation.contracts import (
    Expression,
    custom_function_calls,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SelectedRawArtifact(StrictModel):
    dataset_code: str
    artifact_id: UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class SdtmInputSelectionWrite(StrictModel):
    raw_id: UUID
    raw_revision: int = Field(ge=1)
    validation_run_id: UUID
    source_artifacts: tuple[SelectedRawArtifact, ...] = Field(min_length=1)
    raw_dependency_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def unique_datasets_and_artifacts(self) -> "SdtmInputSelectionWrite":
        datasets = [item.dataset_code for item in self.source_artifacts]
        artifacts = [item.artifact_id for item in self.source_artifacts]
        if len(datasets) != len(set(datasets)) or len(artifacts) != len(set(artifacts)):
            raise ValueError("selected Raw datasets and artifacts must be unique")
        return self


class SdtmTerminologyBinding(StrictModel):
    terminology_release_id: UUID
    codelist_code: str
    term_code: str | None = None
    extension_revision_id: UUID | None = None


class SdtmVariable(StrictModel):
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,7}$")
    label: str = Field(min_length=1, max_length=40)
    data_type: Literal["character", "numeric"]
    length: int | None = Field(default=None, ge=1, le=200)
    role: str
    core: Literal["Req", "Exp", "Perm"]
    origin: str
    derived: bool = False
    terminology_binding: SdtmTerminologyBinding | None = None


class SdtmValueContext(StrictModel):
    """Reusable reviewer-facing value-level column owned by one domain."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    label: str = Field(min_length=1, max_length=120)
    discriminator_variable: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,7}$")
    operator: Literal["eq", "ne", "in"]
    values: tuple[str | int | float | bool, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_values(self) -> "SdtmValueContext":
        if self.operator in {"eq", "ne"} and len(self.values) != 1:
            raise ValueError(f"{self.operator} requires exactly one typed value")
        serialized = [(type(item).__name__, repr(item)) for item in self.values]
        if len(serialized) != len(set(serialized)):
            raise ValueError("context values must be unique")
        return self


class SdtmValueLevelMetadata(StrictModel):
    id: str
    variable: str
    context_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    # Kept only so immutable 1.0.0 revisions remain readable. New 2.0.0
    # Specifications must use context_id and may not author a condition here.
    condition: Expression | None = None
    label: str
    data_type: Literal["character", "numeric"]
    length: int | None = Field(default=None, ge=1, le=200)
    terminology_binding: SdtmTerminologyBinding | None = None


class SdtmDomain(StrictModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    label: str = Field(min_length=1, max_length=40)
    domain_class: str
    structure: str
    keys: tuple[str, ...] = Field(min_length=1)
    sort_order: tuple[str, ...] = Field(min_length=1)
    expected_output_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,7}\.xpt$")
    variables: tuple[SdtmVariable, ...] = Field(min_length=1)
    value_contexts: tuple[SdtmValueContext, ...] = ()
    value_level_metadata: tuple[SdtmValueLevelMetadata, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> "SdtmDomain":
        names = [item.name for item in self.variables]
        if len(names) != len(set(names)):
            raise ValueError("variable names must be unique within a domain")
        known = set(names)
        if not set(self.keys) <= known or not set(self.sort_order) <= known:
            raise ValueError("keys and sort order must reference declared variables")
        if any(item.variable not in known for item in self.value_level_metadata):
            raise ValueError("value-level metadata must reference a declared variable")
        context_ids = [item.id for item in self.value_contexts]
        if len(context_ids) != len(set(context_ids)):
            raise ValueError("value context IDs must be unique within a domain")
        if any(item.discriminator_variable not in known for item in self.value_contexts):
            raise ValueError("value context discriminators must reference declared variables")
        if any(
            item.context_id is not None and item.context_id not in set(context_ids)
            for item in self.value_level_metadata
        ):
            raise ValueError("value-level metadata context_id must resolve within its domain")
        return self


class SdtmSpecification(StrictModel):
    schema_version: Literal["1.0.0", "2.0.0"] = "2.0.0"
    domains: tuple[SdtmDomain, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def recognize_historical_shape(cls, value: object) -> object:
        if not isinstance(value, dict) or "schema_version" in value:
            return value
        domains = value.get("domains")
        if isinstance(domains, (list, tuple)) and any(
            isinstance(item, dict)
            and any(
                isinstance(vlm, dict) and vlm.get("condition") is not None
                for vlm in item.get("value_level_metadata", [])
            )
            for item in domains
        ):
            return {**value, "schema_version": "1.0.0"}
        return value

    @model_validator(mode="after")
    def unique_domains(self) -> "SdtmSpecification":
        codes = [item.code for item in self.domains]
        outputs = [item.expected_output_name for item in self.domains]
        if len(codes) != len(set(codes)) or len(outputs) != len(set(outputs)):
            raise ValueError("domain codes and output names must be unique")
        if any(
            item.condition is not None and custom_function_calls(item.condition)
            for domain in self.domains
            for item in domain.value_level_metadata
        ):
            raise ValueError("custom functions are not supported in SDTM value-level conditions")
        if self.schema_version == "2.0.0":
            for domain in self.domains:
                for item in domain.value_level_metadata:
                    if item.condition is not None or item.context_id is None:
                        raise ValueError(
                            "2.0.0 value-level metadata must reference context_id only"
                        )
        return self


class SdtmDomainMappingWrite(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    raw_datasets: tuple[str, ...] = ()
    upstream_domains: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_inputs(self) -> "SdtmDomainMappingWrite":
        if not self.raw_datasets and not self.upstream_domains:
            raise ValueError("a domain mapping requires at least one input")
        for values, label in (
            (self.raw_datasets, "Raw datasets"),
            (self.upstream_domains, "upstream domains"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
        return self


class SdtmQualifiedSource(StrictModel):
    source_type: Literal["raw", "sdtm"]
    dataset: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")
    variable: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")


class SdtmVariableMappingCell(StrictModel):
    target_variable: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,7}$")
    context_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    sources: tuple[SdtmQualifiedSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sources(self) -> "SdtmVariableMappingCell":
        identities = [(item.source_type, item.dataset, item.variable) for item in self.sources]
        if len(identities) != len(set(identities)):
            raise ValueError("cell sources must be unique")
        return self


class SdtmVariableMappingWrite(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    cells: tuple[SdtmVariableMappingCell, ...] = ()

    @model_validator(mode="after")
    def unique_cells(self) -> "SdtmVariableMappingWrite":
        identities = [(item.target_variable, item.context_id) for item in self.cells]
        if len(identities) != len(set(identities)):
            raise ValueError("target variable/context cells must be unique")
        return self


class SdtmCodeWorkareaCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    domain: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    language: Literal["python", "r", "sas"]
    source: str = Field(default="", max_length=1_000_000)


class SdtmCodeWorkareaUpdate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    source: str = Field(max_length=1_000_000)


class SdtmUpstreamArtifactSelection(StrictModel):
    domain: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    artifact_id: UUID


class SdtmWorkareaRunCreate(StrictModel):
    upstream_artifacts: tuple[SdtmUpstreamArtifactSelection, ...] = ()

    @model_validator(mode="after")
    def unique_upstream_domains(self) -> "SdtmWorkareaRunCreate":
        domains = [item.domain for item in self.upstream_artifacts]
        if len(domains) != len(set(domains)):
            raise ValueError("upstream artifact domains must be unique")
        return self


class SdtmOutputSelectionItem(StrictModel):
    domain: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    provider_type: Literal["generation", "imported"]
    provider_revision_id: UUID
    xpt_artifact_id: UUID


class SdtmOutputSelectionWrite(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    items: tuple[SdtmOutputSelectionItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_domains(self) -> "SdtmOutputSelectionWrite":
        domains = [item.domain for item in self.items]
        if len(domains) != len(set(domains)):
            raise ValueError("output selection domains must be unique")
        return self


class SdtmSpecificationInitialize(StrictModel):
    """User-selected scope for factual initialization from the pinned SDTMIG."""

    domain_codes: tuple[str, ...] = Field(
        min_length=1,
        description="Concrete standard domains to add or refresh.",
    )
    required_expected_only: bool = Field(
        default=False,
        description="When true, add only Required and Expected standard variables.",
    )

    @field_validator("domain_codes")
    @classmethod
    def validate_domain_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().upper() for item in value)
        if any(not re.fullmatch(r"[A-Z][A-Z0-9]{1,7}", item) for item in normalized):
            raise ValueError("domain codes must use the SDTM domain-code format")
        if len(normalized) != len(set(normalized)):
            raise ValueError("domain codes must be unique")
        return normalized


class SdtmStandardDomainOption(StrictModel):
    code: str
    label: str
    domain_class: str
    required_variable_count: int = Field(ge=0)
    expected_variable_count: int = Field(ge=0)
    permissible_variable_count: int = Field(ge=0)


class SdtmSpecificationInitializationOptions(StrictModel):
    standard_version_id: UUID
    domains: tuple[SdtmStandardDomainOption, ...]


class SdtmImportedVariable(StrictModel):
    """Factual physical metadata extracted from an imported XPT member."""

    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,7}$")
    label: str | None = Field(default=None, max_length=40)
    data_type: Literal["character", "numeric"]
    length: int | None = Field(default=None, ge=1, le=200)
    ordinal: int = Field(ge=1)


class SdtmImportedSchema(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    domain_code: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    row_count: int = Field(ge=0)
    variables: tuple[SdtmImportedVariable, ...] = Field(min_length=1)


class SdtmImportedDomainCreate(StrictModel):
    source_file_id: UUID
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    specification_revision: int = Field(ge=1)


class AcrfRegion(StrictModel):
    """Normalized PDF coordinates measured from the page's top-left corner."""

    coordinate_system: Literal["normalized_top_left"] = "normalized_top_left"
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(gt=0, le=1, allow_inf_nan=False)
    height: float = Field(gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def contained_by_page(self) -> "AcrfRegion":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("aCRF region must be contained by the normalized page")
        return self


class AcrfSdtmVariableLink(StrictModel):
    target_type: Literal["sdtm_variable"]
    specification_revision: int = Field(ge=1)
    domain: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    variable: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,7}$")


class AcrfRawVariableLink(StrictModel):
    target_type: Literal["raw_variable"]
    raw_variable_id: UUID


AcrfLink = Annotated[
    AcrfSdtmVariableLink | AcrfRawVariableLink,
    Field(discriminator="target_type"),
]


class AcrfAnnotationCreate(StrictModel):
    source_pdf_artifact_id: UUID
    page_number: int = Field(ge=1)
    region: AcrfRegion
    annotation_text: str | None = Field(default=None, max_length=4000)
    links: tuple[AcrfLink, ...] = ()
    question: str | None = Field(default=None, max_length=4000)
    resolution: str | None = Field(default=None, max_length=4000)
    status: Literal["open", "resolved"] = "open"

    @model_validator(mode="after")
    def unique_links(self) -> "AcrfAnnotationCreate":
        serialized = [item.model_dump_json() for item in self.links]
        if len(serialized) != len(set(serialized)):
            raise ValueError("aCRF links must be unique")
        return self


class AcrfAnnotationPatch(StrictModel):
    page_number: int | None = Field(default=None, ge=1)
    region: AcrfRegion | None = None
    annotation_text: str | None = Field(default=None, max_length=4000)
    question: str | None = Field(default=None, max_length=4000)
    resolution: str | None = Field(default=None, max_length=4000)
    status: Literal["open", "resolved"] | None = None


class AcrfLinksWrite(StrictModel):
    operation: Literal["replace", "amend"] = "replace"
    links: tuple[AcrfLink, ...] = ()

    @model_validator(mode="after")
    def unique_links(self) -> "AcrfLinksWrite":
        serialized = [item.model_dump_json() for item in self.links]
        if len(serialized) != len(set(serialized)):
            raise ValueError("aCRF links must be unique")
        return self


class DefineDocumentReference(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    title: str = Field(min_length=1, max_length=255)
    href: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
    source_artifact_id: UUID | None = None


class DefineLeaf(StrictModel):
    id: str = Field(pattern=r"^LF\.[A-Za-z0-9_.-]{1,124}$")
    title: str = Field(min_length=1, max_length=255)
    href: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
    artifact_id: UUID | None = None
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class DefineOrigin(StrictModel):
    origin_type: Literal["Assigned", "Collected", "Derived", "Predecessor", "Protocol"]
    description: str | None = Field(default=None, max_length=4000)
    document_reference_ids: tuple[str, ...] = ()
    acrf_annotation_ids: tuple[UUID, ...] = ()


class DefineItem(StrictModel):
    oid: str = Field(pattern=r"^IT\.[A-Za-z0-9_.-]{1,124}$")
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,7}$")
    label: str = Field(min_length=1, max_length=40)
    data_type: Literal["text", "integer", "float", "date", "datetime"]
    length: int | None = Field(default=None, ge=1, le=200)
    role: str | None = Field(default=None, max_length=64)
    mandatory: bool
    origin: DefineOrigin
    codelist_id: str | None = None
    method_id: str | None = None
    comment_id: str | None = None


class DefineDataset(StrictModel):
    oid: str = Field(pattern=r"^IG\.[A-Za-z0-9_.-]{1,124}$")
    name: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    label: str = Field(min_length=1, max_length=40)
    dataset_class: str = Field(min_length=1, max_length=128)
    structure: str = Field(min_length=1, max_length=255)
    purpose: Literal["Tabulation", "Analysis"] = "Tabulation"
    repeating: bool = True
    reference_data: bool = False
    leaf_id: str | None = None
    items: tuple[DefineItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_items(self) -> "DefineDataset":
        names = [item.name for item in self.items]
        oids = [item.oid for item in self.items]
        if len(names) != len(set(names)) or len(oids) != len(set(oids)):
            raise ValueError("Define item names and OIDs must be unique within a dataset")
        return self


class DefineCodeListItem(StrictModel):
    coded_value: str
    decode: str
    rank: int | None = Field(default=None, ge=1)


class DefineCodeList(StrictModel):
    id: str = Field(pattern=r"^CL\.[A-Za-z0-9_.-]{1,124}$")
    name: str = Field(min_length=1, max_length=255)
    data_type: Literal["text", "integer", "float"]
    items: tuple[DefineCodeListItem, ...] = ()


class DefineMethod(StrictModel):
    id: str = Field(pattern=r"^MT\.[A-Za-z0-9_.-]{1,124}$")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=8000)


class DefineComment(StrictModel):
    id: str = Field(pattern=r"^COM\.[A-Za-z0-9_.-]{1,123}$")
    description: str = Field(min_length=1, max_length=8000)


class SdtmDefineModel(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    specification_revision: int = Field(ge=1)
    study_oid: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    metadata_version_oid: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    standard_name: str = Field(min_length=1, max_length=64)
    standard_version: str = Field(min_length=1, max_length=32)
    output_artifact_ids: tuple[UUID, ...] = ()
    datasets: tuple[DefineDataset, ...] = Field(min_length=1)
    leaves: tuple[DefineLeaf, ...] = ()
    document_references: tuple[DefineDocumentReference, ...] = ()
    codelists: tuple[DefineCodeList, ...] = ()
    methods: tuple[DefineMethod, ...] = ()
    comments: tuple[DefineComment, ...] = ()

    @model_validator(mode="after")
    def resolve_internal_references(self) -> "SdtmDefineModel":
        dataset_names = [item.name for item in self.datasets]
        dataset_oids = [item.oid for item in self.datasets]
        if len(dataset_names) != len(set(dataset_names)) or len(dataset_oids) != len(
            set(dataset_oids)
        ):
            raise ValueError("Define dataset names and OIDs must be unique")
        output_ids = list(self.output_artifact_ids)
        if len(output_ids) != len(set(output_ids)):
            raise ValueError("Define output artifact IDs must be unique")
        documents = {item.id for item in self.document_references}
        codelists = {item.id for item in self.codelists}
        methods = {item.id for item in self.methods}
        comments = {item.id for item in self.comments}
        leaf_ids = {item.id for item in self.leaves}
        if len(leaf_ids) != len(self.leaves):
            raise ValueError("Define leaf IDs must be unique")
        for dataset in self.datasets:
            if dataset.leaf_id is not None and dataset.leaf_id not in leaf_ids:
                raise ValueError("Define dataset leaf references must resolve")
            for item in dataset.items:
                if not set(item.origin.document_reference_ids) <= documents:
                    raise ValueError("Define origin document references must resolve")
                if item.codelist_id is not None and item.codelist_id not in codelists:
                    raise ValueError("Define item codelist references must resolve")
                if item.method_id is not None and item.method_id not in methods:
                    raise ValueError("Define item method references must resolve")
                if item.comment_id is not None and item.comment_id not in comments:
                    raise ValueError("Define item comment references must resolve")
        return self


class SdtmDefineInitialize(StrictModel):
    expected_define_revision: int | None = Field(default=None, ge=1)
    study_oid: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    metadata_version_oid: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    standard_name: str = Field(min_length=1, max_length=64)
    standard_version: str = Field(min_length=1, max_length=32)
    output_artifact_ids: tuple[UUID, ...] = ()


class CsdrgDatasetFact(StrictModel):
    """Factual dataset evidence copied from exact immutable SDTM outputs."""

    dataset: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    label: str = Field(min_length=1, max_length=255)
    structure: str = Field(min_length=1, max_length=1000)
    xpt_artifact_id: UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(ge=0)
    variable_count: int = Field(ge=1)


class CsdrgNarrativeSection(StrictModel):
    """One manually authored cSDRG narrative section."""

    section_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    heading: str = Field(min_length=1, max_length=500)
    paragraphs: tuple[Annotated[str, Field(min_length=1, max_length=8000)], ...] = ()


class SdtmCsdrgModel(StrictModel):
    """Versioned cSDRG content with factual evidence separated from narrative."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    title: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=64)
    specification_revision: int = Field(ge=1)
    define_revision: int = Field(ge=1)
    reconciliation_run_id: UUID
    output_artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    dataset_facts: tuple[CsdrgDatasetFact, ...] = Field(min_length=1)
    narrative_sections: tuple[CsdrgNarrativeSection, ...] = ()

    @model_validator(mode="after")
    def unique_content(self) -> "SdtmCsdrgModel":
        datasets = [item.dataset for item in self.dataset_facts]
        artifacts = [item.xpt_artifact_id for item in self.dataset_facts]
        sections = [item.section_id for item in self.narrative_sections]
        if len(datasets) != len(set(datasets)) or len(artifacts) != len(set(artifacts)):
            raise ValueError("cSDRG dataset facts and XPT artifact IDs must be unique")
        if len(sections) != len(set(sections)):
            raise ValueError("cSDRG narrative section IDs must be unique")
        if set(artifacts) != set(self.output_artifact_ids):
            raise ValueError("cSDRG dataset facts must cover the exact selected outputs")
        return self


class SdtmCsdrgInitialize(StrictModel):
    """Request to refresh factual cSDRG structures without writing narrative."""

    expected_csdrg_revision: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=64)
    define_revision: int = Field(ge=1)
    reconciliation_run_id: UUID
