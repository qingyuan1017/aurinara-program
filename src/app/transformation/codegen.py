"""Runnable deterministic source generation for supported Dataflow operators."""

from collections.abc import Callable

from app.transformation.contracts import (
    CustomFunctionDefinition,
    CustomFunctionLanguage,
    DataflowIR,
    DataflowNode,
    DerivationExpression,
    Expression,
)


class UnsupportedOperator(ValueError):
    """Raised when a backend cannot preserve one operator's semantics."""


def _custom_name(identifier: str) -> str:
    return f"aur_user_{identifier}"


def missing_custom_functions(
    functions: tuple[CustomFunctionDefinition, ...], language: CustomFunctionLanguage
) -> tuple[str, ...]:
    """List functions for which generated source contains a TODO placeholder."""

    return tuple(item.id for item in functions if item.implementation(language) is None)


def _python_custom_functions(functions: tuple[CustomFunctionDefinition, ...]) -> str:
    blocks: list[str] = []
    for definition in functions:
        source = definition.implementation("python")
        parameters = ", ".join(definition.parameters)
        if source is None:
            source = (
                f"# TODO: provide Python implementation for custom function {definition.id}\n"
                f"raise NotImplementedError('custom_function_todo:{definition.id}:python')"
            )
        body = "\n".join(f"    {line}" if line else "" for line in source.splitlines())
        blocks.append(f"def {_custom_name(definition.id)}({parameters}):\n{body}")
    return "\n\n".join(blocks)


def _r_custom_functions(functions: tuple[CustomFunctionDefinition, ...]) -> str:
    blocks: list[str] = []
    for definition in functions:
        source = definition.implementation("r")
        parameters = ", ".join(definition.parameters)
        if source is None:
            source = (
                f"# TODO: provide R implementation for custom function {definition.id}\n"
                f"stop('custom_function_todo:{definition.id}:r')"
            )
        blocks.append(f"{_custom_name(definition.id)} <- function({parameters}) {{\n{source}\n}}")
    return "\n\n".join(blocks)


def _sas_custom_functions(functions: tuple[CustomFunctionDefinition, ...]) -> str:
    if not functions:
        return ""
    lines = ["proc fcmp outlib=work.aurinara.user; "]
    for definition in functions:
        source = definition.implementation("sas")
        parameters = ", ".join(definition.parameters)
        lines.append(f"  function {_custom_name(definition.id)}({parameters});")
        if source is None:
            lines.extend(
                [
                    "    /* TODO: provide SAS implementation for custom function "
                    f"{definition.id} */",
                    f'    put "ERROR: custom_function_todo:{definition.id}:sas";',
                    "    return(.);",
                ]
            )
        else:
            lines.extend(f"    {line}" if line else "" for line in source.splitlines())
        lines.append("  endsub;")
    lines.extend(["run;", "options cmplib=work.aurinara;"])
    return "\n".join(lines)


