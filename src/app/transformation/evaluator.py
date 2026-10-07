"""Bounded evaluator for previews of trusted, normalized Dataflow IR."""

from collections.abc import Mapping, Sequence
from typing import cast

from app.common.problems import ProblemException
from app.transformation.contracts import Aggregation, DataflowIR, Expression, WindowOperation

type Scalar = object | None
type Row = dict[str, Scalar]


def _problem(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=422,
        code=code,
        title="Dataflow preview cannot be evaluated",
        detail=detail,
    )


def _value(expression: Expression, row: Mapping[str, Scalar]) -> Scalar:
    if expression.kind == "literal":
        return expression.value
    if expression.kind == "column":
        if expression.column not in row:
            raise _problem(
                "preview_column_unknown", f"Column '{expression.column}' is not available."
            )
        return row[expression.column]
    if expression.kind == "unary":
        operand = _value(expression.operand, row)
        if expression.operator == "not":
            return not bool(operand)
        if expression.operator == "is_null":
            return operand is None
        if expression.operator == "is_not_null":
            return operand is not None
        if operand is None:
            return None
        try:
            return cast(Scalar, -operand)  # type: ignore[operator]
        except TypeError as error:
            raise _problem(
                "preview_expression_type_invalid", "Negation requires a number."
            ) from error

    left = _value(expression.left, row)
    right = _value(expression.right, row)
    operator = expression.operator
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "and":
        return bool(left) and bool(right)
    if operator == "or":
        return bool(left) or bool(right)
    if left is None or right is None:
        return None
    try:
        if operator == "lt":
            return cast(Scalar, left < right)  # type: ignore[operator]
        if operator == "le":
            return cast(Scalar, left <= right)  # type: ignore[operator]
        if operator == "gt":
            return cast(Scalar, left > right)  # type: ignore[operator]
        if operator == "ge":
            return cast(Scalar, left >= right)  # type: ignore[operator]
        if operator == "add":
            return cast(Scalar, left + right)  # type: ignore[operator]
        if operator == "sub":
            return cast(Scalar, left - right)  # type: ignore[operator]
        if operator == "mul":
            return cast(Scalar, left * right)  # type: ignore[operator]
        if operator == "div":
            return cast(Scalar, left / right)  # type: ignore[operator]
    except (TypeError, ZeroDivisionError) as error:
        raise _problem(
            "preview_expression_type_invalid", f"Operator '{operator}' has incompatible operands."
        ) from error
    raise AssertionError(f"unhandled expression operator: {operator}")


def _single_input(node_id: str, incoming: Sequence[list[Row]]) -> list[Row]:
    if len(incoming) != 1:
        raise _problem(
            "preview_graph_input_invalid", f"Node '{node_id}' requires exactly one input."
        )
    return incoming[0]


def _cast(value: Scalar, target_type: str, invalid: str) -> Scalar:
    if value is None or value == "":
        return None
    try:
        if target_type == "text":
            return str(value)
        if target_type == "integer":
            return int(str(value))
        if target_type == "float":
            return float(str(value))
        normalized = str(value).strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
        raise ValueError("not a declared boolean representation")
    except (TypeError, ValueError) as error:
        if invalid == "null":
            return None
        raise _problem(
            "preview_cast_invalid",
            f"Value '{value}' cannot be cast to {target_type}.",
        ) from error


def _join_rows(
    left: list[Row],
    right: list[Row],
    keys: tuple[tuple[str, str], ...],
    join_type: str,
    suffix: str,
) -> list[Row]:
    right_index: dict[tuple[Scalar, ...], list[tuple[int, Row]]] = {}
    for index, row in enumerate(right):
        key = tuple(row.get(right_key) for _, right_key in keys)
        if any(value is None for value in key):
            continue
        right_index.setdefault(key, []).append((index, row))
    matched_right: set[int] = set()
    result: list[Row] = []
    for left_row in left:
        key = tuple(left_row.get(left_key) for left_key, _ in keys)
        matches = [] if any(value is None for value in key) else right_index.get(key, [])
        if not matches and join_type in {"left", "full"}:
            result.append(dict(left_row))
        for right_index_value, right_row in matches:
            matched_right.add(right_index_value)
            combined = dict(left_row)
            right_key_names = {right_key for _, right_key in keys}
            for name, value in right_row.items():
                if name in right_key_names:
                    continue
                combined[name if name not in combined else f"{name}{suffix}"] = value
            result.append(combined)
    if join_type in {"right", "full"}:
        left_columns = tuple(dict.fromkeys(name for row in left for name in row))
        for index, right_row in enumerate(right):
            if index in matched_right:
                continue
            combined = {name: None for name in left_columns}
            for left_key, right_key in keys:
                combined[left_key] = right_row.get(right_key)
            right_key_names = {right_key for _, right_key in keys}
            for name, value in right_row.items():
                if name not in right_key_names:
                    combined[name if name not in combined else f"{name}{suffix}"] = value
            result.append(combined)
    return result


