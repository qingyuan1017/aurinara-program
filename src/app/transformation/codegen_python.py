"""Deterministic Python emission from Dataflow IR."""

from app.transformation.codegen_common import (
    UnsupportedOperator,
    _custom_name,
    _single,
    incoming_nodes,
    ordered_nodes,
)
from app.transformation.contracts import (
    CustomFunctionDefinition,
    DataflowIR,
    DerivationExpression,
)


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
        return f"terminology_value({value}, {expression.mappings!r}, {expression.unmapped!r})"
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
        f"# aurinara-dataflow compiler=1.9.0 ir={digest}",
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
        "def normalize_rows(rows):",
        "    fields = list(dict.fromkeys(key for row in rows for key in row))",
        "    return [{field: row.get(field) for field in fields} for row in rows]",
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
        source = f"normalize_rows(state[{_single(node, incoming[node.id])!r}])"
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
                [
                    f"state[{target}] = []",
                    f"for row in {source}:",
                    "    next_row = dict(row)",
                    "    derived = {}",
                ]
            )
            for name, expression in node.ordered_assignments():
                lines.append(f"    derived[{name!r}] = {_py_expr(expression, 'row')}")
            lines.append("    next_row.update(derived)")
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
