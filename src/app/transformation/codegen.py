"""Runnable deterministic source generation for supported Dataflow operators."""

from collections.abc import Callable

from app.transformation.contracts import DataflowIR, DataflowNode, Expression


class UnsupportedOperator(ValueError):
    """Raised when a backend cannot preserve one operator's semantics."""


def ordered_nodes(value: DataflowIR) -> tuple[DataflowNode, ...]:
    nodes = {node.id: node for node in value.nodes}
    degree = dict.fromkeys(nodes, 0)
    outgoing: dict[str, list[str]] = {name: [] for name in nodes}
    for edge in value.edges:
        degree[edge.target_node] += 1
        outgoing[edge.source_node].append(edge.target_node)
    queue = sorted(name for name, count in degree.items() if count == 0)
    result: list[DataflowNode] = []
    while queue:
        name = queue.pop(0)
        result.append(nodes[name])
        for target in sorted(outgoing[name]):
            degree[target] -= 1
            if degree[target] == 0:
                queue.append(target)
                queue.sort()
    return tuple(result)


def incoming_nodes(value: DataflowIR) -> dict[str, tuple[str, ...]]:
    inputs: dict[str, list[str]] = {node.id: [] for node in value.nodes}
    for edge in value.edges:
        inputs[edge.target_node].append(edge.source_node)
    return {name: tuple(sorted(items)) for name, items in inputs.items()}


def _single(node: DataflowNode, incoming: tuple[str, ...]) -> str:
    if len(incoming) != 1:
        raise UnsupportedOperator(f"{node.node_type}_input_arity")
    return incoming[0]


def _py_expr(expression: Expression, row: str = "row") -> str:
    if expression.kind == "literal":
        return repr(expression.value)
    if expression.kind == "column":
        return f"{row}[{expression.column!r}]"
    if expression.kind == "conditional":
        result = f"({_py_expr(expression.otherwise, row)})"
        for branch in reversed(expression.branches):
            when = _py_expr(branch.when, row)
            then = _py_expr(branch.then, row)
            result = (
                f"((guard(lambda: {then})) if "
                f"((_c := guard(lambda: {when})) is not None and bool(_c)) "
                f"else {result})"
            )
        return result
    if expression.kind == "unary":
        operand = _py_expr(expression.operand, row)
        return {
            "not": f"(not bool({operand}))",
            "is_null": f"({operand} is None)",
            "is_not_null": f"({operand} is not None)",
            "negate": f"(-number({operand}))",
        }[expression.operator]
    left, right = _py_expr(expression.left, row), _py_expr(expression.right, row)
    symbols = {
        "eq": "==",
        "ne": "!=",
        "lt": "<",
        "le": "<=",
        "gt": ">",
        "ge": ">=",
        "and": "and",
        "or": "or",
        "add": "+",
        "sub": "-",
        "mul": "*",
        "div": "/",
    }
    if expression.operator in {"add", "sub", "mul", "div"}:
        left, right = f"number({left})", f"number({right})"
    return f"({left} {symbols[expression.operator]} {right})"