def _aggregate(
    rows: list[Row], group_by: tuple[str, ...], specs: dict[str, Aggregation]
) -> list[Row]:
    groups: dict[tuple[Scalar, ...], list[Row]] = {}
    for row in rows:
        groups.setdefault(tuple(row.get(name) for name in group_by), []).append(row)
    if not rows and not group_by:
        groups[()] = []
    result: list[Row] = []
    for key, members in groups.items():
        output: Row = dict(zip(group_by, key, strict=True))
        for target, spec in specs.items():
            values = (
                [row.get(spec.column) for row in members if row.get(spec.column) is not None]
                if spec.column is not None
                else []
            )
            if spec.operation == "count":
                output[target] = len(values) if spec.column is not None else len(members)
            else:
                try:
                    numeric = [float(str(value)) for value in values]
                except (TypeError, ValueError) as error:
                    raise _problem(
                        "preview_aggregate_type_invalid",
                        f"Aggregation '{target}' requires numeric values.",
                    ) from error
                if not numeric:
                    output[target] = None
                elif spec.operation == "sum":
                    output[target] = sum(numeric)
                elif spec.operation == "mean":
                    output[target] = sum(numeric) / len(numeric)
                elif spec.operation == "min":
                    output[target] = min(numeric)
                else:
                    output[target] = max(numeric)
        result.append(output)
    return result


def _window_rows(
    rows: list[Row],
    partition_by: tuple[str, ...],
    order_by: tuple[str, ...],
    operations: dict[str, WindowOperation],
) -> list[Row]:
    result = [dict(row) for row in rows]
    keys = (*partition_by, *order_by)
    try:
        result.sort(key=lambda row: tuple((row.get(key) is None, row.get(key)) for key in keys))
    except TypeError as error:
        raise _problem(
            "preview_window_type_invalid", "Window keys contain incompatible value types."
        ) from error
    groups: dict[tuple[Scalar, ...], list[Row]] = {}
    for row in result:
        groups.setdefault(tuple(row.get(name) for name in partition_by), []).append(row)
    for members in groups.values():
        for target, operation in operations.items():
            kind = operation.operation
            source_column = operation.source_column
            offset = operation.offset
            if kind == "row_number":
                for position, row in enumerate(members, start=1):
                    row[target] = position
            elif kind == "lag":
                assert source_column is not None
                for position, row in enumerate(members):
                    row[target] = (
                        None if position < offset else members[position - offset].get(source_column)
                    )
            else:
                assert source_column is not None
                running = 0.0
                for row in members:
                    value = row.get(source_column)
                    if value is None or value == "":
                        row[target] = None
                        continue
                    try:
                        running += float(str(value))
                    except (TypeError, ValueError) as error:
                        raise _problem(
                            "preview_window_type_invalid",
                            f"Window operation '{target}' requires numeric values.",
                        ) from error
                    row[target] = running
    return result


