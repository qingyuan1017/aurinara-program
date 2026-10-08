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

from app.transformation.contracts import ConditionalExpression, Expression
from app.validation.contracts import IssueSeverity, ValidationIssue

_ISSUE_NAMESPACE = UUID("f6b3c3d8-9c2a-4e4b-9a0c-2d6a1b7e5c40")

EXPR_CONDITIONAL_EMPTY = "expr_conditional_empty"
EXPR_CONDITIONAL_RESULT_TYPE_MIXED = "expr_conditional_result_type_mixed"
EXPR_CONDITIONAL_BRANCH_UNREACHABLE = "expr_conditional_branch_unreachable"

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


def _walk(
    expression: Expression,
    *,
    field_path: str,
    module: str,
    entity_type: str,
    entity_id: UUID | None,
) -> Iterator[ValidationIssue]:
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