_PY_FUNCTION_PREAMBLE = r"""
import math as _math
from datetime import date as _date, datetime as _dt, timedelta as _timedelta
_ASCII_UP = {c: c - 32 for c in range(ord("a"), ord("z") + 1)}
_ASCII_LO = {c: c + 32 for c in range(ord("A"), ord("Z") + 1)}
def _txt(v):
    if isinstance(v, bool): return "1" if v else "0"
    return v if isinstance(v, str) else str(v)
def _num(v):
    if isinstance(v, bool): return float(v)
    return float(str(v).strip())
def _int(v):
    if isinstance(v, bool): return int(v)
    if isinstance(v, float): return int(v)
    return int(str(v).strip())
def _parse_date(v):
    if v is None: return None
    t = _txt(v).strip()
    if len(t) != 10 or t[4] != "-" or t[7] != "-": return None
    try: return _date.fromisoformat(t)
    except ValueError: return None
def _parse_dt(v):
    if v is None: return None
    t = _txt(v).strip()
    if t[-1:] in ("Z", "z"): t = t[:-1]
    t = t.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try: return _dt.strptime(t, fmt)
        except ValueError: continue
    return None
def _req_date(v):
    if v is None: return None
    if isinstance(v, _dt): return v.date()
    if isinstance(v, _date): return v
    return _parse_date(v)
def _req_dt(v):
    if v is None: return None
    if isinstance(v, _dt): return v
    return _parse_dt(v)
def _half_away(value, digits):
    factor = 10.0 ** digits
    scaled = value * factor
    base = _math.floor(scaled)
    rem = scaled - base
    if rem > 0.5: r = base + 1
    elif rem < 0.5: r = base
    else: r = base + 1 if scaled >= 0 else base
    return r / factor
def _skey(v):
    if isinstance(v, bool): return (0, float(v))
    if isinstance(v, (int, float)): return (0, float(v))
    return (1, _txt(v))
def fn_concat(a): return "".join("" if v is None else _txt(v) for v in a)
def fn_substring(a):
    s, start, length = a
    if s is None: return None
    t = _txt(s); b = max(_int(start) - 1, 0); n = _int(length)
    return "" if n <= 0 else t[b:b + n]
def fn_upper(a):
    (s,) = a
    return None if s is None else _txt(s).translate(_ASCII_UP)
def fn_lower(a):
    (s,) = a
    return None if s is None else _txt(s).translate(_ASCII_LO)
def fn_trim(a):
    (s,) = a
    return None if s is None else _txt(s).strip()
def fn_length(a):
    (s,) = a
    return None if s is None else len(_txt(s))
def fn_contains(a):
    s, n = a
    return None if s is None or n is None else (_txt(n) in _txt(s))
def fn_startswith(a):
    s, p = a
    return None if s is None or p is None else _txt(s).startswith(_txt(p))
def fn_endswith(a):
    s, p = a
    return None if s is None or p is None else _txt(s).endswith(_txt(p))
def fn_replace(a):
    s, f, w = a
    if s is None: return None
    ft = _txt(f)
    if ft == "": raise ValueError("replace_empty_find")
    return _txt(s).replace(ft, _txt(w))
def fn_index_of(a):
    s, n = a
    return None if s is None or n is None else _txt(s).find(_txt(n)) + 1
def fn_scan_token(a):
    s, idx, delim = a
    if s is None: return None
    d = _txt(delim)
    if d == "": raise ValueError("scan_token_empty_delimiter")
    toks = [tok for tok in _txt(s).split(d) if tok != ""]
    p = _int(idx)
    return None if p < 1 or p > len(toks) else toks[p - 1]
def fn_pad_left(a):
    s, w, f = a
    if s is None: return None
    fc = _txt(f)
    if len(fc) != 1: raise ValueError("pad_fill_not_single")
    return _txt(s).rjust(_int(w), fc)
def fn_pad_right(a):
    s, w, f = a
    if s is None: return None
    fc = _txt(f)
    if len(fc) != 1: raise ValueError("pad_fill_not_single")
    return _txt(s).ljust(_int(w), fc)
def fn_coalesce(a):
    for v in a:
        if v is not None: return v
    return None
def fn_nullif(a):
    x, y = a
    if x is None: return None
    return None if x == y else x
def fn_is_in(value, candidates):
    if value is None: return False
    return value in candidates
def fn_n_missing(a): return sum(1 for v in a if v is None)
def fn_n_present(a): return sum(1 for v in a if v is not None)
def fn_round(a):
    v, d = a
    return None if v is None or d is None else _half_away(_num(v), _int(d))
def fn_floor(a):
    (v,) = a
    return None if v is None else _math.floor(_num(v))
def fn_ceil(a):
    (v,) = a
    return None if v is None else _math.ceil(_num(v))
def fn_abs(a):
    (v,) = a
    if v is None: return None
    if isinstance(v, bool): return abs(int(v))
    if isinstance(v, int): return abs(v)
    return abs(_num(v))
def fn_modulo(a):
    x, y = a
    if x is None or y is None: return None
    xi = _int(x); yi = _int(y)
    if yi == 0: return None
    return int(xi - yi * _math.trunc(xi / yi))
def fn_min_of(a):
    p = [v for v in a if v is not None]
    return None if not p else min(p, key=_skey)
def fn_max_of(a):
    p = [v for v in a if v is not None]
    return None if not p else max(p, key=_skey)
def fn_truncate(a):
    (v,) = a
    return None if v is None else _math.trunc(_num(v))
def fn_safe_divide(a):
    x, y = a
    if x is None or y is None: return None
    d = _num(y)
    return None if d == 0 else _num(x) / d
def fn_parse_date(a):
    (v,) = a
    return _parse_date(v)
def fn_year(a):
    (v,) = a
    d = _req_date(v)
    return None if d is None else d.year
def fn_month(a):
    (v,) = a
    d = _req_date(v)
    return None if d is None else d.month
def fn_day(a):
    (v,) = a
    d = _req_date(v)
    return None if d is None else d.day
def fn_date_diff_days(a):
    e, s = a
    ed = _req_date(e); sd = _req_date(s)
    return None if ed is None or sd is None else (ed - sd).days
def fn_parse_datetime(a):
    (v,) = a
    return _parse_dt(v)
def fn_hour(a):
    (v,) = a
    d = _req_dt(v)
    return None if d is None else d.hour
def fn_minute(a):
    (v,) = a
    d = _req_dt(v)
    return None if d is None else d.minute
def fn_second(a):
    (v,) = a
    d = _req_dt(v)
    return None if d is None else d.second
def fn_study_day(a):
    e, r = a
    ed = _req_date(e); rd = _req_date(r)
    if ed is None or rd is None: return None
    delta = (ed - rd).days
    return delta + 1 if delta >= 0 else delta
def fn_date_add_days(a):
    b, n = a
    bd = _req_date(b)
    if bd is None or n is None: return None
    return bd + _timedelta(days=_int(n))
def fn_date_diff_months(a):
    e, s = a
    ed = _req_date(e); sd = _req_date(s)
    if ed is None or sd is None: return None
    m = (ed.year - sd.year) * 12 + (ed.month - sd.month)
    if m >= 0:
        if ed.day < sd.day: m -= 1
    else:
        if ed.day > sd.day: m += 1
    return m
""".strip("\n")


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


