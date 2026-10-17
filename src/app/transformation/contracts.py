"""Internal typed Dataflow and Analysis IR contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


CustomFunctionLanguage = Literal["python", "r", "sas"]
CustomFunctionReturnType = Literal[
    "character", "numeric", "logical", "date", "datetime", "result_rows"
]


class CustomFunctionImplementation(StrictModel):
    """One manually authored language body for a custom function.

    The compiler supplies the function declaration and parameter list. ``source``
    therefore contains only the language-specific body (including its return).
    It is never evaluated by API or preview processes.
    """

    language: CustomFunctionLanguage
    source: str = Field(min_length=1, max_length=32768)

    @model_validator(mode="after")
    def valid_source(self) -> "CustomFunctionImplementation":
        if not self.source.strip():
            raise ValueError("custom function source must not be blank")
        if "\x00" in self.source:
            raise ValueError("custom function source must not contain NUL bytes")
        return self


class CustomFunctionDefinition(StrictModel):
    """Typed custom-function signature plus one or more language bodies."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    parameters: tuple[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")], ...] = Field(
        max_length=32
    )
    return_type: CustomFunctionReturnType
    implementations: tuple[CustomFunctionImplementation, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_signature(self) -> "CustomFunctionDefinition":
        if len(self.parameters) != len(set(self.parameters)):
            raise ValueError("custom function parameter names must be unique")
        languages = [item.language for item in self.implementations]
        if len(languages) != len(set(languages)):
            raise ValueError("custom function implementations must be unique by language")
        return self

    def implementation(self, language: CustomFunctionLanguage) -> str | None:
        """Return the exact body for ``language`` when the user supplied one."""

        return next(
            (item.source for item in self.implementations if item.language == language), None
        )


class LiteralExpression(StrictModel):
    kind: Literal["literal"]
    value: str | int | float | bool | None


class ColumnExpression(StrictModel):
    kind: Literal["column"]
    dataset: str | None = Field(
        default=None,
        json_schema_extra={"deprecated": True},
        description=(
            "Legacy source label. Column values are always read from the row entering "
            "the current operator."
        ),
    )
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


class CustomFunctionCallExpression(StrictModel):
    kind: Literal["custom_function"]
    function_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    arguments: tuple["Expression", ...]


Expression = Annotated[
    LiteralExpression
    | ColumnExpression
    | UnaryExpression
    | BinaryExpression
    | ConditionalExpression
    | FunctionCallExpression
    | CustomFunctionCallExpression
    | ListLiteralExpression,
    Field(discriminator="kind"),
]


class CastExpression(StrictModel):
    """Convert one derived value to a declared scalar type."""

    kind: Literal["cast"]
    value: "Expression"
    target_type: Literal["text", "integer", "float", "boolean"]
    invalid: Literal["error", "null"] = "error"


class TerminologyMapExpression(StrictModel):
    """Apply a manually authored controlled-terminology value mapping."""

    kind: Literal["terminology_map"]
    value: "Expression"
    mappings: dict[str, str] = Field(min_length=1)
    unmapped: Literal["preserve", "null", "error"] = "error"


DerivationExpression = Annotated[
    LiteralExpression
    | ColumnExpression
    | UnaryExpression
    | BinaryExpression
    | ConditionalExpression
    | FunctionCallExpression
    | CustomFunctionCallExpression
    | CastExpression
    | TerminologyMapExpression
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
    assignments: dict[str, DerivationExpression] = Field(min_length=1)
    assignment_order: tuple[str, ...] = ()
    result_types: dict[str, Literal["character", "numeric"]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_assignment_order(self) -> "DeriveNode":
        """Keep derive presentation and canonical order explicit across JSONB serialization."""

        order = self.assignment_order or tuple(self.assignments)
        if len(order) != len(set(order)) or set(order) != set(self.assignments):
            raise ValueError("assignment_order must list every assignment exactly once")
        object.__setattr__(self, "assignment_order", order)
        object.__setattr__(
            self,
            "assignments",
            {target: self.assignments[target] for target in order},
        )
        return self

    def ordered_assignments(self) -> tuple[tuple[str, DerivationExpression], ...]:
        """Return assignments in their persisted deterministic output order."""

        return tuple((target, self.assignments[target]) for target in self.assignment_order)


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
    operator_version: Literal["1.4.0"] = "1.4.0"
    custom_functions: tuple[CustomFunctionDefinition, ...] = ()
    nodes: tuple[DataflowNode, ...] = Field(min_length=1)
    edges: tuple[Edge, ...] = ()

    @model_validator(mode="after")
    def validate_dag(self) -> "DataflowIR":
        function_ids = [item.id for item in self.custom_functions]
        if len(function_ids) != len(set(function_ids)):
            raise ValueError("custom function IDs must be unique")
        functions = {item.id: item for item in self.custom_functions}
        if any(item.return_type == "result_rows" for item in self.custom_functions):
            raise ValueError("Dataflow custom functions must return a scalar type")
        expressions: list[DerivationExpression] = []
        for node in self.nodes:
            if node.node_type == "derive":
                expressions.extend(node.assignments.values())
            elif node.node_type == "filter" or node.node_type == "assert":
                expressions.append(node.predicate)
        for expression in expressions:
            for call in custom_function_calls(expression):
                definition = functions.get(call.function_id)
                if definition is None:
                    raise ValueError(
                        f"custom function call '{call.function_id}' must resolve to a definition"
                    )
                if len(call.arguments) != len(definition.parameters):
                    raise ValueError(
                        f"custom function '{call.function_id}' expects "
                        f"{len(definition.parameters)} arguments, got {len(call.arguments)}"
                    )
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
    method: Literal["descriptive_statistics", "frequency", "linear_model", "survival", "custom"]
    input_dataset: str
    grouping: tuple[str, ...] = ()
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    result_schema: dict[str, str] = Field(min_length=1)
    tolerance: float | None = Field(default=None, ge=0)
    custom_function_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,62}$")

    @model_validator(mode="after")
    def valid_custom_method(self) -> "AnalysisProcedure":
        if (self.method == "custom") != (self.custom_function_id is not None):
            raise ValueError("custom analysis methods require exactly one custom_function_id")
        return self


class AnalysisIR(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    procedure_version: Literal["1.0.0"] = "1.0.0"
    custom_functions: tuple[CustomFunctionDefinition, ...] = ()
    preparation: DataflowIR | None = None
    procedures: tuple[AnalysisProcedure, ...] = Field(min_length=1)
    postprocessing: DataflowIR | None = None

    @model_validator(mode="after")
    def valid_custom_functions(self) -> "AnalysisIR":
        identifiers = [item.id for item in self.custom_functions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("custom function IDs must be unique")
        known = set(identifiers)
        for procedure in self.procedures:
            if (
                procedure.custom_function_id is not None
                and procedure.custom_function_id not in known
            ):
                raise ValueError("custom analysis function references must resolve")
        return self


def custom_function_calls(
    expression: Expression | DerivationExpression,
) -> tuple[CustomFunctionCallExpression, ...]:
    """Return custom calls recursively for signature validation."""

    calls: list[CustomFunctionCallExpression] = []
    if expression.kind == "custom_function":
        calls.append(expression)
        children = expression.arguments
    elif expression.kind == "function":
        children = expression.arguments
    elif expression.kind == "conditional":
        children = tuple(
            child for branch in expression.branches for child in (branch.when, branch.then)
        ) + (expression.otherwise,)
    elif expression.kind == "unary":
        children = (expression.operand,)
    elif expression.kind == "binary":
        children = (expression.left, expression.right)
    elif expression.kind == "cast" or expression.kind == "terminology_map":
        children = (expression.value,)
    else:
        children = ()
    for child in children:
        calls.extend(custom_function_calls(child))
    return tuple(calls)
