"""Declarative expression validation emitting the common issue model.

This validator walks the shared typed ``Expression`` tree and reports
authoring problems as :class:`app.validation.contracts.ValidationIssue`
records with stable machine-readable codes and ``field_path`` anchors.
Clinical modules (SDTM/ADaM/TLF) call :func:`validate_expression` or
:func:`validate_expressions` through this typed interface so expression
rules stay in the transformation package rather than in ``common``.
"""

from collections.abc import Iterable, Iterator
from uuid import UUID, uuid5

from app.transformation.contracts import (
    _FUNCTION_ARITY,
    _FUNCTION_MIN_ARITY,
    ConditionalExpression,
    Expression,
    FunctionCallExpression,
)
from app.validation.contracts import IssueSeverity, ValidationIssue

_ISSUE_NAMESPACE = UUID("f6b3c3d8-9c2a-4e4b-9a0c-2d6a1b7e5c40")

EXPR_CONDITIONAL_EMPTY = "expr_conditional_empty"
EXPR_CONDITIONAL_RESULT_TYPE_MIXED = "expr_conditional_result_type_mixed"
EXPR_CONDITIONAL_BRANCH_UNREACHABLE = "expr_conditional_branch_unreachable"
EXPR_FUNCTION_UNKNOWN = "expr_function_unknown"
EXPR_FUNCTION_ARITY = "expr_function_arity"
EXPR_FUNCTION_ARG_TYPE = "expr_function_arg_type"
EXPR_LIST_LITERAL_MISPLACED = "expr_list_literal_misplaced"
EXPR_DATE_FUNCTION_ON_NONDATE = "expr_date_function_on_nondate"

_INTEGER_ARGUMENTS: dict[str, tuple[int, ...]] = {
    "substring": (1, 2),
    "scan_token": (1,),
    "pad_left": (1,),
    "pad_right": (1,),
    "round": (1,),
    "modulo": (0, 1),
    "date_add_days": (1,),
}

_HOMOGENEOUS_FUNCTIONS = frozenset({"n_missing", "n_present", "min_of", "max_of"})

_DATE_PRODUCERS = frozenset({"parse_date", "date_add_days"})
_DATETIME_PRODUCERS = frozenset({"parse_datetime"})
_DATE_CONSUMERS: dict[str, str] = {
    "year": "date",
    "month": "date",
    "day": "date",
    "date_diff_days": "date",
    "study_day": "date",
    "date_add_days": "date",
    "date_diff_months": "date",
    "hour": "datetime",
    "minute": "datetime",
    "second": "datetime",
}

_LiteralType = str | None


def _literal_result_type(expression: Expression) -> _LiteralType:
    """Return the static character/numeric type of a literal result, else None."""

    if expression.kind != "literal":
        return None
    value = expression.value
    if value is None:
        return None
    if isinstance(value, bool):
        return "numeric"
    if isinstance(value, (int, float)):
        return "numeric"
    if isinstance(value, str):
        return "character"
    return None


def _is_integer_literal(expression: Expression) -> bool | None:
    """True/False when statically decidable, None when the type is dynamic."""

    if expression.kind != "literal":
        return None
    value = expression.value
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return value.is_integer()
    return False


def _produces_date(expression: Expression) -> str | None:
    """Return 'date'/'datetime' when an expression statically yields that kind."""

    if expression.kind == "function":
        if expression.function in _DATE_PRODUCERS:
            return "date"
        if expression.function in _DATETIME_PRODUCERS:
            return "datetime"
    if expression.kind == "literal" and expression.value is None:
        return None
    return "unknown"


def _issue(
    *,
    code: str,
    severity: IssueSeverity,
    message: str,
    suggestion: str,
    module: str,
    entity_type: str,
    entity_id: UUID | None,
    field_path: str,
) -> ValidationIssue:
    key = f"{entity_id}:{code}:{field_path}"
    return ValidationIssue(
        id=uuid5(_ISSUE_NAMESPACE, key),
        code=code,
        severity=severity,
        message=message,
        suggestion=suggestion,
        module=module,
        entity_type=entity_type,
        entity_id=entity_id,
        field_path=field_path,
    )


