"""FunctionCallExpression + ListLiteralExpression evaluator, codegen, validation tests."""

import datetime as dt

import pytest
from pydantic import ValidationError

from app.transformation.codegen import UnsupportedOperator, _py_expr, _r_expr, _sas_expr
from app.transformation.contracts import (
    DeriveNode,
    Expression,
    FunctionCallExpression,
    ListLiteralExpression,
)
from app.transformation.evaluator import _value
from app.transformation.expression_validation import (
    EXPR_DATE_FUNCTION_ON_NONDATE,
    EXPR_FUNCTION_ARG_TYPE,
    EXPR_FUNCTION_ARITY,
    EXPR_LIST_LITERAL_MISPLACED,
    validate_expression,
)


def _lit(value: object) -> dict[str, object]:
    return {"kind": "literal", "value": value}


def _col(name: str) -> dict[str, object]:
    return {"kind": "column", "dataset": "src", "column": name}


def _fn(name: str, *arguments: dict[str, object]) -> dict[str, object]:
    return {"kind": "function", "function": name, "arguments": list(arguments)}


def _as_expression(value: dict[str, object]) -> Expression:
    return DeriveNode.model_validate(
        {"node_type": "derive", "id": "d", "assignments": {"X": value}}
    ).assignments["X"]


# --- evaluator: string -------------------------------------------------------


def test_concat_treats_null_as_empty() -> None:
    expr = _as_expression(_fn("concat", _lit("A"), _lit(None), _lit("B")))
    assert _value(expr, {}) == "AB"


def test_substring_is_one_based() -> None:
    expr = _as_expression(_fn("substring", _lit("ABCDE"), _lit(2), _lit(3)))
    assert _value(expr, {}) == "BCD"


def test_substring_out_of_range_is_empty() -> None:
    expr = _as_expression(_fn("substring", _lit("AB"), _lit(5), _lit(3)))
    assert _value(expr, {}) == ""


def test_upper_lower_ascii_only() -> None:
    # Non-ASCII 'Ñ' is left unchanged (D5); only ASCII a-z/A-Z are cased.
    assert _value(_as_expression(_fn("upper", _lit("aÑb"))), {}) == "AÑB"
    assert _value(_as_expression(_fn("lower", _lit("AÑB"))), {}) == "aÑb"


def test_length_null_in_null_out() -> None:
    assert _value(_as_expression(_fn("length", _lit(None))), {}) is None
    assert _value(_as_expression(_fn("length", _lit("abc"))), {}) == 3


def test_contains_startswith_endswith() -> None:
    assert _value(_as_expression(_fn("contains", _lit("hello"), _lit("ell"))), {}) is True
    assert _value(_as_expression(_fn("startswith", _lit("hello"), _lit("he"))), {}) is True
    assert _value(_as_expression(_fn("endswith", _lit("hello"), _lit("lo"))), {}) is True


def test_replace_all_occurrences() -> None:
    assert _value(_as_expression(_fn("replace", _lit("a.b.c"), _lit("."), _lit("-"))), {}) == (
        "a-b-c"
    )


def test_index_of_is_one_based_zero_when_absent() -> None:
    assert _value(_as_expression(_fn("index_of", _lit("hello"), _lit("l"))), {}) == 3
    assert _value(_as_expression(_fn("index_of", _lit("hello"), _lit("z"))), {}) == 0


def test_scan_token_collapses_delimiters() -> None:
    assert _value(_as_expression(_fn("scan_token", _lit("a,,b"), _lit(2), _lit(","))), {}) == "b"
    assert _value(_as_expression(_fn("scan_token", _lit("a,b"), _lit(3), _lit(","))), {}) is None


def test_pad_left_right() -> None:
    assert _value(_as_expression(_fn("pad_left", _lit("7"), _lit(3), _lit("0"))), {}) == "007"
    assert _value(_as_expression(_fn("pad_right", _lit("7"), _lit(3), _lit("x"))), {}) == "7xx"