def python_source(value: DataflowIR, digest: str) -> str:
    lines = [
        f"# aurinara-dataflow compiler=1.5.0 ir={digest}",
        "import csv",
        "import os",
        "from pathlib import Path",
        "",
        'root = Path(os.environ.get("AURINARA_WORKSPACE", "/workspace"))',
        'inputs = root / "inputs"',
        'outputs = root / "outputs"',
        "outputs.mkdir(parents=True, exist_ok=True)",
        'def number(value): return float(value) if "." in str(value) else int(value)',
        "def guard(thunk):",
        "    try: return thunk()",
        "    except (ZeroDivisionError, TypeError, ValueError): return None",
        "def read(name):",
        '    with (inputs / f"{name}.csv").open(encoding="utf-8-sig", newline="") as stream:',
        "        return list(csv.DictReader(stream))",
        "def write(name, rows):",
        "    fields = list(dict.fromkeys(key for row in rows for key in row))",
        '    with (outputs / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:',
        '        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")',
        "        if fields: writer.writeheader(); writer.writerows(rows)",
        "def cast_value(value, target_type, invalid):",
        "    if value in (None, ''): return None",
        "    try:",
        "        if target_type == 'text': return str(value)",
        "        if target_type == 'integer': return int(str(value))",
        "        if target_type == 'float': return float(str(value))",
        "        normalized = str(value).strip().lower()",
        "        if normalized in ('true', '1'): return True",
        "        if normalized in ('false', '0'): return False",
        "        raise ValueError('invalid boolean')",
        "    except (TypeError, ValueError):",
        "        if invalid == 'null': return None",
        "        raise RuntimeError('cast_invalid')",
        "def join_rows(left, right, keys, how, suffix):",
        "    index = {}",
        "    for position, row in enumerate(right):",
        "        key = tuple(row.get(pair[1]) for pair in keys)",
        "        if all(value not in (None, '') for value in key):",
        "            index.setdefault(key, []).append((position, row))",
        "    matched = set(); result = []",
        "    right_keys = {pair[1] for pair in keys}",
        "    for left_row in left:",
        "        key = tuple(left_row.get(pair[0]) for pair in keys)",
        "        matches = [] if any(value in (None, '') for value in key) else index.get(key, [])",
        "        if not matches and how in ('left', 'full'): result.append(dict(left_row))",
        "        for position, right_row in matches:",
        "            matched.add(position); combined = dict(left_row)",
        "            for name, value in right_row.items():",
        "                if name not in right_keys:",
        "                    target = name if name not in combined else name + suffix",
        "                    combined[target] = value",
        "            result.append(combined)",
        "    if how in ('right', 'full'):",
        "        left_columns = list(dict.fromkeys(name for row in left for name in row))",
        "        for position, right_row in enumerate(right):",
        "            if position in matched: continue",
        "            combined = {name: None for name in left_columns}",
        "            for left_key, right_key in keys:",
        "                combined[left_key] = right_row.get(right_key)",
        "            for name, value in right_row.items():",
        "                if name not in right_keys:",
        "                    target = name if name not in combined else name + suffix",
        "                    combined[target] = value",
        "            result.append(combined)",
        "    return result",
        "def aggregate_rows(rows, groups, specs):",
        "    grouped = {}",
        "    for row in rows:",
        "        key = tuple(row.get(name) for name in groups)",
        "        grouped.setdefault(key, []).append(row)",
        "    if not rows and not groups: grouped[()] = []",
        "    result = []",
        "    for key, members in grouped.items():",
        "        output = dict(zip(groups, key))",
        "        for target, spec in specs.items():",
        "            column = spec.get('column')",
        "            values = [row.get(column) for row in members",
        "                      if column is not None and row.get(column) not in (None, '')]",
        "            operation = spec['operation']",
        "            if operation == 'count':",
        "                output[target] = len(values) if column else len(members)",
        "                continue",
        "            numeric = [float(value) for value in values]",
        "            if not numeric: output[target] = None",
        "            elif operation == 'sum': output[target] = sum(numeric)",
        "            elif operation == 'mean': output[target] = sum(numeric) / len(numeric)",
        "            elif operation == 'min': output[target] = min(numeric)",
        "            else: output[target] = max(numeric)",
        "        result.append(output)",
        "    return result",
        "def window_rows(rows, partitions, orders, operations):",
        "    result = [dict(row) for row in rows]",
        "    keys = partitions + orders",
        "    result.sort(key=lambda row: tuple((row.get(name) is None, row.get(name))",
        "                                      for name in keys))",
        "    groups = {}",
        "    for row in result:",
        "        key = tuple(row.get(name) for name in partitions)",
        "        groups.setdefault(key, []).append(row)",
        "    for members in groups.values():",
        "        for target, operation in operations.items():",
        "            kind = operation['operation']",
        "            source = operation.get('source_column')",
        "            offset = operation.get('offset', 1)",
        "            if kind == 'row_number':",
        "                for position, row in enumerate(members, 1): row[target] = position",
        "            elif kind == 'lag':",
        "                for position, row in enumerate(members):",
        "                    row[target] = (None if position < offset",
        "                                   else members[position - offset].get(source))",
        "            else:",
        "                running = 0.0",
        "                for row in members:",
        "                    value = row.get(source)",
        "                    if value in (None, ''): row[target] = None; continue",
        "                    running += float(value); row[target] = running",
        "    return result",
        "state = {}",
    ]
    incoming = incoming_nodes(value)
    for node in ordered_nodes(value):
        target = repr(node.id)
        if node.node_type == "read":
            lines.append(f"state[{target}] = read({node.dataset!r})")
            continue
        if node.node_type == "union":
            sources = ", ".join(f"state[{item!r}]" for item in incoming[node.id])
            lines.append(f"state[{target}] = [row for rows in ({sources},) for row in rows]")
            continue
        if node.node_type == "join":
            lines.append(
                f"state[{target}] = join_rows(state[{node.left_input!r}], "
                f"state[{node.right_input!r}], {node.keys!r}, {node.join_type!r}, "
                f"{node.right_suffix!r})"
            )
            continue
        source = f"state[{_single(node, incoming[node.id])!r}]"
        if node.node_type == "select":
            lines.append(
                f"state[{target}] = [{{name: row.get(name) for name in "
                f"{node.columns!r}}} for row in {source}]"
            )
        elif node.node_type == "filter":
            lines.append(
                f"state[{target}] = [row for row in {source} if bool({_py_expr(node.predicate)})]"
            )
        elif node.node_type == "derive":
            lines.extend(
                [f"state[{target}] = []", f"for row in {source}:", "    next_row = dict(row)"]
            )
            for name, expression in node.assignments.items():
                lines.append(f"    next_row[{name!r}] = {_py_expr(expression, 'next_row')}")
            lines.append(f"    state[{target}].append(next_row)")
        elif node.node_type == "cast":
            lines.extend(
                [f"state[{target}] = []", f"for row in {source}:", "    next_row = dict(row)"]
            )
            for name, operation in node.casts.items():
                lines.append(
                    f"    next_row[{name!r}] = cast_value("
                    f"next_row.get({operation.source_column!r}), "
                    f"{operation.target_type!r}, {operation.invalid!r})"
                )
            lines.append(f"    state[{target}].append(next_row)")
        elif node.node_type == "aggregate":
            specs = {
                name: spec.model_dump(mode="python") for name, spec in node.aggregations.items()
            }
            lines.append(
                f"state[{target}] = aggregate_rows({source}, {node.group_by!r}, {specs!r})"
            )
        elif node.node_type == "pivot_longer":
            lines.extend([f"state[{target}] = []", f"for row in {source}:"])
            lines.append(f"    for column in {node.value_columns!r}:")
            lines.append(
                f"        state[{target}].append({{**{{name: row.get(name) for name in "
                f"{node.id_columns!r}}}, {node.name_column!r}: column, "
                f"{node.value_column!r}: row.get(column)}})"
            )
        elif node.node_type == "terminology_map":
            lines.extend(
                [f"state[{target}] = []", f"for row in {source}:", "    next_row = dict(row)"]
            )
            lines.append(f"    source_value = next_row.get({node.source_column!r})")
            lines.append(f"    mappings = {node.mappings!r}")
            if node.unmapped == "error":
                lines.append(
                    "    if str(source_value) not in mappings: "
                    "raise RuntimeError('terminology_mapping_unmapped')"
                )
                lines.append(f"    next_row[{node.target_column!r}] = mappings[str(source_value)]")
            elif node.unmapped == "preserve":
                lines.append(
                    f"    next_row[{node.target_column!r}] = "
                    "mappings.get(str(source_value), source_value)"
                )
            else:
                lines.append(
                    f"    next_row[{node.target_column!r}] = mappings.get(str(source_value))"
                )
            lines.append(f"    state[{target}].append(next_row)")
        elif node.node_type == "sequence":
            keys = (*node.group_by, *node.order_by)
            lines.extend(
                [
                    f"state[{target}] = [dict(row) for row in {source}]",
                    f"state[{target}].sort(key=lambda row: tuple("
                    f"(row.get(name) is None, row.get(name)) for name in {keys!r}))",
                    "counters = {}",
                    f"for row in state[{target}]:",
                    f"    group = tuple(row.get(name) for name in {node.group_by!r})",
                    f"    value = counters.get(group, {node.start})",
                    f"    row[{node.target_column!r}] = value",
                    "    counters[group] = value + 1",
                ]
            )
        elif node.node_type == "window":
            operations = {
                name: operation.model_dump(mode="python")
                for name, operation in node.operations.items()
            }
            lines.append(
                f"state[{target}] = window_rows({source}, {node.partition_by!r}, "
                f"{node.order_by!r}, {operations!r})"
            )
        elif node.node_type == "sort":
            lines.append(
                f"state[{target}] = sorted({source}, key=lambda row: tuple("
                f"(row.get(name) is None, row.get(name)) for name in {node.keys!r}))"
            )
        elif node.node_type == "assert":
            lines.extend(
                [
                    f"state[{target}] = list({source})",
                    f"if not all(bool({_py_expr(node.predicate)}) for row in "
                    f"state[{target}]): raise RuntimeError({node.issue_code!r})",
                ]
            )
        elif node.node_type == "write":
            lines.extend(
                [f"state[{target}] = list({source})", f"write({node.dataset!r}, state[{target}])"]
            )
        else:
            raise UnsupportedOperator(node.node_type)
    return "\n".join(lines) + "\n"


