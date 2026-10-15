"""Strict SDTM-owned authoring contracts and Raw input selection."""

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.transformation.contracts import (
    CustomFunctionDefinition,
    DerivationExpression,
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


class SdtmValueLevelMetadata(StrictModel):
    id: str
    variable: str
    condition: Expression
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
        return self


class SdtmSpecification(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    domains: tuple[SdtmDomain, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_domains(self) -> "SdtmSpecification":
        codes = [item.code for item in self.domains]
        outputs = [item.expected_output_name for item in self.domains]
        if len(codes) != len(set(codes)) or len(outputs) != len(set(outputs)):
            raise ValueError("domain codes and output names must be unique")
        if any(
            custom_function_calls(item.condition)
            for domain in self.domains
            for item in domain.value_level_metadata
        ):
            raise ValueError("custom functions may only be called from a Derivation Plan")
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


class RawReadNode(StrictModel):
    node_type: Literal["raw_read"]
    id: str
    raw_dataset_code: str


class SdtmReadNode(StrictModel):
    node_type: Literal["sdtm_read"]
    id: str = Field(min_length=1, max_length=128)
    dataset: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")  # upstream SDTM domain code


class FilterNode(StrictModel):
    node_type: Literal["filter"]
    id: str
    predicate: Expression


def _expression_column_references(
    expression: DerivationExpression,
) -> tuple[tuple[str, str], ...]:
    """Collect typed column references without interpreting function semantics."""

    if expression.kind == "column":
        return ((expression.dataset, expression.column),)
    if expression.kind == "unary":
        return _expression_column_references(expression.operand)
    if expression.kind == "binary":
        return (
            *_expression_column_references(expression.left),
            *_expression_column_references(expression.right),
        )
    if expression.kind == "conditional":
        references: list[tuple[str, str]] = []
        for branch in expression.branches:
            references.extend(_expression_column_references(branch.when))
            references.extend(_expression_column_references(branch.then))
        references.extend(_expression_column_references(expression.otherwise))
        return tuple(references)
    if expression.kind == "function":
        references = []
        for argument in expression.arguments:
            if argument.kind != "list_literal":
                references.extend(_expression_column_references(argument))
        return tuple(references)
    if expression.kind == "custom_function":
        references = []
        for argument in expression.arguments:
            references.extend(_expression_column_references(argument))
        return tuple(references)
    if expression.kind == "cast":
        return _expression_column_references(expression.value)
    if expression.kind == "terminology_map":
        return _expression_column_references(expression.value)
    return ()


class DeriveNode(StrictModel):
    node_type: Literal["derive"]
    id: str
    target_domain: str
    assignments: dict[str, DerivationExpression] = Field(min_length=1)
    assignment_order: tuple[str, ...] = ()

    @model_validator(mode="after")
    def ordered_assignment_dependencies(self) -> "DeriveNode":
        """Preserve recipe order independently of JSON-object key ordering."""

        targets = set(self.assignments)
        order = self.assignment_order
        if order:
            if len(order) != len(set(order)) or set(order) != targets:
                raise ValueError("assignment_order must list every assignment exactly once")
        else:
            # Revisions saved before assignment_order existed may have had their
            # JSON-object keys reordered by PostgreSQL JSONB. Recover a stable,
            # dependency-safe order instead of treating that storage order as
            # authored intent.
            dependencies_by_target = {
                target: {
                    column
                    for dataset, column in _expression_column_references(expression)
                    if dataset == self.target_domain and column in targets
                }
                for target, expression in self.assignments.items()
            }
            resolved: list[str] = []
            resolved_targets: set[str] = set()
            while len(resolved) < len(targets):
                ready = sorted(
                    target
                    for target in targets - resolved_targets
                    if dependencies_by_target[target] <= resolved_targets
                )
                if not ready:
                    raise ValueError("assignment dependencies must not contain a cycle")
                resolved.extend(ready)
                resolved_targets.update(ready)
            order = tuple(resolved)
            self.assignment_order = order

        available: set[str] = set()
        for target in order:
            expression = self.assignments[target]
            dependencies = {
                column
                for dataset, column in _expression_column_references(expression)
                if dataset == self.target_domain and column in targets
            }
            unavailable = sorted(dependencies - available)
            if unavailable:
                joined = ", ".join(unavailable)
                raise ValueError(
                    f"assignment '{target}' references target-domain variable(s) {joined} "
                    "before they are derived; reorder the assignments and remove cycles"
                )
            available.add(target)
        self.assignments = {target: self.assignments[target] for target in order}
        return self


class SelectNode(StrictModel):
    node_type: Literal["select"]
    id: str
    columns: tuple[str, ...] = Field(min_length=1)


class JoinNode(StrictModel):
    node_type: Literal["join"]
    id: str
    join_type: Literal["inner", "left", "right", "full"]
    left_input: str
    right_input: str
    keys: tuple[tuple[str, str], ...] = Field(min_length=1)
    right_suffix: str = Field(default="_right", pattern=r"^_[A-Za-z0-9_]{1,16}$")


class UnionNode(StrictModel):
    node_type: Literal["union"]
    id: str


class SdtmAggregation(StrictModel):
    operation: Literal["count", "sum", "mean", "min", "max"]
    column: str | None = None

    @model_validator(mode="after")
    def source_required(self) -> "SdtmAggregation":
        if self.operation != "count" and self.column is None:
            raise ValueError("numeric aggregations require a source column")
        return self


class AggregateNode(StrictModel):
    node_type: Literal["aggregate"]
    id: str
    group_by: tuple[str, ...]
    aggregations: dict[str, SdtmAggregation] = Field(min_length=1)


class PivotLongerNode(StrictModel):
    node_type: Literal["pivot_longer"]
    id: str
    id_columns: tuple[str, ...]
    value_columns: tuple[str, ...] = Field(min_length=1)
    name_column: str
    value_column: str


class SequenceNode(StrictModel):
    node_type: Literal["sequence"]
    id: str
    group_by: tuple[str, ...] = ()
    order_by: tuple[str, ...] = Field(min_length=1)
    target_column: str
    start: int = Field(default=1, ge=0)


class SortNode(StrictModel):
    node_type: Literal["sort"]
    id: str
    keys: tuple[str, ...] = Field(min_length=1)


class AssertNode(StrictModel):
    node_type: Literal["assert"]
    id: str
    predicate: Expression
    issue_code: str


class DomainWriteNode(StrictModel):
    node_type: Literal["domain_write"]
    id: str
    domain: str


SdtmPlanNode = Annotated[
    RawReadNode
    | SdtmReadNode
    | FilterNode
    | DeriveNode
    | SelectNode
    | JoinNode
    | UnionNode
    | AggregateNode
    | PivotLongerNode
    | SequenceNode
    | SortNode
    | AssertNode
    | DomainWriteNode,
    Field(discriminator="node_type"),
]


class PlanEdge(StrictModel):
    source_node: str
    target_node: str


class SdtmDerivationPlan(StrictModel):
    schema_version: Literal["1.2.0"] = "1.2.0"
    domain: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    specification_revision: int = Field(ge=1)
    input_selection_revision: int = Field(ge=1)
    custom_functions: tuple[CustomFunctionDefinition, ...] = ()
    nodes: tuple[SdtmPlanNode, ...] = Field(min_length=1)
    edges: tuple[PlanEdge, ...] = ()

    @model_validator(mode="after")
    def valid_graph(self) -> "SdtmDerivationPlan":
        function_ids = [item.id for item in self.custom_functions]
        if len(function_ids) != len(set(function_ids)):
            raise ValueError("custom function IDs must be unique")
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("plan node IDs must be unique")
        known = set(ids)
        indegree = dict.fromkeys(ids, 0)
        outgoing: dict[str, list[str]] = {item: [] for item in ids}
        for edge in self.edges:
            if edge.source_node not in known or edge.target_node not in known:
                raise ValueError("plan edges must resolve to known nodes")
            indegree[edge.target_node] += 1
            outgoing[edge.source_node].append(edge.target_node)
        queue = [item for item, count in indegree.items() if count == 0]
        visited = 0
        while queue:
            current = queue.pop()
            visited += 1
            for target in outgoing[current]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if visited != len(ids):
            raise ValueError("plan graph must be acyclic")
        edge_pairs = {(edge.source_node, edge.target_node) for edge in self.edges}
        for node in self.nodes:
            if node.node_type == "join" and (
                node.left_input == node.right_input
                or node.left_input not in known
                or node.right_input not in known
                or (node.left_input, node.id) not in edge_pairs
                or (node.right_input, node.id) not in edge_pairs
            ):
                raise ValueError("join inputs must be distinct declared incoming nodes")
        return self


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


class AcrfPlanNodeLink(StrictModel):
    target_type: Literal["derivation_plan_node"]
    plan_revision: int = Field(ge=1)
    node_id: str = Field(min_length=1, max_length=128)
    domain: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9]{1,7}$")


AcrfLink = Annotated[
    AcrfSdtmVariableLink | AcrfRawVariableLink | AcrfPlanNodeLink,
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