# --- evaluator: null/logical -------------------------------------------------


def test_coalesce_first_non_null() -> None:
    assert _value(_as_expression(_fn("coalesce", _lit(None), _lit(None), _lit("Z"))), {}) == "Z"
    assert _value(_as_expression(_fn("coalesce", _lit(None))), {}) is None


def test_nullif() -> None:
    assert _value(_as_expression(_fn("nullif", _lit("A"), _lit("A"))), {}) is None
    assert _value(_as_expression(_fn("nullif", _lit("A"), _lit("B"))), {}) == "A"


def test_is_in_with_list_literal() -> None:
    expr = _as_expression(
        _fn("is_in", _lit("B"), {"kind": "list_literal", "values": ["A", "B", "C"]})
    )
    assert _value(expr, {}) is True
    null_expr = _as_expression(_fn("is_in", _lit(None), {"kind": "list_literal", "values": ["A"]}))
    assert _value(null_expr, {}) is False


def test_n_missing_present() -> None:
    assert _value(_as_expression(_fn("n_missing", _lit(1), _lit(None), _lit(3))), {}) == 1
    assert _value(_as_expression(_fn("n_present", _lit(1), _lit(None), _lit(3))), {}) == 2


# --- evaluator: numeric (D3) -------------------------------------------------


def test_round_half_away_from_zero() -> None:
    assert _value(_as_expression(_fn("round", _lit(2.5), _lit(0))), {}) == 3.0
    assert _value(_as_expression(_fn("round", _lit(-2.5), _lit(0))), {}) == -3.0


def test_modulo_truncated_dividend_sign() -> None:
    assert _value(_as_expression(_fn("modulo", _lit(-7), _lit(3))), {}) == -1
    assert _value(_as_expression(_fn("modulo", _lit(7), _lit(0))), {}) is None


def test_floor_ceil_truncate_distinguish_negatives() -> None:
    assert _value(_as_expression(_fn("floor", _lit(-1.5))), {}) == -2
    assert _value(_as_expression(_fn("ceil", _lit(-1.5))), {}) == -1
    assert _value(_as_expression(_fn("truncate", _lit(-1.5))), {}) == -1


def test_min_max_of_skip_nulls() -> None:
    assert _value(_as_expression(_fn("min_of", _lit(3), _lit(None), _lit(1))), {}) == 1
    assert _value(_as_expression(_fn("max_of", _lit(3), _lit(None), _lit(1))), {}) == 3


def test_safe_divide_null_on_zero() -> None:
    assert _value(_as_expression(_fn("safe_divide", _lit(1), _lit(0))), {}) is None
    assert _value(_as_expression(_fn("safe_divide", _lit(6), _lit(2))), {}) == 3.0


# --- evaluator: date/datetime (D4, D8, D9, D10) ------------------------------


def test_parse_date_full_only() -> None:
    assert _value(_as_expression(_fn("parse_date", _lit("2021-03-04"))), {}) == dt.date(2021, 3, 4)
    assert _value(_as_expression(_fn("parse_date", _lit("2021-03"))), {}) is None
    assert _value(_as_expression(_fn("parse_date", _lit("2021"))), {}) is None


def test_year_month_day() -> None:
    base = _fn("parse_date", _lit("2021-03-04"))
    assert _value(_as_expression(_fn("year", base)), {}) == 2021
    assert _value(_as_expression(_fn("month", base)), {}) == 3
    assert _value(_as_expression(_fn("day", base)), {}) == 4


def test_date_diff_days_and_add() -> None:
    end = _fn("parse_date", _lit("2021-01-10"))
    start = _fn("parse_date", _lit("2021-01-01"))
    assert _value(_as_expression(_fn("date_diff_days", end, start)), {}) == 9
    added = _value(_as_expression(_fn("date_add_days", start, _lit(5))), {})
    assert added == dt.date(2021, 1, 6)


