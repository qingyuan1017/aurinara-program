"""Property tests for the conditional expression kind."""

from hypothesis import given
from hypothesis import strategies as st

from app.transformation.contracts import ConditionalExpression, Expression
from app.transformation.evaluator import _value

_literals = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    st.text(max_size=8),
)


def _literal(value: object) -> dict[str, object]:
    return {"kind": "literal", "value": value}


@st.composite
def _conditionals(draw: st.DrawFn) -> dict[str, object]:
    count = draw(st.integers(min_value=1, max_value=4))
    branches = [
        {
            "when": _literal(draw(st.booleans() | st.none())),
            "then": _literal(draw(_literals)),
        }
        for _ in range(count)
    ]
    return {
        "kind": "conditional",
        "branches": branches,
        "otherwise": _literal(draw(_literals)),
    }


@given(_conditionals())
def test_conditional_round_trips(payload: dict[str, object]) -> None:
    expression = ConditionalExpression.model_validate(payload)
    restored = ConditionalExpression.model_validate(expression.model_dump(mode="json"))
    assert restored == expression


@given(_conditionals())
def test_selection_matches_python_oracle(payload: dict[str, object]) -> None:
    expression: Expression = ConditionalExpression.model_validate(payload)

    expected = None
    for branch in payload["branches"]:  # type: ignore[attr-defined]
        condition = branch["when"]["value"]
        if condition is not None and bool(condition):
            expected = branch["then"]["value"]
            break
    else:
        expected = payload["otherwise"]["value"]  # type: ignore[index]

    assert _value(expression, {}) == expected


@given(st.lists(st.booleans() | st.none(), min_size=1, max_size=4))
def test_null_when_never_matches(conditions: list[bool | None]) -> None:
    branches = [
        {"when": _literal(condition), "then": _literal(index)}
        for index, condition in enumerate(conditions)
    ]
    expression = ConditionalExpression.model_validate(
        {"kind": "conditional", "branches": branches, "otherwise": _literal("fallback")}
    )
    result = _value(expression, {})
    truthy = [index for index, condition in enumerate(conditions) if condition]
    assert result == (truthy[0] if truthy else "fallback")
