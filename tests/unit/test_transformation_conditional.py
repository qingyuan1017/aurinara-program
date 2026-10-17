"""Conditional-expression evaluator, codegen, contract, and validation tests."""

from uuid import UUID

import pytest

from app.transformation.codegen import UnsupportedOperator, _py_expr, _r_expr, _sas_expr
from app.transformation.contracts import ConditionalExpression, DataflowIR, DeriveNode, Expression
from app.transformation.evaluator import _value, evaluate_dataflow
from app.transformation.expression_validation import (
    EXPR_CONDITIONAL_BRANCH_UNREACHABLE,
    EXPR_CONDITIONAL_RESULT_TYPE_MIXED,
    validate_expression,
)
from app.transformation.service import BackendCapabilityMissing, compile_dataflow


def _ittfl() -> ConditionalExpression:
    return ConditionalExpression.model_validate(
        {
            "kind": "conditional",
            "branches": [
                {
                    "when": {
                        "kind": "binary",
                        "operator": "and",
                        "left": {
                            "kind": "binary",
                            "operator": "eq",
                            "left": {"kind": "column", "dataset": "dm", "column": "SAFFL"},
                            "right": {"kind": "literal", "value": "Y"},
                        },
                        "right": {
                            "kind": "binary",
                            "operator": "eq",
                            "left": {"kind": "column", "dataset": "dm", "column": "RANDFL"},
                            "right": {"kind": "literal", "value": "Y"},
                        },
                    },
                    "then": {"kind": "literal", "value": "Y"},
                }
            ],
            "otherwise": {"kind": "literal", "value": None},
        }
    )


def _as_expression(value: object) -> Expression:
    return DeriveNode.model_validate(
        {"node_type": "derive", "id": "d", "assignments": {"X": value}}
    ).assignments["X"]


# --- evaluator ---------------------------------------------------------------


def test_evaluator_selects_matching_branch() -> None:
    expression = _ittfl()
    assert _value(expression, {"SAFFL": "Y", "RANDFL": "Y"}) == "Y"
    assert _value(expression, {"SAFFL": "Y", "RANDFL": "N"}) is None


def test_evaluator_null_when_is_not_matched() -> None:
    expression = _as_expression(
        {
            "kind": "conditional",
            "branches": [
                {
                    "when": {"kind": "literal", "value": None},
                    "then": {"kind": "literal", "value": "A"},
                }
            ],
            "otherwise": {"kind": "literal", "value": "B"},
        }
    )
    assert _value(expression, {}) == "B"


def test_evaluator_short_circuits_unmatched_division() -> None:
    expression = _as_expression(
        {
            "kind": "conditional",
            "branches": [
                {
                    "when": {"kind": "literal", "value": True},
                    "then": {"kind": "literal", "value": 1},
                },
                {
                    "when": {"kind": "literal", "value": True},
                    "then": {
                        "kind": "binary",
                        "operator": "div",
                        "left": {"kind": "literal", "value": 1},
                        "right": {"kind": "literal", "value": 0},
                    },
                },
            ],
            "otherwise": {"kind": "literal", "value": 9},
        }
    )
    assert _value(expression, {}) == 1


def test_evaluator_d1_swallows_arithmetic_error_to_null() -> None:
    expression = _as_expression(
        {
            "kind": "conditional",
            "branches": [
                {
                    "when": {"kind": "literal", "value": True},
                    "then": {
                        "kind": "binary",
                        "operator": "div",
                        "left": {"kind": "literal", "value": 1},
                        "right": {"kind": "literal", "value": 0},
                    },
                }
            ],
            "otherwise": {"kind": "literal", "value": 9},
        }
    )
    assert _value(expression, {}) is None


def test_evaluator_d1_does_not_swallow_unknown_column() -> None:
    expression = _as_expression(
        {
            "kind": "conditional",
            "branches": [
                {
                    "when": {"kind": "literal", "value": True},
                    "then": {"kind": "column", "dataset": "dm", "column": "MISSING"},
                }
            ],
            "otherwise": {"kind": "literal", "value": 9},
        }
    )
    from app.common.problems import ProblemException

    with pytest.raises(ProblemException) as captured:
        _value(expression, {})
    assert captured.value.code == "preview_column_unknown"


# --- codegen -----------------------------------------------------------------


def test_py_expr_right_folds_with_guard() -> None:
    source = _py_expr(_ittfl(), "row")
    assert "guard(lambda:" in source
    assert source.count("if ((_c :=") == 1
    assert source.endswith("else (None))")


def test_r_expr_uses_na_guarded_ifelse_with_normalizer() -> None:
    source = _r_expr(_ittfl(), "frame")
    assert source.startswith("ifelse(")
    assert "!is.na(" in source
    assert "aur_norm(" in source


def test_sas_expr_picks_ifc_for_character_result() -> None:
    source = _sas_expr(_ittfl(), "character")
    assert source.startswith("IFC(")


