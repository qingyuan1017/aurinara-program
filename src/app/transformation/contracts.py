"""Internal typed Dataflow and Analysis IR contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LiteralExpression(StrictModel):
    kind: Literal["literal"]
    value: str | int | float | bool | None


class ColumnExpression(StrictModel):
    kind: Literal["column"]
    dataset: str
    column: str


class UnaryExpression(StrictModel):
    kind: Literal["unary"]
    operator: Literal["not", "is_null", "is_not_null", "negate"]
    operand: "Expression"


class BinaryExpression(StrictModel):
    kind: Literal["binary"]
    operator: Literal["eq", "ne", "lt", "le", "gt", "ge", "and", "or", "add", "sub", "mul", "div"]
    left: "Expression"
    right: "Expression"


class ConditionalBranch(StrictModel):
    when: "Expression"
    then: "Expression"


class ConditionalExpression(StrictModel):
    kind: Literal["conditional"]
    branches: tuple[ConditionalBranch, ...] = Field(min_length=1)
    otherwise: "Expression"


FunctionName = Literal[
    # String
    "concat",
    "substring",
    "upper",
    "lower",
    "trim",
    "length",
    "contains",
    "startswith",
    "endswith",
    "replace",
    "index_of",
    "scan_token",
    "pad_left",
    "pad_right",
    # Null / logical
    "coalesce",
    "nullif",
    "is_in",
    "n_missing",
    "n_present",
    # Numeric
    "round",
    "floor",
    "ceil",
    "abs",
    "modulo",
    "min_of",
    "max_of",
    "truncate",
    "safe_divide",
    # Date / datetime
    "parse_date",
    "year",
    "month",
    "day",
    "date_diff_days",
    "parse_datetime",
    "hour",
    "minute",
    "second",
    "study_day",
    "date_add_days",
    "date_diff_months",
]

# Exact fixed arities per function. Variadic functions carry a minimum count.
_FUNCTION_ARITY: dict[str, int] = {
    "substring": 3,
    "upper": 1,
    "lower": 1,
    "trim": 1,
    "length": 1,
    "contains": 2,
    "startswith": 2,
    "endswith": 2,
    "replace": 3,
    "index_of": 2,
    "scan_token": 3,
    "pad_left": 3,
    "pad_right": 3,
    "nullif": 2,
    "is_in": 2,
    "round": 2,
    "floor": 1,
    "ceil": 1,
    "abs": 1,
    "modulo": 2,
    "truncate": 1,
    "safe_divide": 2,
    "parse_date": 1,
    "year": 1,
    "month": 1,
    "day": 1,
    "date_diff_days": 2,
    "parse_datetime": 1,
    "hour": 1,
    "minute": 1,
    "second": 1,
    "study_day": 2,
    "date_add_days": 2,
    "date_diff_months": 2,
}

# Variadic functions and their minimum argument counts.
_FUNCTION_MIN_ARITY: dict[str, int] = {
    "concat": 1,
    "coalesce": 1,
    "min_of": 1,
    "max_of": 1,
    "n_missing": 1,
    "n_present": 1,
}


class ListLiteralExpression(StrictModel):
    kind: Literal["list_literal"]
    values: tuple[str | int | float | bool | None, ...] = Field(min_length=1)


class FunctionCallExpression(StrictModel):
    kind: Literal["function"]
    function: FunctionName
    arguments: tuple["Expression", ...]

    @model_validator(mode="after")
    def validate_signature(self) -> "FunctionCallExpression":
        count = len(self.arguments)
        if self.function in _FUNCTION_ARITY:
            expected = _FUNCTION_ARITY[self.function]
            if count != expected:
                raise ValueError(
                    f"function '{self.function}' expects {expected} arguments, got {count}"
                )
        else:
            minimum = _FUNCTION_MIN_ARITY[self.function]
            if count < minimum:
                raise ValueError(
                    f"function '{self.function}' expects at least {minimum} arguments, got {count}"
                )
        # A ListLiteralExpression may appear ONLY as the second argument of is_in,
        # and is_in requires one there.
        for index, argument in enumerate(self.arguments):
            is_list_literal = getattr(argument, "kind", None) == "list_literal"
            allowed_slot = self.function == "is_in" and index == 1
            if is_list_literal and not allowed_slot:
                raise ValueError("a list literal is only valid as the second argument of is_in")
            if allowed_slot and not is_list_literal:
                raise ValueError("is_in requires a list literal as its second argument")
        return self


Expression = Annotated[
    LiteralExpression
    | ColumnExpression
    | UnaryExpression
    | BinaryExpression
    | ConditionalExpression
    | FunctionCallExpression
    | ListLiteralExpression,
    Field(discriminator="kind"),
]


class ReadNode(StrictModel):
    node_type: Literal["read"]
    id: str
    dataset: str


class SelectNode(StrictModel):
    node_type: Literal["select"]
    id: str
    columns: tuple[str, ...] = Field(min_length=1)


class FilterNode(StrictModel):
    node_type: Literal["filter"]
    id: str
    predicate: Expression


class DeriveNode(StrictModel):
    node_type: Literal["derive"]
    id: str
    assignments: dict[str, Expression] = Field(min_length=1)
    result_types: dict[str, Literal["character", "numeric"]] = Field(default_factory=dict)


class CastOperation(StrictModel):
    source_column: str
    target_type: Literal["text", "integer", "float", "boolean"]
    invalid: Literal["error", "null"] = "error"


class CastNode(StrictModel):
    node_type: Literal["cast"]
    id: str
    casts: dict[str, CastOperation] = Field(min_length=1)


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


class Aggregation(StrictModel):
    operation: Literal["count", "sum", "mean", "min", "max"]
    column: str | None = None

    @model_validator(mode="after")
    def source_required(self) -> "Aggregation":
        if self.operation != "count" and self.column is None:
            raise ValueError("numeric aggregations require a source column")
        return self


class AggregateNode(StrictModel):
    node_type: Literal["aggregate"]
    id: str
    group_by: tuple[str, ...]
    aggregations: dict[str, Aggregation] = Field(min_length=1)


class PivotLongerNode(StrictModel):
    node_type: Literal["pivot_longer"]
    id: str
    id_columns: tuple[str, ...]
    value_columns: tuple[str, ...] = Field(min_length=1)
    name_column: str
    value_column: str


class TerminologyMapNode(StrictModel):
    node_type: Literal["terminology_map"]
    id: str
    source_column: str
    target_column: str
    mappings: dict[str, str] = Field(min_length=1)
    unmapped: Literal["preserve", "null", "error"] = "error"


class SequenceNode(StrictModel):
    node_type: Literal["sequence"]
    id: str
    group_by: tuple[str, ...] = ()
    order_by: tuple[str, ...] = Field(min_length=1)
    target_column: str
    start: int = Field(default=1, ge=0)


class WindowOperation(StrictModel):
    operation: Literal["row_number", "lag", "cumulative_sum"]
    source_column: str | None = None
    offset: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def valid_source(self) -> "WindowOperation":
        if self.operation == "row_number" and self.source_column is not None:
            raise ValueError("row_number does not accept a source column")
        if self.operation != "row_number" and self.source_column is None:
            raise ValueError("lag and cumulative_sum require a source column")
        if self.operation != "lag" and self.offset != 1:
            raise ValueError("offset applies only to lag")
        return self


class WindowNode(StrictModel):
    node_type: Literal["window"]
    id: str
    partition_by: tuple[str, ...] = ()
    order_by: tuple[str, ...] = Field(min_length=1)
    operations: dict[str, WindowOperation] = Field(min_length=1)


class SortNode(StrictModel):
    node_type: Literal["sort"]
    id: str
    keys: tuple[str, ...] = Field(min_length=1)


class AssertNode(StrictModel):
    node_type: Literal["assert"]
    id: str
    predicate: Expression
    issue_code: str


class WriteNode(StrictModel):
    node_type: Literal["write"]
    id: str
    dataset: str


DataflowNode = Annotated[
    ReadNode
    | SelectNode
    | FilterNode
    | DeriveNode
    | CastNode
    | JoinNode
    | UnionNode
    | AggregateNode
    | PivotLongerNode
    | TerminologyMapNode
    | SequenceNode
    | WindowNode
    | SortNode
    | AssertNode
    | WriteNode,
    Field(discriminator="node_type"),
]


class Edge(StrictModel):
    source_node: str
    target_node: str


class DataflowIR(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    operator_version: Literal["1.2.0"] = "1.2.0"
    nodes: tuple[DataflowNode, ...] = Field(min_length=1)
    edges: tuple[Edge, ...] = ()

    @model_validator(mode="after")
    def validate_dag(self) -> "DataflowIR":
        identifiers = [node.id for node in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("node IDs must be unique")
        known = set(identifiers)
        incoming = dict.fromkeys(identifiers, 0)
        outgoing: dict[str, list[str]] = {item: [] for item in identifiers}
        for edge in self.edges:
            if edge.source_node not in known or edge.target_node not in known:
                raise ValueError("edges must resolve to known nodes")
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
            raise ValueError("Dataflow graph must be acyclic")
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


class AnalysisProcedure(StrictModel):
    id: str
    method: Literal["descriptive_statistics", "frequency", "linear_model", "survival"]
    input_dataset: str
    grouping: tuple[str, ...] = ()
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    result_schema: dict[str, str] = Field(min_length=1)
    tolerance: float | None = Field(default=None, ge=0)


class AnalysisIR(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    procedure_version: Literal["1.0.0"] = "1.0.0"
    preparation: DataflowIR | None = None
    procedures: tuple[AnalysisProcedure, ...] = Field(min_length=1)
    postprocessing: DataflowIR | None = None