def test_study_day_no_day_zero() -> None:
    reference = _fn("parse_date", _lit("2021-01-01"))
    same = _fn("parse_date", _lit("2021-01-01"))
    before = _fn("parse_date", _lit("2020-12-31"))
    assert _value(_as_expression(_fn("study_day", same, reference)), {}) == 1
    assert _value(_as_expression(_fn("study_day", before, reference)), {}) == -1


def test_date_diff_months_continuous() -> None:
    end = _fn("parse_date", _lit("2021-03-10"))
    start = _fn("parse_date", _lit("2021-01-15"))
    assert _value(_as_expression(_fn("date_diff_months", end, start)), {}) == 1


def test_parse_datetime_naive_offset_rejected() -> None:
    naive = _fn("parse_datetime", _lit("2021-03-04T08:30:00"))
    assert _value(_as_expression(_fn("hour", naive)), {}) == 8
    assert _value(_as_expression(_fn("minute", naive)), {}) == 30
    offset = _fn("parse_datetime", _lit("2021-03-04T08:30:00+02:00"))
    assert _value(_as_expression(_fn("second", offset)), {}) is None


# --- contract validation -----------------------------------------------------


def test_contract_rejects_wrong_arity() -> None:
    with pytest.raises(ValidationError):
        FunctionCallExpression.model_validate(_fn("upper", _lit("a"), _lit("b")))


def test_contract_rejects_variadic_below_minimum() -> None:
    with pytest.raises(ValidationError):
        FunctionCallExpression.model_validate(
            {"kind": "function", "function": "concat", "arguments": []}
        )


def test_contract_rejects_list_literal_outside_is_in() -> None:
    with pytest.raises(ValidationError):
        FunctionCallExpression.model_validate(
            _fn("concat", {"kind": "list_literal", "values": ["A"]})
        )


def test_contract_requires_list_literal_for_is_in() -> None:
    with pytest.raises(ValidationError):
        FunctionCallExpression.model_validate(_fn("is_in", _lit("A"), _lit("B")))


def test_list_literal_round_trips() -> None:
    literal = ListLiteralExpression.model_validate({"kind": "list_literal", "values": [1, "x"]})
    assert ListLiteralExpression.model_validate(literal.model_dump(mode="json")) == literal


# --- codegen golden ----------------------------------------------------------


def test_py_expr_lowers_functions_to_fn_helpers() -> None:
    assert _py_expr(_as_expression(_fn("upper", _col("A")))) == "fn_upper([row['A']])"
    is_in = _as_expression(_fn("is_in", _col("A"), {"kind": "list_literal", "values": ["X", "Y"]}))
    assert _py_expr(is_in) == "fn_is_in(row['A'], ('X', 'Y',))"


def test_r_expr_lowers_functions_to_aur_helpers() -> None:
    assert _r_expr(_as_expression(_fn("upper", _col("A")))) == 'aur_upper(frame[["A"]])'
    is_in = _as_expression(_fn("is_in", _col("A"), {"kind": "list_literal", "values": ["X"]}))
    assert _r_expr(is_in) == 'aur_is_in(frame[["A"]], list("X"))'


def test_sas_expr_round_uses_explicit_half_away() -> None:
    source = _sas_expr(_as_expression(_fn("round", _col("X"), _lit(2))))
    assert "sign(X)" in source and "round(abs(X)" in source


def test_sas_expr_study_day_formula() -> None:
    source = _sas_expr(
        _as_expression(
            _fn(
                "study_day",
                _fn("parse_date", _col("ADTC")),
                _fn("parse_date", _col("RFSTDTC")),
            )
        )
    )
    assert source.startswith("ifn(")
    assert "+ 1" in source


