"""Property tests for the typed function catalog."""

import datetime as dt

from hypothesis import given
from hypothesis import strategies as st

from app.transformation import expression_functions as fns
from app.transformation.contracts import DeriveNode, Expression, FunctionCallExpression
from app.transformation.evaluator import _value


def _lit(value: object) -> dict[str, object]:
    return {"kind": "literal", "value": value}


def _fn(name: str, *arguments: dict[str, object]) -> dict[str, object]:
    return {"kind": "function", "function": name, "arguments": list(arguments)}


def _as_expression(value: dict[str, object]) -> Expression:
    return DeriveNode.model_validate(
        {"node_type": "derive", "id": "d", "assignments": {"X": value}}
    ).assignments["X"]


@given(
    st.text(max_size=12),
    st.integers(min_value=1, max_value=14),
    st.integers(min_value=0, max_value=14),
)
def test_substring_round_trips_and_is_one_based(source: str, start: int, length: int) -> None:
    payload = _fn("substring", _lit(source), _lit(start), _lit(length))
    expression = FunctionCallExpression.model_validate(payload)
    restored = FunctionCallExpression.model_validate(expression.model_dump(mode="json"))
    assert restored == expression
    result = _value(_as_expression(payload), {})
    assert result == source[start - 1 : start - 1 + length] if length > 0 else result == ""


@given(st.text(min_size=1, max_size=10), st.text(min_size=1, max_size=3))
def test_index_of_matches_one_based_find(source: str, needle: str) -> None:
    result = _value(_as_expression(_fn("index_of", _lit(source), _lit(needle))), {})
    assert result == source.find(needle) + 1


@given(st.integers(min_value=-200, max_value=200), st.integers(min_value=1, max_value=37))
def test_modulo_sign_follows_dividend(dividend: int, divisor: int) -> None:
    result = _value(_as_expression(_fn("modulo", _lit(dividend), _lit(divisor))), {})
    assert result == dividend - divisor * int(dividend / divisor)
    assert isinstance(result, int)
    if dividend != 0:
        assert (result >= 0) == (dividend >= 0) or result == 0


@given(
    st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
    st.integers(min_value=0, max_value=4),
)
def test_round_half_away_matches_reference(value: float, digits: int) -> None:
    result = _value(_as_expression(_fn("round", _lit(value), _lit(digits))), {})
    assert result == fns.half_away_round(value, digits)


@given(st.dates(min_value=dt.date(1990, 1, 1), max_value=dt.date(2040, 1, 1)))
def test_parse_date_valid_full_dates(day: dt.date) -> None:
    text = day.isoformat()
    assert _value(_as_expression(_fn("parse_date", _lit(text))), {}) == day


@given(st.sampled_from(["2021", "2021-03", "2021/03/04", "not-a-date", "20210304"]))
def test_parse_date_rejects_partial_or_invalid(text: str) -> None:
    assert _value(_as_expression(_fn("parse_date", _lit(text))), {}) is None


@given(st.integers(min_value=-5, max_value=5))
def test_study_day_boundaries(delta: int) -> None:
    reference = dt.date(2021, 6, 15)
    event = reference + dt.timedelta(days=delta)
    payload = _fn(
        "study_day",
        _fn("parse_date", _lit(event.isoformat())),
        _fn("parse_date", _lit(reference.isoformat())),
    )
    result = _value(_as_expression(payload), {})
    expected = delta + 1 if delta >= 0 else delta
    assert result == expected
    if delta == 0:
        assert result == 1
    if delta == -1:
        assert result == -1