def _py_expr(expression: DerivationExpression, row: str = "row") -> str:
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
    if expression.kind == "list_literal":
        return "(" + ", ".join(repr(value) for value in expression.values) + ",)"
    if expression.kind == "function":
        if expression.function == "is_in":
            value = _py_expr(expression.arguments[0], row)
            candidates = _py_expr(expression.arguments[1], row)
            return f"fn_is_in({value}, {candidates})"
        arguments = ", ".join(_py_expr(argument, row) for argument in expression.arguments)
        return f"fn_{expression.function}([{arguments}])"
    if expression.kind == "custom_function":
        arguments = ", ".join(_py_expr(argument, row) for argument in expression.arguments)
        return f"{_custom_name(expression.function_id)}({arguments})"
    if expression.kind == "cast":
        value = _py_expr(expression.value, row)
        return f"cast_value({value}, {expression.target_type!r}, {expression.invalid!r})"
    if expression.kind == "terminology_map":
        value = _py_expr(expression.value, row)
        return (
            f"terminology_value({value}, {expression.mappings!r}, "
            f"{expression.unmapped!r})"
        )
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
        f"# aurinara-dataflow compiler=1.7.0 ir={digest}",
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
        _PY_FUNCTION_PREAMBLE,
        _python_custom_functions(value.custom_functions),
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
        "def terminology_value(value, mappings, unmapped):",
        "    mapped = mappings.get(str(value)) if value is not None else None",
        "    if mapped is None and unmapped == 'error':",
        "        raise RuntimeError('terminology_mapping_unmapped')",
        "    return value if mapped is None and unmapped == 'preserve' else mapped",
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
            for name, expression in node.ordered_assignments():
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


def _r_mapping(value: dict[str, str]) -> str:
    return "c(" + ", ".join(f"{_rq(key)}={_rq(mapped)}" for key, mapped in value.items()) + ")"


def _r_literal_scalar(value: str | int | float | bool | None) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return _rq(value)
    return repr(value)


def _r_expr(expression: DerivationExpression, frame: str = "frame") -> str:
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
    if expression.kind == "list_literal":
        items = ", ".join(_r_literal_scalar(value) for value in expression.values)
        return f"list({items})"
    if expression.kind == "function":
        if expression.function == "is_in":
            value = _r_expr(expression.arguments[0], frame)
            candidates = _r_expr(expression.arguments[1], frame)
            return f"aur_is_in({value}, {candidates})"
        arguments = ", ".join(_r_expr(argument, frame) for argument in expression.arguments)
        return f"aur_{expression.function}({arguments})"
    if expression.kind == "custom_function":
        arguments = ", ".join(_r_expr(argument, frame) for argument in expression.arguments)
        return f"{_custom_name(expression.function_id)}({arguments})"
    if expression.kind == "cast":
        return (
            f"aur_cast({_r_expr(expression.value, frame)}, "
            f"{_rq(expression.target_type)}, {_rq(expression.invalid)})"
        )
    if expression.kind == "terminology_map":
        return (
            f"aur_terminology_map({_r_expr(expression.value, frame)}, "
            f"{_r_mapping(expression.mappings)}, {_rq(expression.unmapped)})"
        )
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