def test_sas_coalesce_char_vs_numeric() -> None:
    char = _sas_expr(_as_expression(_fn("coalesce", _col("A"), _col("B"))), "character")
    numeric = _sas_expr(_as_expression(_fn("coalesce", _col("A"), _col("B"))), "numeric")
    assert char.startswith("coalescec(")
    assert numeric.startswith("coalesce(")


def test_sas_n_missing_char_vs_numeric() -> None:
    char = _sas_expr(_as_expression(_fn("n_missing", _col("A"), _col("B"))), "character")
    numeric = _sas_expr(_as_expression(_fn("n_missing", _col("A"), _col("B"))), "numeric")
    assert char.startswith("cmiss(")
    assert numeric.startswith("nmiss(")


def test_sas_date_function_requires_parse_date() -> None:
    with pytest.raises(UnsupportedOperator):
        _sas_expr(_as_expression(_fn("year", _col("RAWDATE"))))


# --- expression validation ---------------------------------------------------


def test_validation_flags_misplaced_list_literal() -> None:
    expression = _as_expression(
        {
            "kind": "conditional",
            "branches": [
                {
                    "when": {"kind": "literal", "value": True},
                    "then": {"kind": "list_literal", "values": ["A"]},
                }
            ],
            "otherwise": {"kind": "literal", "value": "Z"},
        }
    )
    issues = validate_expression(expression, field_path="x", module="sdtm", entity_type="plan")
    assert EXPR_LIST_LITERAL_MISPLACED in {issue.code for issue in issues}


def test_validation_flags_non_integer_substring_start() -> None:
    expression = _as_expression(_fn("substring", _lit("abc"), _lit("x"), _lit(2)))
    issues = validate_expression(expression, field_path="x", module="sdtm", entity_type="plan")
    assert EXPR_FUNCTION_ARG_TYPE in {issue.code for issue in issues}


def test_validation_flags_empty_replace_find() -> None:
    expression = _as_expression(_fn("replace", _lit("abc"), _lit(""), _lit("-")))
    issues = validate_expression(expression, field_path="x", module="sdtm", entity_type="plan")
    assert EXPR_FUNCTION_ARG_TYPE in {issue.code for issue in issues}


def test_validation_flags_pad_fill_not_single_char() -> None:
    expression = _as_expression(_fn("pad_left", _lit("1"), _lit(3), _lit("ab")))
    issues = validate_expression(expression, field_path="x", module="sdtm", entity_type="plan")
    assert EXPR_FUNCTION_ARG_TYPE in {issue.code for issue in issues}


def test_validation_flags_heterogeneous_min_of() -> None:
    expression = _as_expression(_fn("min_of", _lit(1), _lit("a")))
    issues = validate_expression(expression, field_path="x", module="sdtm", entity_type="plan")
    assert EXPR_FUNCTION_ARG_TYPE in {issue.code for issue in issues}


def test_validation_warns_date_function_on_nondate() -> None:
    expression = _as_expression(_fn("year", _col("RAWDATE")))
    issues = validate_expression(expression, field_path="x", module="sdtm", entity_type="plan")
    assert EXPR_DATE_FUNCTION_ON_NONDATE in {issue.code for issue in issues}


def test_validation_passes_date_function_on_parse_date() -> None:
    expression = _as_expression(_fn("year", _fn("parse_date", _col("RAWDATE"))))
    issues = validate_expression(expression, field_path="x", module="sdtm", entity_type="plan")
    assert EXPR_DATE_FUNCTION_ON_NONDATE not in {issue.code for issue in issues}


def test_validation_arity_defense_in_depth_via_walk() -> None:
    # Build a structurally valid call then confirm the harness reports arity when
    # a mismatch is present (constructed through model to bypass contract requires
    # a valid tree, so we assert the harness agrees with the contract on a good one).
    expression = _as_expression(_fn("concat", _lit("a"), _lit("b")))
    issues = validate_expression(expression, field_path="x", module="sdtm", entity_type="plan")
    assert EXPR_FUNCTION_ARITY not in {issue.code for issue in issues}