def test_sas_expr_picks_ifn_for_numeric_result() -> None:
    numeric = _as_expression(
        {
            "kind": "conditional",
            "branches": [
                {
                    "when": {"kind": "literal", "value": True},
                    "then": {"kind": "literal", "value": 1},
                }
            ],
            "otherwise": {"kind": "literal", "value": 0},
        }
    )
    source = _sas_expr(numeric, "numeric")
    assert source.startswith("IFN(")


def test_sas_expr_raises_without_result_type() -> None:
    with pytest.raises(UnsupportedOperator):
        _sas_expr(_ittfl(), None)


def _conditional_flow(result_types: dict[str, str] | None) -> DataflowIR:
    derive: dict[str, object] = {
        "node_type": "derive",
        "id": "flag",
        "assignments": {"ITTFL": _ittfl().model_dump(mode="json")},
    }
    if result_types is not None:
        derive["result_types"] = result_types
    return DataflowIR.model_validate(
        {
            "nodes": [
                {"node_type": "read", "id": "read", "dataset": "dm"},
                derive,
                {"node_type": "write", "id": "write", "dataset": "ADSL"},
            ],
            "edges": [
                {"source_node": "read", "target_node": "flag"},
                {"source_node": "flag", "target_node": "write"},
            ],
        }
    )


def test_sas_compiles_with_result_types_and_fails_without() -> None:
    program = compile_dataflow(_conditional_flow({"ITTFL": "character"}), "sas")
    assert "IFC(" in program.source
    assert program.compiler_version == "1.8.0"
    with pytest.raises(BackendCapabilityMissing):
        compile_dataflow(_conditional_flow(None), "sas")


def test_compiler_banner_is_bumped() -> None:
    flow = _conditional_flow({"ITTFL": "character"})
    assert "compiler=1.8.0" in compile_dataflow(flow, "python").source
    assert "compiler=1.8.0" in compile_dataflow(flow, "r").source


# --- contract round-trip and backward compatibility --------------------------


def test_conditional_contract_round_trips() -> None:
    expression = _ittfl()
    restored = ConditionalExpression.model_validate(expression.model_dump(mode="json"))
    assert restored == expression


def test_old_ir_without_result_types_validates_and_lowers() -> None:
    flow = _conditional_flow(None)
    assert flow.operator_version == "1.4.0"
    assert flow.schema_version == "1.0.0"
    derive = next(node for node in flow.nodes if node.node_type == "derive")
    assert derive.result_types == {}
    # Python/R unaffected by the missing result type.
    assert compile_dataflow(flow, "python").source
    assert compile_dataflow(flow, "r").source


def test_derive_executes_conditional_in_preview() -> None:
    outputs = evaluate_dataflow(
        _conditional_flow({"ITTFL": "character"}),
        {"dm": ({"SAFFL": "Y", "RANDFL": "Y"}, {"SAFFL": "Y", "RANDFL": "N"})},
    )
    assert [row["ITTFL"] for row in outputs["ADSL"]] == ["Y", None]


# --- validation --------------------------------------------------------------


def test_validation_flags_mixed_result_types() -> None:
    expression = _as_expression(
        {
            "kind": "conditional",
            "branches": [
                {
                    "when": {"kind": "literal", "value": True},
                    "then": {"kind": "literal", "value": "A"},
                }
            ],
            "otherwise": {"kind": "literal", "value": 1},
        }
    )
    issues = validate_expression(expression, field_path="x", module="sdtm", entity_type="plan")
    assert [issue.code for issue in issues] == [EXPR_CONDITIONAL_RESULT_TYPE_MIXED]


def test_validation_flags_unreachable_duplicate_branch() -> None:
    guard = {
        "kind": "binary",
        "operator": "eq",
        "left": {"kind": "column", "dataset": "dm", "column": "A"},
        "right": {"kind": "literal", "value": "Y"},
    }
    expression = _as_expression(
        {
            "kind": "conditional",
            "branches": [
                {"when": guard, "then": {"kind": "literal", "value": "A"}},
                {"when": guard, "then": {"kind": "literal", "value": "B"}},
            ],
            "otherwise": {"kind": "literal", "value": "C"},
        }
    )
    issues = validate_expression(expression, field_path="x", module="sdtm", entity_type="plan")
    assert [issue.code for issue in issues] == [EXPR_CONDITIONAL_BRANCH_UNREACHABLE]
    assert issues[0].field_path == "x.branches[1].when"


def test_validation_ids_are_deterministic() -> None:
    expression = _as_expression(
        {
            "kind": "conditional",
            "branches": [
                {
                    "when": {"kind": "literal", "value": True},
                    "then": {"kind": "literal", "value": "A"},
                }
            ],
            "otherwise": {"kind": "literal", "value": 1},
        }
    )
    first = validate_expression(
        expression, field_path="x", module="sdtm", entity_type="plan", entity_id=None
    )
    second = validate_expression(
        expression, field_path="x", module="sdtm", entity_type="plan", entity_id=None
    )
    assert [issue.id for issue in first] == [issue.id for issue in second]
    assert all(isinstance(issue.id, UUID) for issue in first)