_R_FUNCTION_PREAMBLE = r"""
aur_norm <- function(x) { if (is.numeric(x)) x[!is.finite(x)] <- NA; x }
.aur_na <- function(x) is.na(x) | (is.character(x) & is.na(suppressWarnings(x)))
.aur_txt <- function(x) {
  if (is.logical(x)) ifelse(is.na(x), NA_character_, ifelse(x, "1", "0")) else as.character(x)
}
.aur_num <- function(x) suppressWarnings(as.numeric(x))
.aur_int <- function(x) suppressWarnings(as.integer(round(as.numeric(x))))
aur_cast <- function(x, target, invalid) {
  missing <- is.na(x) | x == ""
  if (target == "text") converted <- as.character(x)
  else if (target == "float") converted <- suppressWarnings(as.numeric(x))
  else if (target == "integer") {
    numeric_values <- suppressWarnings(as.numeric(x))
    converted <- as.integer(numeric_values)
    converted[!is.na(numeric_values) & numeric_values != trunc(numeric_values)] <- NA_integer_
  } else {
    normalized <- tolower(trimws(as.character(x)))
    converted <- rep(NA, length(x))
    converted[normalized %in% c("true", "1")] <- TRUE
    converted[normalized %in% c("false", "0")] <- FALSE
  }
  failed <- !missing & is.na(converted)
  if (invalid == "error" && any(failed)) stop("cast_invalid")
  converted[missing] <- NA
  converted
}
aur_terminology_map <- function(x, mappings, unmapped) {
  keys <- as.character(x)
  matched <- !is.na(keys) & keys %in% names(mappings)
  if (unmapped == "error" && any(!matched)) stop("terminology_mapping_unmapped")
  result <- unname(mappings[keys])
  if (unmapped == "preserve") result[!matched] <- x[!matched]
  result
}
.aur_vec <- function(fun, n, ...) {
  args <- list(...)
  out <- vector("list", n)
  for (i in seq_len(n)) {
    out[[i]] <- do.call(fun, lapply(args, function(a) a[[((i - 1) %% length(a)) + 1]]))
  }
  out
}
.aur_recycle <- function(..., n) {
  lapply(list(...), function(a) { if (length(a) == 1) rep(a, n) else a })
}
.aur_n <- function(...) max(vapply(list(...), length, integer(1)), 1L)
.aur_date <- function(x) {
  t <- .aur_txt(x)
  ok <- !is.na(t) & nchar(t) == 10 & substr(t, 5, 5) == "-" & substr(t, 8, 8) == "-"
  d <- rep(as.Date(NA), length(t))
  d[ok] <- as.Date(t[ok], format = "%Y-%m-%d")
  d
}
.aur_dt <- function(x) {
  t <- .aur_txt(x)
  t <- sub("[Zz]$", "", t)
  t <- gsub("T", " ", t)
  d <- as.POSIXct(t, format = "%Y-%m-%d %H:%M:%S", tz = "UTC")
  short <- is.na(d) & !is.na(t)
  if (any(short)) {
    d[short] <- as.POSIXct(t[short], format = "%Y-%m-%d %H:%M", tz = "UTC")
  }
  d
}
aur_concat <- function(...) {
  n <- .aur_n(...)
  parts <- lapply(list(...), function(a) {
    v <- .aur_txt(a); v[is.na(v)] <- ""; rep(v, length.out = n)
  })
  Reduce(function(x, y) paste0(x, y), parts)
}
aur_substring <- function(s, start, length) {
  n <- .aur_n(s, start, length)
  st <- .aur_txt(s); si <- .aur_int(start); ln <- .aur_int(length)
  r <- character(n)
  for (i in seq_len(n)) {
    ss <- st[[((i - 1) %% length(st)) + 1]]
    b <- max(si[[((i - 1) %% length(si)) + 1]], 1)
    l <- ln[[((i - 1) %% length(ln)) + 1]]
    if (is.na(ss)) { r[i] <- NA_character_ }
    else if (l <= 0) { r[i] <- "" }
    else { r[i] <- substr(ss, b, b + l - 1) }
  }
  r
}
aur_upper <- function(s) { v <- .aur_txt(s); ifelse(is.na(v), NA_character_, toupper(v)) }
aur_lower <- function(s) { v <- .aur_txt(s); ifelse(is.na(v), NA_character_, tolower(v)) }
aur_trim <- function(s) { v <- .aur_txt(s); ifelse(is.na(v), NA_character_, trimws(v)) }
aur_length <- function(s) { v <- .aur_txt(s); ifelse(is.na(v), NA_integer_, nchar(v)) }
aur_contains <- function(s, sub) {
  a <- .aur_txt(s); b <- .aur_txt(sub)
  ifelse(is.na(a) | is.na(b), NA, mapply(function(x, y) grepl(y, x, fixed = TRUE), a, b))
}
aur_startswith <- function(s, p) {
  a <- .aur_txt(s); b <- .aur_txt(p)
  ifelse(is.na(a) | is.na(b), NA, startsWith(a, b))
}
aur_endswith <- function(s, p) {
  a <- .aur_txt(s); b <- .aur_txt(p)
  ifelse(is.na(a) | is.na(b), NA, endsWith(a, b))
}
aur_replace <- function(s, find, repl) {
  a <- .aur_txt(s); f <- .aur_txt(find); w <- .aur_txt(repl)
  if (any(!is.na(f) & f == "")) stop("replace_empty_find")
  ifelse(is.na(a), NA_character_, mapply(function(x, y, z) gsub(y, z, x, fixed = TRUE), a, f, w))
}
aur_index_of <- function(s, sub) {
  a <- .aur_txt(s); b <- .aur_txt(sub)
  ifelse(is.na(a) | is.na(b), NA_integer_, {
    find1 <- function(x, y) { r <- regexpr(y, x, fixed = TRUE)[1]; if (r < 0) 0L else r }
    as.integer(mapply(find1, a, b))
  })
}
aur_scan_token <- function(s, idx, delim) {
  a <- .aur_txt(s); p <- .aur_int(idx); d <- .aur_txt(delim)
  if (any(!is.na(d) & d == "")) stop("scan_token_empty_delimiter")
  n <- .aur_n(a, p, d)
  r <- character(n)
  for (i in seq_len(n)) {
    av <- a[[((i - 1) %% length(a)) + 1]]
    dv <- d[[((i - 1) %% length(d)) + 1]]
    pv <- p[[((i - 1) %% length(p)) + 1]]
    if (is.na(av)) { r[i] <- NA_character_; next }
    toks <- strsplit(av, dv, fixed = TRUE)[[1]]
    toks <- toks[toks != ""]
    r[i] <- if (pv < 1 || pv > length(toks)) NA_character_ else toks[pv]
  }
  r
}
aur_pad_left <- function(s, w, f) {
  a <- .aur_txt(s); wi <- .aur_int(w); fc <- .aur_txt(f)
  if (any(!is.na(fc) & nchar(fc) != 1)) stop("pad_fill_not_single")
  n <- .aur_n(a, wi, fc)
  r <- character(n)
  for (i in seq_len(n)) {
    av <- a[[((i - 1) %% length(a)) + 1]]
    if (is.na(av)) { r[i] <- NA_character_; next }
    width <- wi[[((i - 1) %% length(wi)) + 1]]
    fill <- fc[[((i - 1) %% length(fc)) + 1]]
    if (nchar(av) >= width) { r[i] <- av } else {
      r[i] <- paste0(paste(rep(fill, width - nchar(av)), collapse = ""), av)
    }
  }
  r
}
aur_pad_right <- function(s, w, f) {
  a <- .aur_txt(s); wi <- .aur_int(w); fc <- .aur_txt(f)
  if (any(!is.na(fc) & nchar(fc) != 1)) stop("pad_fill_not_single")
  n <- .aur_n(a, wi, fc)
  r <- character(n)
  for (i in seq_len(n)) {
    av <- a[[((i - 1) %% length(a)) + 1]]
    if (is.na(av)) { r[i] <- NA_character_; next }
    width <- wi[[((i - 1) %% length(wi)) + 1]]
    fill <- fc[[((i - 1) %% length(fc)) + 1]]
    if (nchar(av) >= width) { r[i] <- av } else {
      r[i] <- paste0(av, paste(rep(fill, width - nchar(av)), collapse = ""))
    }
  }
  r
}
aur_coalesce <- function(...) {
  args <- list(...); n <- .aur_n(...)
  r <- rep(NA, n); r <- as.vector(r, mode = "list")
  for (i in seq_len(n)) {
    val <- NA
    for (a in args) { v <- a[[((i - 1) %% length(a)) + 1]]; if (!is.na(v)) { val <- v; break } }
    r[[i]] <- val
  }
  unlist(lapply(r, function(x) if (is.null(x)) NA else x))
}
aur_nullif <- function(a, b) {
  n <- .aur_n(a, b); r <- a[rep(seq_along(a), length.out = n)]
  bb <- b[rep(seq_along(b), length.out = n)]
  r[!is.na(r) & !is.na(bb) & r == bb] <- NA
  r
}
aur_is_in <- function(value, candidates) {
  cand <- unlist(candidates)
  ifelse(is.na(value), FALSE, value %in% cand)
}
aur_n_missing <- function(...) {
  args <- list(...); n <- .aur_n(...)
  r <- integer(n)
  for (i in seq_len(n)) {
    r[i] <- sum(vapply(args, function(a) is.na(a[[((i - 1) %% length(a)) + 1]]), logical(1)))
  }
  r
}
aur_n_present <- function(...) {
  args <- list(...); n <- .aur_n(...)
  r <- integer(n)
  for (i in seq_len(n)) {
    r[i] <- sum(vapply(args, function(a) !is.na(a[[((i - 1) %% length(a)) + 1]]), logical(1)))
  }
  r
}
aur_round <- function(x, digits) {
  xv <- .aur_num(x); dv <- .aur_int(digits)
  factor <- 10 ^ dv
  scaled <- xv * factor
  base <- floor(scaled)
  rem <- scaled - base
  up <- ifelse(rem > 0.5, base + 1, ifelse(rem < 0.5, base, ifelse(scaled >= 0, base + 1, base)))
  ifelse(is.na(xv) | is.na(dv), NA_real_, up / factor)
}
aur_floor <- function(x) { v <- .aur_num(x); ifelse(is.na(v), NA_integer_, as.integer(floor(v))) }
aur_ceil <- function(x) { v <- .aur_num(x); ifelse(is.na(v), NA_integer_, as.integer(ceiling(v))) }
aur_abs <- function(x) { v <- .aur_num(x); ifelse(is.na(v), NA_real_, abs(v)) }
aur_modulo <- function(a, b) {
  av <- .aur_int(a); bv <- .aur_int(b)
  ifelse(is.na(av) | is.na(bv) | bv == 0, NA_integer_, as.integer(av - bv * trunc(av / bv)))
}
aur_min_of <- function(...) {
  args <- lapply(list(...), .aur_num); n <- max(vapply(args, length, integer(1)), 1L)
  m <- do.call(pmin, c(lapply(args, function(a) rep(a, length.out = n)), na.rm = TRUE))
  m[is.infinite(m)] <- NA
  m
}
aur_max_of <- function(...) {
  args <- lapply(list(...), .aur_num); n <- max(vapply(args, length, integer(1)), 1L)
  m <- do.call(pmax, c(lapply(args, function(a) rep(a, length.out = n)), na.rm = TRUE))
  m[is.infinite(m)] <- NA
  m
}
aur_truncate <- function(x) {
  v <- .aur_num(x); ifelse(is.na(v), NA_integer_, as.integer(trunc(v)))
}
aur_safe_divide <- function(a, b) {
  av <- .aur_num(a); bv <- .aur_num(b)
  ifelse(is.na(av) | is.na(bv) | bv == 0, NA_real_, av / bv)
}
aur_parse_date <- function(x) format(.aur_date(x), "%Y-%m-%d")
aur_year <- function(x) {
  d <- .aur_date(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%Y")))
}
aur_month <- function(x) {
  d <- .aur_date(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%m")))
}
aur_day <- function(x) {
  d <- .aur_date(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%d")))
}
aur_date_diff_days <- function(e, s) {
  ed <- .aur_date(e); sd <- .aur_date(s)
  ifelse(is.na(ed) | is.na(sd), NA_integer_, as.integer(ed - sd))
}
aur_parse_datetime <- function(x) {
  d <- .aur_dt(x); ifelse(is.na(d), NA_character_, format(d, "%Y-%m-%d %H:%M:%S", tz = "UTC"))
}
aur_hour <- function(x) {
  d <- .aur_dt(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%H", tz = "UTC")))
}
aur_minute <- function(x) {
  d <- .aur_dt(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%M", tz = "UTC")))
}
aur_second <- function(x) {
  d <- .aur_dt(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%S", tz = "UTC")))
}
aur_study_day <- function(e, r) {
  ed <- .aur_date(e); rd <- .aur_date(r)
  delta <- as.integer(ed - rd)
  ifelse(is.na(ed) | is.na(rd), NA_integer_, ifelse(delta >= 0, delta + 1L, delta))
}
aur_date_add_days <- function(b, n) {
  bd <- .aur_date(b); nn <- .aur_int(n)
  ifelse(is.na(bd) | is.na(nn), NA_character_, format(bd + nn, "%Y-%m-%d"))
}
aur_date_diff_months <- function(e, s) {
  ed <- .aur_date(e); sd <- .aur_date(s)
  n <- .aur_n(ed, sd); r <- integer(n)
  for (i in seq_len(n)) {
    a <- ed[[((i - 1) %% length(ed)) + 1]]; b <- sd[[((i - 1) %% length(sd)) + 1]]
    if (is.na(a) || is.na(b)) { r[i] <- NA_integer_; next }
    m <- (as.integer(format(a, "%Y")) - as.integer(format(b, "%Y"))) * 12 +
         (as.integer(format(a, "%m")) - as.integer(format(b, "%m")))
    da <- as.integer(format(a, "%d")); db <- as.integer(format(b, "%d"))
    if (m >= 0) { if (da < db) m <- m - 1 } else { if (da > db) m <- m + 1 }
    r[i] <- as.integer(m)
  }
  r
}
""".strip("\n")