def evaluate_dataflow(
    ir: DataflowIR,
    datasets: Mapping[str, Sequence[Mapping[str, Scalar]]],
    *,
    row_limit: int = 100,
) -> dict[str, tuple[Row, ...]]:
    """Evaluate normalized operators for a bounded preview, returning declared writes."""

    if row_limit < 1 or row_limit > 200:
        raise ValueError("row_limit must be between 1 and 200")
    nodes = {node.id: node for node in ir.nodes}
    incoming_ids: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    indegree = dict.fromkeys(nodes, 0)
    for edge in ir.edges:
        incoming_ids[edge.target_node].append(edge.source_node)
        outgoing[edge.source_node].append(edge.target_node)
        indegree[edge.target_node] += 1
    for sources in incoming_ids.values():
        sources.sort()
    queue = [node_id for node_id, count in indegree.items() if count == 0]
    values: dict[str, list[Row]] = {}
    outputs: dict[str, tuple[Row, ...]] = {}
    while queue:
        node_id = queue.pop(0)
        node = nodes[node_id]
        inputs = [values[source] for source in incoming_ids[node_id]]
        if node.node_type == "read":
            source = datasets.get(node.dataset)
            if source is None:
                raise _problem(
                    "preview_dataset_unknown", f"Dataset '{node.dataset}' was not selected."
                )
            result = [dict(row) for row in source[:row_limit]]
        elif node.node_type == "select":
            result = [
                {column: row.get(column) for column in node.columns}
                for row in _single_input(node.id, inputs)
            ]
        elif node.node_type == "filter":
            result = [
                row for row in _single_input(node.id, inputs) if bool(_value(node.predicate, row))
            ]
        elif node.node_type == "derive":
            result = []
            for source_row in _single_input(node.id, inputs):
                row = dict(source_row)
                for name, expression in node.assignments.items():
                    row[name] = _value(expression, row)
                result.append(row)
        elif node.node_type == "cast":
            result = []
            for source_row in _single_input(node.id, inputs):
                row = dict(source_row)
                for target, operation in node.casts.items():
                    row[target] = _cast(
                        row.get(operation.source_column),
                        operation.target_type,
                        operation.invalid,
                    )
                result.append(row)
        elif node.node_type == "sort":
            source_rows = _single_input(node.id, inputs)
            try:
                result = sorted(
                    source_rows,
                    key=lambda row: tuple(
                        (row.get(key) is None, row.get(key)) for key in node.keys
                    ),
                )
            except TypeError as error:
                raise _problem(
                    "preview_sort_type_invalid", "Sort keys contain incompatible value types."
                ) from error
        elif node.node_type == "assert":
            result = _single_input(node.id, inputs)
            if any(not bool(_value(node.predicate, row)) for row in result):
                raise _problem(node.issue_code, f"Assertion '{node.id}' failed in preview rows.")
        elif node.node_type == "union":
            result = [row for source in inputs for row in source]
        elif node.node_type == "join":
            if set(incoming_ids[node.id]) != {node.left_input, node.right_input}:
                raise _problem(
                    "preview_join_inputs_invalid",
                    f"Join '{node.id}' inputs do not match its declared left and right inputs.",
                )
            result = _join_rows(
                values[node.left_input],
                values[node.right_input],
                node.keys,
                node.join_type,
                node.right_suffix,
            )
        elif node.node_type == "aggregate":
            result = _aggregate(_single_input(node.id, inputs), node.group_by, node.aggregations)
        elif node.node_type == "pivot_longer":
            result = []
            for row in _single_input(node.id, inputs):
                for column in node.value_columns:
                    result.append(
                        {
                            **{name: row.get(name) for name in node.id_columns},
                            node.name_column: column,
                            node.value_column: row.get(column),
                        }
                    )
        elif node.node_type == "terminology_map":
            result = []
            for source_row in _single_input(node.id, inputs):
                row = dict(source_row)
                source_value = row.get(node.source_column)
                mapped = node.mappings.get(str(source_value)) if source_value is not None else None
                if mapped is None and node.unmapped == "error":
                    raise _problem(
                        "preview_terminology_unmapped",
                        f"Value '{source_value}' has no declared terminology mapping.",
                    )
                row[node.target_column] = (
                    source_value if mapped is None and node.unmapped == "preserve" else mapped
                )
                result.append(row)
        elif node.node_type == "sequence":
            source_rows = [dict(row) for row in _single_input(node.id, inputs)]
            keys = (*node.group_by, *node.order_by)
            try:
                source_rows.sort(
                    key=lambda row: tuple((row.get(key) is None, row.get(key)) for key in keys)
                )
            except TypeError as error:
                raise _problem(
                    "preview_sequence_type_invalid",
                    "Sequence keys contain incompatible value types.",
                ) from error
            counters: dict[tuple[Scalar, ...], int] = {}
            for row in source_rows:
                group = tuple(row.get(name) for name in node.group_by)
                value = counters.get(group, node.start)
                row[node.target_column] = value
                counters[group] = value + 1
            result = source_rows
        elif node.node_type == "window":
            result = _window_rows(
                _single_input(node.id, inputs),
                node.partition_by,
                node.order_by,
                node.operations,
            )
        elif node.node_type == "write":
            result = _single_input(node.id, inputs)
            outputs[node.dataset] = tuple(result[:row_limit])
        else:
            raise AssertionError(f"unhandled node type: {node.node_type}")
        values[node.id] = result[:row_limit]
        for target in outgoing[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return outputs
