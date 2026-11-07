"""Deterministic SAS emission from Dataflow IR."""

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
    Expression,
)


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
        f"/* aurinara-dataflow compiler=1.9.0 ir={digest} */",
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
            assignments = node.ordered_assignments()
            temporary_names = {
                name: f"_aur_d{index}" for index, (name, _) in enumerate(assignments, start=1)
            }
            lines.append(f"data work.{target};")
            for name, temporary in temporary_names.items():
                if node.result_types.get(name) == "character":
                    lines.append(f"  length {temporary} $32767;")
            lines.append(f"  set work.{source};")
            lines.extend(
                f"  {temporary_names[name]} = {_sas_expr(expression, node.result_types.get(name))};"
                for name, expression in assignments
            )
            lines.extend(f"  {name} = {temporary_names[name]};" for name, _ in assignments)
            lines.append("  drop _aur_d:;")
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