def r_source(value: DataflowIR, digest: str) -> str:
    lines = [
        f"# aurinara-dataflow compiler=1.7.0 ir={digest}",
        'root <- Sys.getenv("AURINARA_WORKSPACE", unset = "/workspace")',
        'inputs <- file.path(root, "inputs")',
        'outputs <- file.path(root, "outputs")',
        "dir.create(outputs, recursive=TRUE, showWarnings=FALSE)",
        _R_FUNCTION_PREAMBLE,
        _r_custom_functions(value.custom_functions),
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
                for name, expr in node.ordered_assignments()
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


def _sas_list_scalar(value: str | int | float | bool | None) -> str:
    if value is None:
        raise UnsupportedOperator("is_in_null_list_member")
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return repr(value)


def _sas_date(expression: Expression) -> str:
    """Lower a sub-expression that must yield a SAS date (1960 origin, internal).

    Only ``parse_date`` output and ``date_add_days`` compose into date functions
    (design §4.3/§7). Any other producer cannot be guaranteed to be a SAS date,
    so the backend declines rather than guess.
    """

    if expression.kind == "function" and expression.function == "parse_date":
        inner = _sas_expr(expression.arguments[0])
        return f"input({inner}, anydtdte32.)"
    if expression.kind == "function" and expression.function == "date_add_days":
        base = _sas_date(expression.arguments[0])
        offset = _sas_expr(expression.arguments[1])
        return f"({base} + {offset})"
    if expression.kind == "literal" and expression.value is None:
        return "."
    raise UnsupportedOperator("date_function_requires_parse_date")


def _sas_datetime(expression: Expression) -> str:
    if expression.kind == "function" and expression.function == "parse_datetime":
        inner = _sas_expr(expression.arguments[0])
        return f"input({inner}, e8601dt.)"
    if expression.kind == "literal" and expression.value is None:
        return "."
    raise UnsupportedOperator("datetime_function_requires_parse_datetime")


def _sas_function(expression: Expression, result_type: str | None) -> str:
    assert expression.kind == "function"
    name = expression.function
    args = expression.arguments

    def expr(index: int) -> str:
        return _sas_expr(args[index])

    if name == "concat":
        return "cats(" + ", ".join(expr(i) for i in range(len(args))) + ")"
    if name == "substring":
        return f"substrn({expr(0)}, {expr(1)}, {expr(2)})"
    if name == "upper":
        return f"upcase({expr(0)})"
    if name == "lower":
        return f"lowcase({expr(0)})"
    if name == "trim":
        return f"strip({expr(0)})"
    if name == "length":
        return f"ifn(missing({expr(0)}), ., lengthn({expr(0)}))"
    if name == "contains":
        return f"(index({expr(0)}, {expr(1)}) > 0)"
    if name == "startswith":
        return f"(index({expr(0)}, {expr(1)}) = 1)"
    if name == "endswith":
        return f"(substrn({expr(0)}, lengthn({expr(0)}) - lengthn({expr(1)}) + 1) = {expr(1)})"
    if name == "replace":
        return f"tranwrd({expr(0)}, {expr(1)}, {expr(2)})"
    if name == "index_of":
        return f"index({expr(0)}, {expr(1)})"
    if name == "scan_token":
        return f"scan({expr(0)}, {expr(1)}, {expr(2)}, 'm')"
    if name == "pad_left":
        return f"right(repeat({expr(2)}, {expr(1)} - 1)) || {expr(0)}"
    if name == "pad_right":
        return f"{expr(0)} || repeat({expr(2)}, {expr(1)} - lengthn({expr(0)}) - 1)"
    if name == "coalesce":
        joined = ", ".join(expr(i) for i in range(len(args)))
        function = "coalescec" if result_type == "character" else "coalesce"
        return f"{function}({joined})"
    if name == "nullif":
        function = "ifc" if result_type == "character" else "ifn"
        empty = "''" if result_type == "character" else "."
        return f"{function}({expr(0)} = {expr(1)}, {empty}, {expr(0)})"
    if name == "is_in":
        return f"({expr(0)} in {_sas_expr(args[1])})"
    if name == "n_missing":
        joined = ", ".join(expr(i) for i in range(len(args)))
        function = "cmiss" if result_type == "character" else "nmiss"
        return f"{function}({joined})"
    if name == "n_present":
        joined = ", ".join(expr(i) for i in range(len(args)))
        if result_type == "character":
            return f"({len(args)} - cmiss({joined}))"
        return f"n({joined})"
    if name == "round":
        return f"(sign({expr(0)}) * round(abs({expr(0)}), 10 ** (-({expr(1)}))))"
    if name == "floor":
        return f"floor({expr(0)})"
    if name == "ceil":
        return f"ceil({expr(0)})"
    if name == "abs":
        return f"abs({expr(0)})"
    if name == "modulo":
        return f"ifn({expr(1)} = 0, ., {expr(0)} - {expr(1)} * int({expr(0)} / {expr(1)}))"
    if name == "min_of":
        return "min(" + ", ".join(expr(i) for i in range(len(args))) + ")"
    if name == "max_of":
        return "max(" + ", ".join(expr(i) for i in range(len(args))) + ")"
    if name == "truncate":
        return f"int({expr(0)})"
    if name == "safe_divide":
        return f"ifn(missing({expr(1)}) or {expr(1)} = 0, ., {expr(0)} / {expr(1)})"
    if name == "parse_date":
        return f"put({_sas_date(expression)}, yymmdd10.)"
    if name == "year":
        return f"year({_sas_date(args[0])})"
    if name == "month":
        return f"month({_sas_date(args[0])})"
    if name == "day":
        return f"day({_sas_date(args[0])})"
    if name == "date_diff_days":
        return f"({_sas_date(args[0])} - {_sas_date(args[1])})"
    if name == "date_add_days":
        return f"put({_sas_date(expression)}, yymmdd10.)"
    if name == "study_day":
        event = _sas_date(args[0])
        reference = _sas_date(args[1])
        return f"ifn({event} >= {reference}, {event} - {reference} + 1, {event} - {reference})"
    if name == "date_diff_months":
        return f"intck('month', {_sas_date(args[1])}, {_sas_date(args[0])}, 'C')"
    if name == "parse_datetime":
        return f"put({_sas_datetime(expression)}, e8601dt19.)"
    if name == "hour":
        return f"hour(timepart({_sas_datetime(args[0])}))"
    if name == "minute":
        return f"minute(timepart({_sas_datetime(args[0])}))"
    if name == "second":
        return f"second(timepart({_sas_datetime(args[0])}))"
    raise UnsupportedOperator(f"function_{name}")


def _sas_expr(expression: DerivationExpression, result_type: str | None = None) -> str:
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
    if expression.kind == "list_literal":
        return "(" + ", ".join(_sas_list_scalar(value) for value in expression.values) + ")"
    if expression.kind == "function":
        return _sas_function(expression, result_type)
    if expression.kind == "custom_function":
        arguments = ", ".join(_sas_expr(item) for item in expression.arguments)
        return f"{_custom_name(expression.function_id)}({arguments})"
    if expression.kind == "cast":
        if expression.invalid == "error":
            raise UnsupportedOperator("cast_error_policy")
        value = _sas_expr(expression.value)
        if expression.target_type == "text":
            return f"cats({value})"
        if expression.target_type in {"integer", "float"}:
            return f"input(cats({value}), ?? best32.)"
        normalized = f"lowcase(strip(cats({value})))"
        return f"ifn({normalized} in ('true', '1'), 1, ifn({normalized} in ('false', '0'), 0, .))"
    if expression.kind == "terminology_map":
        if expression.unmapped == "error":
            raise UnsupportedOperator("terminology_mapping_error_policy")
        if result_type not in {"character", "numeric"}:
            raise UnsupportedOperator("terminology_mapping_result_type_unknown")
        source = _sas_expr(expression.value)
        character = result_type == "character"
        conditional = "IFC" if character else "IFN"
        result = source if expression.unmapped == "preserve" else ("''" if character else ".")
        for original, mapped in reversed(expression.mappings.items()):
            if character:
                mapped_value = "'" + mapped.replace("'", "''") + "'"
            else:
                try:
                    mapped_value = repr(float(mapped))
                except ValueError as error:
                    raise UnsupportedOperator("terminology_mapping_numeric_value") from error
            original_value = "'" + original.replace("'", "''") + "'"
            result = f"{conditional}((cats({source}) = {original_value}), {mapped_value}, {result})"
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
    lines = [
        f"/* aurinara-dataflow compiler=1.7.0 ir={digest} */",
        _sas_custom_functions(value.custom_functions),
    ]
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
                for name, expression in node.ordered_assignments()
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