def _check_conditional(
    expression: ConditionalExpression,
    *,
    field_path: str,
    module: str,
    entity_type: str,
    entity_id: UUID | None,
) -> Iterator[ValidationIssue]:
    if not expression.branches:
        yield _issue(
            code=EXPR_CONDITIONAL_EMPTY,
            severity=IssueSeverity.ERROR,
            message="A conditional expression must declare at least one branch.",
            suggestion="Add a when/then branch or replace the conditional with its otherwise.",
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
            field_path=f"{field_path}.branches",
        )

    result_types = {_literal_result_type(branch.then) for branch in expression.branches}
    result_types.add(_literal_result_type(expression.otherwise))
    declared = {item for item in result_types if item is not None}
    if len(declared) > 1:
        yield _issue(
            code=EXPR_CONDITIONAL_RESULT_TYPE_MIXED,
            severity=IssueSeverity.WARNING,
            message=(
                "Conditional branch results mix character and numeric literal types; "
                "backends will not coerce between them."
            ),
            suggestion="Use the same character/numeric type for every then and the otherwise.",
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
            field_path=field_path,
        )

    seen: list[Expression] = []
    for index, branch in enumerate(expression.branches):
        if any(branch.when == earlier for earlier in seen):
            yield _issue(
                code=EXPR_CONDITIONAL_BRANCH_UNREACHABLE,
                severity=IssueSeverity.WARNING,
                message=(
                    "A later branch repeats an earlier branch guard and can never be reached."
                ),
                suggestion="Remove the duplicate branch or change its when condition.",
                module=module,
                entity_type=entity_type,
                entity_id=entity_id,
                field_path=f"{field_path}.branches[{index}].when",
            )
        seen.append(branch.when)


def _check_function(
    expression: FunctionCallExpression,
    *,
    field_path: str,
    module: str,
    entity_type: str,
    entity_id: UUID | None,
) -> Iterator[ValidationIssue]:
    name = expression.function
    count = len(expression.arguments)

    def issue(
        code: str, severity: IssueSeverity, message: str, suggestion: str, path: str
    ) -> ValidationIssue:
        return _issue(
            code=code,
            severity=severity,
            message=message,
            suggestion=suggestion,
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
            field_path=path,
        )

    if name not in _FUNCTION_ARITY and name not in _FUNCTION_MIN_ARITY:
        yield issue(
            EXPR_FUNCTION_UNKNOWN,
            IssueSeverity.ERROR,
            f"Function '{name}' is not in the typed catalog.",
            "Use a catalog function or request a reviewed addition.",
            f"{field_path}.function",
        )
        return

    if name in _FUNCTION_ARITY and count != _FUNCTION_ARITY[name]:
        yield issue(
            EXPR_FUNCTION_ARITY,
            IssueSeverity.ERROR,
            f"Function '{name}' expects {_FUNCTION_ARITY[name]} arguments but received {count}.",
            "Provide the exact number of arguments the function requires.",
            f"{field_path}.arguments",
        )
    elif name in _FUNCTION_MIN_ARITY and count < _FUNCTION_MIN_ARITY[name]:
        yield issue(
            EXPR_FUNCTION_ARITY,
            IssueSeverity.ERROR,
            f"Function '{name}' requires at least {_FUNCTION_MIN_ARITY[name]} arguments.",
            "Add more arguments to satisfy the minimum arity.",
            f"{field_path}.arguments",
        )

    # Integer-typed argument slots (D-driven; statically decidable only).
    for index in _INTEGER_ARGUMENTS.get(name, ()):
        if index < count and _is_integer_literal(expression.arguments[index]) is False:
            yield issue(
                EXPR_FUNCTION_ARG_TYPE,
                IssueSeverity.ERROR,
                f"Argument {index + 1} of '{name}' must be an integer.",
                "Supply an integer literal or an integer-typed expression.",
                f"{field_path}.arguments[{index}]",
            )

    # replace find must be non-empty (statically decidable).
    if name == "replace" and count >= 2:
        find = expression.arguments[1]
        if find.kind == "literal" and find.value == "":
            yield issue(
                EXPR_FUNCTION_ARG_TYPE,
                IssueSeverity.ERROR,
                "replace find argument must not be an empty string.",
                "Provide a non-empty substring to replace.",
                f"{field_path}.arguments[1]",
            )

    # pad fill must be a single character (statically decidable).
    if name in {"pad_left", "pad_right"} and count >= 3:
        fill = expression.arguments[2]
        if fill.kind == "literal" and isinstance(fill.value, str) and len(fill.value) != 1:
            yield issue(
                EXPR_FUNCTION_ARG_TYPE,
                IssueSeverity.ERROR,
                f"'{name}' fill argument must be exactly one character.",
                "Provide a single-character fill value.",
                f"{field_path}.arguments[2]",
            )

    # D11 homogeneous static types for variadic numeric/null-count functions.
    if name in _HOMOGENEOUS_FUNCTIONS:
        declared = {
            _literal_result_type(argument)
            for argument in expression.arguments
            if _literal_result_type(argument) is not None
        }
        if len(declared) > 1:
            yield issue(
                EXPR_FUNCTION_ARG_TYPE,
                IssueSeverity.ERROR,
                f"'{name}' arguments must share one static type (all numeric or all character).",
                "Use a single character/numeric type across every argument.",
                f"{field_path}.arguments",
            )

    # Date functions should consume parse_date/parse_datetime output (warning).
    expected_kind = _DATE_CONSUMERS.get(name)
    if expected_kind is not None:
        two_date_args = {"date_diff_days", "date_diff_months", "study_day"}
        slot_count = 2 if name in two_date_args else 1
        for index in range(min(count, slot_count)):
            produced = _produces_date(expression.arguments[index])
            if produced == "unknown" or (produced is not None and produced != expected_kind):
                yield issue(
                    EXPR_DATE_FUNCTION_ON_NONDATE,
                    IssueSeverity.WARNING,
                    f"'{name}' expects a {expected_kind} produced by parse_{expected_kind}.",
                    f"Wrap the argument in parse_{expected_kind} first.",
                    f"{field_path}.arguments[{index}]",
                )