def _rq(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _r_expr(expression: Expression, frame: str = "frame") -> str:
    if expression.kind == "literal":
        if expression.value is None:
            return "NA"
        if isinstance(expression.value, bool):
            return "TRUE" if expression.value else "FALSE"
        return (
            _rq(expression.value) if isinstance(expression.value, str) else repr(expression.value)
        )
    if expression.kind == "column":
        return f"{frame}[[{_rq(expression.column)}]]"
    if expression.kind == "conditional":
        result = f"aur_norm({_r_expr(expression.otherwise, frame)})"
        for branch in reversed(expression.branches):
            when = _r_expr(branch.when, frame)
            then = f"aur_norm({_r_expr(branch.then, frame)})"
            result = f"ifelse(({when}) & !is.na({when}), {then}, {result})"
        return result
    if expression.kind == "unary":
        operand = _r_expr(expression.operand, frame)
        return {
            "not": f"!({operand})",
            "is_null": f"is.na({operand})",
            "is_not_null": f"!is.na({operand})",
            "negate": f"-as.numeric({operand})",
        }[expression.operator]
    left, right = _r_expr(expression.left, frame), _r_expr(expression.right, frame)
    symbols = {
        "eq": "==",
        "ne": "!=",
        "lt": "<",
        "le": "<=",
        "gt": ">",
        "ge": ">=",
        "and": "&",
        "or": "|",
        "add": "+",
        "sub": "-",
        "mul": "*",
        "div": "/",
    }
    if expression.operator in {"add", "sub", "mul", "div"}:
        left, right = f"as.numeric({left})", f"as.numeric({right})"
    return f"({left} {symbols[expression.operator]} {right})"


def r_source(value: DataflowIR, digest: str) -> str:
    lines = [
        f"# aurinara-dataflow compiler=1.5.0 ir={digest}",
        'root <- Sys.getenv("AURINARA_WORKSPACE", unset = "/workspace")',
        'inputs <- file.path(root, "inputs")',
        'outputs <- file.path(root, "outputs")',
        "dir.create(outputs, recursive=TRUE, showWarnings=FALSE)",
        "aur_norm <- function(x) { if (is.numeric(x)) x[!is.finite(x)] <- NA; x }",
        "state <- list()",
    ]
    incoming = incoming_nodes(value)
    for node in ordered_nodes(value):
        target = _rq(node.id)
        if node.node_type == "read":
            lines.append(
                f"state[[{target}]] <- read.csv(file.path(inputs, "
                f"{_rq(node.dataset + '.csv')}), check.names=FALSE, "
                'stringsAsFactors=FALSE, colClasses="character")'
            )
            continue
        if node.node_type == "union":
            refs = ", ".join(f"state[[{_rq(item)}]]" for item in incoming[node.id])
            lines.append(f"state[[{target}]] <- do.call(rbind, list({refs}))")
            continue
        if node.node_type == "join":
            left_keys = ", ".join(_rq(pair[0]) for pair in node.keys)
            right_keys = ", ".join(_rq(pair[1]) for pair in node.keys)
            all_left = "TRUE" if node.join_type in {"left", "full"} else "FALSE"
            all_right = "TRUE" if node.join_type in {"right", "full"} else "FALSE"
            lines.append(
                f"state[[{target}]] <- merge(state[[{_rq(node.left_input)}]], "
                f"state[[{_rq(node.right_input)}]], by.x=c({left_keys}), "
                f"by.y=c({right_keys}), all.x={all_left}, all.y={all_right}, "
                f"sort=FALSE, suffixes=c('', {_rq(node.right_suffix)}), incomparables=NA)"
            )
            continue
        source = f"state[[{_rq(_single(node, incoming[node.id]))}]]"
        if node.node_type == "select":
            lines.append(
                f"state[[{target}]] <- {source}[, c("
                f"{', '.join(_rq(x) for x in node.columns)}), drop=FALSE]"
            )
        elif node.node_type == "filter":
            lines.extend(
                [
                    f"frame <- {source}",
                    f"keep <- {_r_expr(node.predicate)}",
                    "keep[is.na(keep)] <- FALSE",
                    f"state[[{target}]] <- frame[keep, , drop=FALSE]",
                ]
            )
        elif node.node_type == "derive":
            lines.append(f"frame <- {source}")
            lines.extend(
                f"frame[[{_rq(name)}]] <- {_r_expr(expr)}"
                for name, expr in node.assignments.items()
            )
            lines.append(f"state[[{target}]] <- frame")
        elif node.node_type == "cast":
            lines.append(f"frame <- {source}")
            for name, operation in node.casts.items():
                source_values = f"frame[[{_rq(operation.source_column)}]]"
                lines.append(f"raw_values <- {source_values}")
                if operation.target_type == "text":
                    lines.append("converted <- as.character(raw_values)")
                    invalid = "rep(FALSE, length(raw_values))"
                elif operation.target_type == "float":
                    lines.append("converted <- suppressWarnings(as.numeric(raw_values))")
                    invalid = "!is.na(raw_values) & raw_values != '' & is.na(converted)"
                elif operation.target_type == "integer":
                    lines.extend(
                        [
                            "numeric_values <- suppressWarnings(as.numeric(raw_values))",
                            "converted <- as.integer(numeric_values)",
                        ]
                    )
                    invalid = (
                        "!is.na(raw_values) & raw_values != '' & "
                        "(is.na(numeric_values) | numeric_values != trunc(numeric_values))"
                    )
                else:
                    lines.extend(
                        [
                            "normalized <- tolower(trimws(as.character(raw_values)))",
                            "converted <- rep(NA, length(raw_values))",
                            "converted[normalized %in% c('true', '1')] <- TRUE",
                            "converted[normalized %in% c('false', '0')] <- FALSE",
                        ]
                    )
                    invalid = (
                        "!is.na(raw_values) & raw_values != '' & "
                        "!normalized %in% c('true', '1', 'false', '0')"
                    )
                if operation.invalid == "error":
                    lines.append(f"if (any({invalid})) stop('cast_invalid')")
                lines.append(f"frame[[{_rq(name)}]] <- converted")
            lines.append(f"state[[{target}]] <- frame")
        elif node.node_type == "aggregate":
            lines.append(f"frame <- {source}")
            if node.group_by:
                group_refs = ", ".join(_rq(name) for name in node.group_by)
                lines.extend(
                    [
                        f"groups <- unique(frame[, c({group_refs}), drop=FALSE])",
                        "result <- groups",
                    ]
                )
                mask = " & ".join(
                    f"frame[[{_rq(name)}]] == groups[[{_rq(name)}]][i]" for name in node.group_by
                )
                lines.append("for (i in seq_len(nrow(groups))) {")
                lines.append(f"  members <- frame[{mask}, , drop=FALSE]")
                indent = "  "
            else:
                lines.extend(["result <- data.frame(row.names=1)", "members <- frame"])
                indent = ""
            for name, spec in node.aggregations.items():
                if spec.operation == "count" and spec.column is None:
                    expression = "nrow(members)"
                else:
                    assert spec.column is not None
                    raw_values = f"members[[{_rq(spec.column)}]]"
                    if spec.operation == "count":
                        expression = f"sum(!is.na({raw_values}) & {raw_values} != '')"
                    elif spec.operation == "mean":
                        values = f"as.numeric({raw_values})"
                        expression = f"if (all(is.na({values}))) NA else mean({values}, na.rm=TRUE)"
                    else:
                        values = f"as.numeric({raw_values})"
                        expression = (
                            f"if (all(is.na({values}))) NA else "
                            f"{spec.operation}({values}, na.rm=TRUE)"
                        )
                if node.group_by:
                    lines.append(f"{indent}result[[{_rq(name)}]][i] <- {expression}")
                else:
                    lines.append(f"result[[{_rq(name)}]] <- {expression}")
            if node.group_by:
                lines.append("}")
            lines.append(f"state[[{target}]] <- result")
        elif node.node_type == "pivot_longer":
            id_refs = ", ".join(_rq(name) for name in node.id_columns)
            value_refs = ", ".join(_rq(name) for name in node.value_columns)
            lines.extend(
                [
                    f"frame <- {source}",
                    f"pieces <- lapply(c({value_refs}), function(column) {{",
                    (
                        f"  item <- frame[, c({id_refs}), drop=FALSE]"
                        if node.id_columns
                        else "  item <- data.frame(row.names=seq_len(nrow(frame)))"
                    ),
                    f"  item[[{_rq(node.name_column)}]] <- column",
                    f"  item[[{_rq(node.value_column)}]] <- frame[[column]]",
                    "  item",
                    "})",
                    f"state[[{target}]] <- do.call(rbind, pieces)",
                    f"row.names(state[[{target}]]) <- NULL",
                ]
            )
        elif node.node_type == "terminology_map":
            mapping_keys = ", ".join(_rq(key) for key in node.mappings)
            mapping_values = ", ".join(_rq(value) for value in node.mappings.values())
            lines.extend(
                [
                    f"frame <- {source}",
                    f"mapping <- setNames(c({mapping_values}), c({mapping_keys}))",
                    f"source_values <- frame[[{_rq(node.source_column)}]]",
                    "mapped <- unname(mapping[source_values])",
                ]
            )
            if node.unmapped == "error":
                lines.append("if (any(is.na(mapped))) stop('terminology_mapping_unmapped')")
            elif node.unmapped == "preserve":
                lines.append("mapped[is.na(mapped)] <- source_values[is.na(mapped)]")
            lines.extend(
                [
                    f"frame[[{_rq(node.target_column)}]] <- mapped",
                    f"state[[{target}]] <- frame",
                ]
            )
        elif node.node_type == "sequence":
            sequence_keys = (*node.group_by, *node.order_by)
            order_values = ", ".join(f"frame[[{_rq(name)}]]" for name in sequence_keys)
            lines.extend(
                [
                    f"frame <- {source}",
                    f"frame <- frame[do.call(order, list({order_values}, na.last=TRUE)), "
                    ", drop=FALSE]",
                ]
            )
            if node.group_by:
                group_refs = ", ".join(_rq(name) for name in node.group_by)
                lines.extend(
                    [
                        f"group_key <- interaction(frame[, c({group_refs}), drop=FALSE], "
                        "drop=TRUE, lex.order=TRUE)",
                        f"frame[[{_rq(node.target_column)}]] <- "
                        f"ave(seq_len(nrow(frame)), group_key, FUN=seq_along) + {node.start - 1}",
                    ]
                )
            else:
                lines.append(
                    f"frame[[{_rq(node.target_column)}]] <- seq_len(nrow(frame)) + {node.start - 1}"
                )
            lines.append(f"state[[{target}]] <- frame")
        elif node.node_type == "window":
            window_keys = (*node.partition_by, *node.order_by)
            order_values = ", ".join(f"frame[[{_rq(name)}]]" for name in window_keys)
            lines.extend(
                [
                    f"frame <- {source}",
                    f"frame <- frame[do.call(order, list({order_values}, na.last=TRUE)), "
                    ", drop=FALSE]",
                ]
            )
            if node.partition_by:
                partition_refs = ", ".join(_rq(name) for name in node.partition_by)
                lines.extend(
                    [
                        f"partition_key <- interaction(frame[, c({partition_refs}), drop=FALSE], "
                        "drop=TRUE, lex.order=TRUE)",
                        "group_indices <- split(seq_len(nrow(frame)), partition_key, drop=TRUE)",
                    ]
                )
            else:
                lines.append("group_indices <- list(seq_len(nrow(frame)))")
            for name, window_operation in node.operations.items():
                target_ref = _rq(name)
                if window_operation.operation == "row_number":
                    lines.extend(
                        [
                            "window_output <- rep(NA_integer_, nrow(frame))",
                            "for (indices in group_indices) {",
                            "  window_output[indices] <- seq_along(indices)",
                            "}",
                        ]
                    )
                elif window_operation.operation == "lag":
                    assert window_operation.source_column is not None
                    lines.extend(
                        [
                            f"window_source <- frame[[{_rq(window_operation.source_column)}]]",
                            "window_output <- rep(NA, nrow(frame))",
                            "for (indices in group_indices) {",
                            f"  if (length(indices) > {window_operation.offset}) {{",
                            "    targets <- indices[("
                            f"{window_operation.offset} + 1):length(indices)]",
                            "    sources <- indices[1:(length(indices) - "
                            f"{window_operation.offset})]",
                            "    window_output[targets] <- window_source[sources]",
                            "  }",
                            "}",
                        ]
                    )
                else:
                    assert window_operation.source_column is not None
                    lines.extend(
                        [
                            f"raw_window <- frame[[{_rq(window_operation.source_column)}]]",
                            "window_source <- suppressWarnings(as.numeric(raw_window))",
                            "invalid_window <- !is.na(raw_window) & raw_window != '' & "
                            "is.na(window_source)",
                            "if (any(invalid_window)) stop('window_numeric_invalid')",
                            "window_output <- rep(NA_real_, nrow(frame))",
                            "for (indices in group_indices) {",
                            "  running <- 0",
                            "  for (index in indices) {",
                            "    if (!is.na(window_source[index])) {",
                            "      running <- running + window_source[index]",
                            "      window_output[index] <- running",
                            "    }",
                            "  }",
                            "}",
                        ]
                    )
                lines.append(f"frame[[{target_ref}]] <- window_output")
            lines.append(f"state[[{target}]] <- frame")
        elif node.node_type == "sort":
            sort_columns = ", ".join(f"{source}[[{_rq(x)}]]" for x in node.keys)
            lines.append(
                f"state[[{target}]] <- {source}[do.call(order, list({sort_columns})), , drop=FALSE]"
            )
        elif node.node_type == "assert":
            lines.extend(
                [
                    f"frame <- {source}",
                    f"if (!all({_r_expr(node.predicate)}, na.rm=FALSE)) "
                    f"stop({_rq(node.issue_code)})",
                    f"state[[{target}]] <- frame",
                ]
            )
        elif node.node_type == "write":
            lines.extend(
                [
                    f"state[[{target}]] <- {source}",
                    f"write.csv(state[[{target}]], file.path(outputs, "
                    f'{_rq(node.dataset + ".csv")}), row.names=FALSE, na="")',
                ]
            )
        else:
            raise UnsupportedOperator(node.node_type)
    return "\n".join(lines) + "\n"


def _sas_expr(expression: Expression, result_type: str | None = None) -> str:
    if expression.kind == "literal":
        if expression.value is None:
            return "." if result_type != "character" else "''"
        if isinstance(expression.value, bool):
            return "1" if expression.value else "0"
        if isinstance(expression.value, str):
            return "'" + expression.value.replace("'", "''") + "'"
        return repr(expression.value)
    if expression.kind == "column":
        return expression.column
    if expression.kind == "conditional":
        if result_type not in {"character", "numeric"}:
            raise UnsupportedOperator("conditional_result_type_unknown")
        function = "IFC" if result_type == "character" else "IFN"
        result = _sas_expr(expression.otherwise, result_type)
        for branch in reversed(expression.branches):
            condition = _sas_expr(branch.when)
            then = _sas_expr(branch.then, result_type)
            result = f"{function}(({condition}), {then}, {result})"
        return result
    if expression.kind == "unary":
        operand = _sas_expr(expression.operand)
        return {
            "not": f"not ({operand})",
            "is_null": f"missing({operand})",
            "is_not_null": f"not missing({operand})",
            "negate": f"-({operand})",
        }[expression.operator]
    symbols = {
        "eq": "=",
        "ne": "ne",
        "lt": "<",
        "le": "<=",
        "gt": ">",
        "ge": ">=",
        "and": "and",
        "or": "or",
        "add": "+",
        "sub": "-",
        "mul": "*",
        "div": "/",
    }
    return (
        f"({_sas_expr(expression.left)} {symbols[expression.operator]} "
        f"{_sas_expr(expression.right)})"
    )


def sas_source(value: DataflowIR, digest: str) -> str:
    lines = [f"/* aurinara-dataflow compiler=1.5.0 ir={digest} */"]
    ordered = ordered_nodes(value)
    incoming = incoming_nodes(value)
    names = {node.id: f"n{index:04d}" for index, node in enumerate(ordered, start=1)}
    for node in ordered:
        target = names[node.id]
        if node.node_type == "read":
            lines.extend(
                [
                    f'proc import datafile="/workspace/inputs/{node.dataset}.csv"',
                    f"  out=work.{target} dbms=csv replace;",
                    "  getnames=yes;",
                    "run;",
                ]
            )
            continue
        if node.node_type in {"join", "aggregate"}:
            raise UnsupportedOperator(node.node_type)
        if node.node_type == "union":
            sources = " ".join(f"work.{names[item]}" for item in incoming[node.id])
            lines.extend([f"data work.{target};", f"  set {sources};", "run;"])
            continue
        source = names[_single(node, incoming[node.id])]
        if node.node_type == "select":
            lines.extend(
                [
                    f"data work.{target};",
                    f"  set work.{source};",
                    f"  keep {' '.join(node.columns)};",
                    "run;",
                ]
            )
        elif node.node_type == "filter":
            lines.extend(
                [
                    f"data work.{target};",
                    f"  set work.{source};",
                    f"  if {_sas_expr(node.predicate)};",
                    "run;",
                ]
            )
        elif node.node_type == "derive":
            lines.extend([f"data work.{target};", f"  set work.{source};"])
            lines.extend(
                f"  {name} = {_sas_expr(expression, node.result_types.get(name))};"
                for name, expression in node.assignments.items()
            )
            lines.append("run;")
        elif node.node_type == "sort":
            lines.extend(
                [
                    f"proc sort data=work.{source} out=work.{target};",
                    f"  by {' '.join(node.keys)};",
                    "run;",
                ]
            )
        elif node.node_type == "assert":
            lines.extend(
                [
                    "data _null_;",
                    f"  set work.{source};",
                    f"  if not ({_sas_expr(node.predicate)}) then do;",
                    f'    put "ERROR: {node.issue_code}";',
                    "    abort cancel;",
                    "  end;",
                    "run;",
                    f"data work.{target}; set work.{source}; run;",
                ]
            )
        elif node.node_type == "write":
            lines.extend(
                [
                    f"proc export data=work.{source} "
                    f'outfile="/workspace/outputs/{node.dataset}.csv"',
                    "  dbms=csv replace;",
                    "run;",
                ]
            )
        else:
            raise UnsupportedOperator(node.node_type)
    return "\n".join(lines) + "\n"


GENERATORS: dict[str, Callable[[DataflowIR, str], str]] = {
    "python": python_source,
    "r": r_source,
    "sas": sas_source,
}
