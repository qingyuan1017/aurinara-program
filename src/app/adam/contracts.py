"""Strict ADaM-owned authoring contracts and exact SDTM input selection."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.transformation.contracts import (
    CustomFunctionDefinition,
    Expression,
    custom_function_calls,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SelectedSdtmArtifact(StrictModel):
    dataset_code: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    artifact_id: UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class AdamInputSelectionWrite(StrictModel):
    sdtm_id: UUID
    sdtm_revision: int = Field(ge=1)
    validation_run_id: UUID
    xpt_artifacts: tuple[SelectedSdtmArtifact, ...] = Field(min_length=1)
    sdtm_dependency_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def unique_datasets_and_artifacts(self) -> "AdamInputSelectionWrite":
        datasets = [item.dataset_code for item in self.xpt_artifacts]
        artifacts = [item.artifact_id for item in self.xpt_artifacts]
        if len(datasets) != len(set(datasets)) or len(artifacts) != len(set(artifacts)):
            raise ValueError("selected SDTM datasets and artifacts must be unique")
        return self


class AdamTerminologyBinding(StrictModel):
    terminology_release_id: UUID
    codelist_code: str = Field(min_length=1, max_length=64)
    term_code: str | None = Field(default=None, max_length=128)
    extension_revision_id: UUID | None = None


class AdamOrigin(StrictModel):
    origin_type: Literal["Assigned", "Derived", "Predecessor"]
    source_kind: Literal["sdtm", "adam"] | None = None
    source_dataset: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    source_variable: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,7}$")
    description: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def valid_source(self) -> "AdamOrigin":
        values = (self.source_kind, self.source_dataset, self.source_variable)
        if self.origin_type == "Predecessor" and any(item is None for item in values):
            raise ValueError("Predecessor origins require source kind, dataset, and variable")
        if self.origin_type != "Predecessor" and any(item is not None for item in values):
            raise ValueError("only Predecessor origins accept an exact source")
        return self


class AdamMethod(StrictModel):
    id: str = Field(pattern=r"^MT\.[A-Za-z0-9_.-]{1,124}$")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=8000)
    plan_node_ids: tuple[str, ...] = Field(min_length=1)


class AdamParameter(StrictModel):
    id: UUID
    code: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=200)
    variable: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,7}$")
    value: str | int | float | bool
    terminology_binding: AdamTerminologyBinding | None = None


class AdamVariable(StrictModel):
    id: UUID
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,7}$")
    label: str = Field(min_length=1, max_length=40)
    data_type: Literal["character", "numeric"]
    length: int | None = Field(default=None, ge=1, le=200)
    role: str = Field(min_length=1, max_length=64)
    origin: AdamOrigin
    method_id: str | None = None
    output_node_id: str = Field(min_length=1, max_length=128)
    terminology_binding: AdamTerminologyBinding | None = None


class AdamValueLevelMetadata(StrictModel):
    id: UUID
    variable: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,7}$")
    condition: Expression
    label: str = Field(min_length=1, max_length=200)
    data_type: Literal["character", "numeric"]
    length: int | None = Field(default=None, ge=1, le=200)
    origin: AdamOrigin
    method_id: str | None = None
    terminology_binding: AdamTerminologyBinding | None = None


class AdamDataset(StrictModel):
    id: UUID
    code: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    label: str = Field(min_length=1, max_length=40)
    dataset_class: str = Field(min_length=1, max_length=128)
    structure: str = Field(min_length=1, max_length=255)
    keys: tuple[str, ...] = Field(min_length=1)
    sort_order: tuple[str, ...] = Field(min_length=1)
    purpose: Literal["Analysis"] = "Analysis"
    expected_output_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,7}\.xpt$")
    variables: tuple[AdamVariable, ...] = Field(min_length=1)
    parameters: tuple[AdamParameter, ...] = ()
    value_level_metadata: tuple[AdamValueLevelMetadata, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> "AdamDataset":
        names = [item.name for item in self.variables]
        variable_ids = [item.id for item in self.variables]
        if len(names) != len(set(names)) or len(variable_ids) != len(set(variable_ids)):
            raise ValueError("variable names and IDs must be unique within an ADaM dataset")
        known = set(names)
        if not set(self.keys) <= known or not set(self.sort_order) <= known:
            raise ValueError("keys and sort order must reference declared variables")
        if any(item.variable not in known for item in self.parameters):
            raise ValueError("parameters must reference a declared variable")
        if any(item.variable not in known for item in self.value_level_metadata):
            raise ValueError("value-level metadata must reference a declared variable")
        parameter_codes = [item.code for item in self.parameters]
        parameter_ids = [item.id for item in self.parameters]
        value_level_ids = [item.id for item in self.value_level_metadata]
        if len(parameter_codes) != len(set(parameter_codes)) or len(parameter_ids) != len(
            set(parameter_ids)
        ):
            raise ValueError("parameter codes and IDs must be unique within an ADaM dataset")
        if len(value_level_ids) != len(set(value_level_ids)):
            raise ValueError("value-level metadata IDs must be unique within an ADaM dataset")
        return self


class AdamTraceSource(StrictModel):
    module: Literal["documents"] = "documents"
    entity_type: Literal[
        "protocol_objective",
        "protocol_endpoint",
        "sap_objective",
        "sap_endpoint",
        "sap_estimand",
        "sap_population",
        "sap_method",
    ]
    entity_id: UUID


class AdamTraceDestination(StrictModel):
    module: Literal["adam"] = "adam"
    entity_type: Literal["adam_dataset", "adam_variable", "adam_parameter", "adam_value_level"]
    entity_id: UUID


class AdamTraceTarget(StrictModel):
    relationship_type: Literal["supports", "addresses", "analyzes", "references", "depends_on"]
    source: AdamTraceSource
    target: AdamTraceDestination


class AdamSpecification(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    datasets: tuple[AdamDataset, ...] = Field(min_length=1)
    methods: tuple[AdamMethod, ...] = ()
    trace_targets: tuple[AdamTraceTarget, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> "AdamSpecification":
        codes = [item.code for item in self.datasets]
        dataset_ids = [item.id for item in self.datasets]
        outputs = [item.expected_output_name for item in self.datasets]
        if (
            len(codes) != len(set(codes))
            or len(dataset_ids) != len(set(dataset_ids))
            or len(outputs) != len(set(outputs))
        ):
            raise ValueError("ADaM dataset codes, IDs, and output names must be unique")
        method_ids = [item.id for item in self.methods]
        if len(method_ids) != len(set(method_ids)):
            raise ValueError("ADaM method IDs must be unique")
        known_methods = set(method_ids)
        entity_ids: dict[str, set[UUID]] = {
            "adam_dataset": set(),
            "adam_variable": set(),
            "adam_parameter": set(),
            "adam_value_level": set(),
        }
        for dataset in self.datasets:
            entity_ids["adam_dataset"].add(dataset.id)
            for variable in dataset.variables:
                entity_ids["adam_variable"].add(variable.id)
                if variable.method_id is not None and variable.method_id not in known_methods:
                    raise ValueError("ADaM method references must resolve")
                if variable.origin.origin_type == "Derived" and variable.method_id is None:
                    raise ValueError("derived ADaM metadata requires a reviewer-readable method")
            for value_level in dataset.value_level_metadata:
                entity_ids["adam_value_level"].add(value_level.id)
                if custom_function_calls(value_level.condition):
                    raise ValueError("custom functions may only be called from a Derivation Plan")
                if value_level.method_id is not None and value_level.method_id not in known_methods:
                    raise ValueError("ADaM method references must resolve")
                if value_level.origin.origin_type == "Derived" and value_level.method_id is None:
                    raise ValueError("derived ADaM metadata requires a reviewer-readable method")
            entity_ids["adam_parameter"].update(item.id for item in dataset.parameters)
        all_ids = [entity_id for values in entity_ids.values() for entity_id in values]
        expected_id_count = sum(
            1
            for dataset in self.datasets
            for _ in (
                dataset,
                *dataset.variables,
                *dataset.parameters,
                *dataset.value_level_metadata,
            )
        )
        if len(all_ids) != expected_id_count or len(all_ids) != len(set(all_ids)):
            raise ValueError("ADaM entity IDs must be unique across the Specification")
        trace_keys = [
            (
                item.relationship_type,
                item.source.module,
                item.source.entity_type,
                item.source.entity_id,
                item.target.module,
                item.target.entity_type,
                item.target.entity_id,
            )
            for item in self.trace_targets
        ]
        if len(trace_keys) != len(set(trace_keys)):
            raise ValueError("ADaM trace targets must be unique")
        for item in self.trace_targets:
            if item.target.entity_id not in entity_ids[item.target.entity_type]:
                raise ValueError(
                    "ADaM trace targets must resolve to declared Specification entities"
                )
        return self


class SdtmReadNode(StrictModel):
    node_type: Literal["sdtm_read"]
    id: str = Field(min_length=1, max_length=128)
    dataset: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")


class AdamReadNode(StrictModel):
    node_type: Literal["adam_read"]
    id: str = Field(min_length=1, max_length=128)
    dataset: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")


class AdamFilterNode(StrictModel):
    node_type: Literal["filter"]
    id: str = Field(min_length=1, max_length=128)
    predicate: Expression


class AdamDeriveNode(StrictModel):
    node_type: Literal["derive"]
    id: str = Field(min_length=1, max_length=128)
    target_dataset: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    assignments: dict[str, Expression] = Field(min_length=1)
    method_id: str | None = None
    parameter_code: str | None = None


class AdamSelectNode(StrictModel):
    node_type: Literal["select"]
    id: str = Field(min_length=1, max_length=128)
    columns: tuple[str, ...] = Field(min_length=1)


class AdamAssertNode(StrictModel):
    node_type: Literal["assert"]
    id: str = Field(min_length=1, max_length=128)
    predicate: Expression
    issue_code: str = Field(min_length=1, max_length=128)


class AdamDatasetWriteNode(StrictModel):
    node_type: Literal["dataset_write"]
    id: str = Field(min_length=1, max_length=128)
    dataset: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")


AdamPlanNode = Annotated[
    SdtmReadNode
    | AdamReadNode
    | AdamFilterNode
    | AdamDeriveNode
    | AdamSelectNode
    | AdamAssertNode
    | AdamDatasetWriteNode,
    Field(discriminator="node_type"),
]


class AdamPlanEdge(StrictModel):
    source_node: str = Field(min_length=1, max_length=128)
    target_node: str = Field(min_length=1, max_length=128)


class AdamDerivationPlan(StrictModel):
    schema_version: Literal["1.1.0"] = "1.1.0"
    dataset: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    specification_revision: int = Field(ge=1)
    input_selection_revision: int = Field(ge=1)
    custom_functions: tuple[CustomFunctionDefinition, ...] = ()
    nodes: tuple[AdamPlanNode, ...] = Field(min_length=1)
    edges: tuple[AdamPlanEdge, ...] = ()

    @model_validator(mode="after")
    def valid_graph(self) -> "AdamDerivationPlan":
        function_ids = [item.id for item in self.custom_functions]
        if len(function_ids) != len(set(function_ids)):
            raise ValueError("custom function IDs must be unique")
        identifiers = [node.id for node in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("plan node IDs must be unique")
        known = set(identifiers)
        incoming = dict.fromkeys(identifiers, 0)
        outgoing: dict[str, list[str]] = {item: [] for item in identifiers}
        for edge in self.edges:
            if edge.source_node not in known or edge.target_node not in known:
                raise ValueError("plan edges must resolve to known nodes")
            incoming[edge.target_node] += 1
            outgoing[edge.source_node].append(edge.target_node)
        queue = [item for item, count in incoming.items() if count == 0]
        visited = 0
        while queue:
            current = queue.pop()
            visited += 1
            for target in outgoing[current]:
                incoming[target] -= 1
                if incoming[target] == 0:
                    queue.append(target)
        if visited != len(identifiers):
            raise ValueError("plan graph must be acyclic")
        return self


class AdamDefineLeaf(StrictModel):
    id: str = Field(pattern=r"^LF\.[A-Za-z0-9_.-]{1,124}$")
    title: str = Field(min_length=1, max_length=255)
    href: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
    artifact_id: UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class AdamDefineModel(StrictModel):
    """Version-neutral ADaM Define metadata over exact authored and output evidence."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    specification_revision: int = Field(ge=1)
    input_selection_revision: int = Field(ge=1)
    study_oid: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    metadata_version_oid: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    standard_name: str = Field(min_length=1, max_length=64)
    standard_version: str = Field(min_length=1, max_length=32)
    output_artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    datasets: tuple[AdamDataset, ...] = Field(min_length=1)
    methods: tuple[AdamMethod, ...] = ()
    leaves: tuple[AdamDefineLeaf, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_internal_references(self) -> "AdamDefineModel":
        dataset_codes = [item.code for item in self.datasets]
        method_ids = [item.id for item in self.methods]
        artifact_ids = list(self.output_artifact_ids)
        leaf_ids = [item.id for item in self.leaves]
        leaf_artifacts = [item.artifact_id for item in self.leaves]
        if len(dataset_codes) != len(set(dataset_codes)):
            raise ValueError("ADaM Define dataset codes must be unique")
        if len(method_ids) != len(set(method_ids)):
            raise ValueError("ADaM Define method IDs must be unique")
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("ADaM Define output artifact IDs must be unique")
        if len(leaf_ids) != len(set(leaf_ids)) or len(leaf_artifacts) != len(set(leaf_artifacts)):
            raise ValueError("ADaM Define leaves and artifact bindings must be unique")
        if set(artifact_ids) != set(leaf_artifacts):
            raise ValueError("every selected ADaM output must have exactly one Define leaf")
        known_methods = set(method_ids)
        for dataset in self.datasets:
            for variable in dataset.variables:
                if variable.method_id is not None and variable.method_id not in known_methods:
                    raise ValueError("ADaM Define method references must resolve")
            for value_level in dataset.value_level_metadata:
                if value_level.method_id is not None and value_level.method_id not in known_methods:
                    raise ValueError("ADaM Define value-level methods must resolve")
        return self


class AdamDefineInitialize(StrictModel):
    expected_define_revision: int | None = Field(default=None, ge=1)
    study_oid: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    metadata_version_oid: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    standard_name: str = Field(min_length=1, max_length=64)
    standard_version: str = Field(min_length=1, max_length=32)
    output_artifact_ids: tuple[UUID, ...] = Field(min_length=1)


class AdrgDatasetFact(StrictModel):
    dataset: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    label: str = Field(min_length=1, max_length=255)
    structure: str = Field(min_length=1, max_length=1000)
    xpt_artifact_id: UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(ge=0)
    variable_count: int = Field(ge=1)


class AdrgExecutionFact(StrictModel):
    execution_run_id: UUID
    language: Literal["python", "r", "sas"]
    program_artifact_id: UUID
    program_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_artifact_ids: tuple[UUID, ...] = Field(min_length=1)


class AdrgNarrativeSection(StrictModel):
    section_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    heading: str = Field(min_length=1, max_length=500)
    paragraphs: tuple[Annotated[str, Field(min_length=1, max_length=8000)], ...] = ()


class AdamAdrgModel(StrictModel):
    """Versioned ADRG content with immutable facts separate from manual narrative."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    title: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=64)
    specification_revision: int = Field(ge=1)
    input_selection_revision: int = Field(ge=1)
    plan_revision: int = Field(ge=1)
    define_revision: int = Field(ge=1)
    reconciliation_run_id: UUID
    output_artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    dataset_facts: tuple[AdrgDatasetFact, ...] = Field(min_length=1)
    execution_facts: tuple[AdrgExecutionFact, ...] = Field(min_length=1)
    narrative_sections: tuple[AdrgNarrativeSection, ...] = ()

    @model_validator(mode="after")
    def unique_content(self) -> "AdamAdrgModel":
        datasets = [item.dataset for item in self.dataset_facts]
        dataset_artifacts = [item.xpt_artifact_id for item in self.dataset_facts]
        executions = [item.execution_run_id for item in self.execution_facts]
        sections = [item.section_id for item in self.narrative_sections]
        if len(datasets) != len(set(datasets)) or len(dataset_artifacts) != len(
            set(dataset_artifacts)
        ):
            raise ValueError("ADRG dataset facts and XPT artifacts must be unique")
        if len(executions) != len(set(executions)):
            raise ValueError("ADRG execution facts must be unique")
        if len(sections) != len(set(sections)):
            raise ValueError("ADRG narrative section IDs must be unique")
        if set(dataset_artifacts) != set(self.output_artifact_ids):
            raise ValueError("ADRG dataset facts must cover exact selected outputs")
        execution_outputs = {
            artifact_id for item in self.execution_facts for artifact_id in item.output_artifact_ids
        }
        if not set(self.output_artifact_ids) <= execution_outputs:
            raise ValueError("ADRG outputs must resolve to its exact execution facts")
        return self


class AdamAdrgInitialize(StrictModel):
    expected_adrg_revision: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=64)
    define_revision: int = Field(ge=1)
    reconciliation_run_id: UUID