def _walk(
    expression: Expression,
    *,
    field_path: str,
    module: str,
    entity_type: str,
    entity_id: UUID | None,
) -> Iterator[ValidationIssue]:
    if expression.kind == "function":
        yield from _check_function(
            expression,
            field_path=field_path,
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        for index, argument in enumerate(expression.arguments):
            if argument.kind == "list_literal":
                allowed = expression.function == "is_in" and index == 1
                if not allowed:
                    yield _issue(
                        code=EXPR_LIST_LITERAL_MISPLACED,
                        severity=IssueSeverity.ERROR,
                        message="A list literal is only valid as the second argument of is_in.",
                        suggestion="Move the list literal into an is_in call or use a literal.",
                        module=module,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        field_path=f"{field_path}.arguments[{index}]",
                    )
                continue
            yield from _walk(
                argument,
                field_path=f"{field_path}.arguments[{index}]",
                module=module,
                entity_type=entity_type,
                entity_id=entity_id,
            )
        return
    if expression.kind == "list_literal":
        yield _issue(
            code=EXPR_LIST_LITERAL_MISPLACED,
            severity=IssueSeverity.ERROR,
            message="A list literal is only valid as the second argument of is_in.",
            suggestion="Use the list literal inside an is_in call.",
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
            field_path=field_path,
        )
        return
    if expression.kind == "conditional":
        yield from _check_conditional(
            expression,
            field_path=field_path,
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        for index, branch in enumerate(expression.branches):
            branch_path = f"{field_path}.branches[{index}]"
            yield from _walk(
                branch.when,
                field_path=f"{branch_path}.when",
                module=module,
                entity_type=entity_type,
                entity_id=entity_id,
            )
            yield from _walk(
                branch.then,
                field_path=f"{branch_path}.then",
                module=module,
                entity_type=entity_type,
                entity_id=entity_id,
            )
        yield from _walk(
            expression.otherwise,
            field_path=f"{field_path}.otherwise",
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    elif expression.kind == "unary":
        yield from _walk(
            expression.operand,
            field_path=f"{field_path}.operand",
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    elif expression.kind == "binary":
        yield from _walk(
            expression.left,
            field_path=f"{field_path}.left",
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        yield from _walk(
            expression.right,
            field_path=f"{field_path}.right",
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
        )


def validate_expression(
    expression: Expression,
    *,
    field_path: str,
    module: str,
    entity_type: str,
    entity_id: UUID | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate one expression tree, returning stable common-model issues."""

    return tuple(
        _walk(
            expression,
            field_path=field_path,
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    )


def validate_expressions(
    expressions: Iterable[tuple[str, Expression]],
    *,
    module: str,
    entity_type: str,
    entity_id: UUID | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate many ``(field_path, expression)`` pairs into one issue sequence."""

    issues: list[ValidationIssue] = []
    for field_path, expression in expressions:
        issues.extend(
            validate_expression(
                expression,
                field_path=field_path,
                module=module,
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )
    return tuple(issues)
