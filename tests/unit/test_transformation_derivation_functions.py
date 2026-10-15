"""Cast and terminology mapping as typed derivation-expression functions."""

import pytest

from app.common.problems import ProblemException
from app.transformation.codegen import _py_expr, _r_expr, _sas_expr
from app.transformation.contracts import DataflowIR, DerivationExpression, DeriveNode
from app.transformation.evaluator import _value
from app.transformation.service import BackendCapabilityMissing, compile_dataflow


def _expression(value: object) -> DerivationExpression:
    return DeriveNode.model_validate(
        {"node_type": "derive", "id": "derive", "assignments": {"RESULT": value}}
    ).assignments["RESULT"]


def test_preview_evaluates_terminology_function() -> None:
    expression = _expression(
        {
            "kind": "terminology_map",
            "value": {"kind": "column", "dataset": "RAW", "column": "SEX"},
            "mappings": {"1": "M", "2": "F"},
            "unmapped": "preserve",
        }
    )

    assert _value(expression, {"SEX": 1}) == "M"
    assert _value(expression, {"SEX": 3}) == 3


def test_preview_honors_invalid_and_unmapped_policies() -> None:
    null_cast = _expression(
        {
            "kind": "cast",
            "value": {"kind": "literal", "value": "not-a-number"},
            "target_type": "float",
            "invalid": "null",
        }
    )
    assert _value(null_cast, {}) is None

    strict_mapping = _expression(
        {
            "kind": "terminology_map",
            "value": {"kind": "literal", "value": "UNKNOWN"},
            "mappings": {"M": "MALE"},
            "unmapped": "error",
        }
    )
    with pytest.raises(ProblemException) as captured:
        _value(strict_mapping, {})
    assert captured.value.code == "preview_terminology_unmapped"


def test_expression_codegen_uses_typed_runtime_functions() -> None:
    cast_expression = _expression(
        {
            "kind": "cast",
            "value": {"kind": "column", "dataset": "RAW", "column": "AGE"},
            "target_type": "integer",
            "invalid": "null",
        }
    )
    mapping_expression = _expression(
        {
            "kind": "terminology_map",
            "value": {"kind": "column", "dataset": "RAW", "column": "SEX"},
            "mappings": {"M": "MALE", "F": "FEMALE"},
            "unmapped": "preserve",
        }
    )

    assert "cast_value(" in _py_expr(cast_expression)
    assert "aur_cast(" in _r_expr(cast_expression)
    assert "input(cats(" in _sas_expr(cast_expression, "numeric")
    assert "terminology_value(" in _py_expr(mapping_expression)
    assert "aur_terminology_map(" in _r_expr(mapping_expression)
    assert _sas_expr(mapping_expression, "character").startswith("IFC(")


def test_sas_reports_unsupported_error_policies_before_publication() -> None:
    flow = DataflowIR.model_validate(
        {
            "nodes": [
                {"node_type": "read", "id": "read", "dataset": "RAW"},
                {
                    "node_type": "derive",
                    "id": "derive",
                    "assignments": {
                        "SEX": {
                            "kind": "terminology_map",
                            "value": {
                                "kind": "column",
                                "dataset": "RAW",
                                "column": "SEX",
                            },
                            "mappings": {"M": "MALE"},
                            "unmapped": "error",
                        }
                    },
                    "result_types": {"SEX": "character"},
                },
                {"node_type": "write", "id": "write", "dataset": "DM"},
            ],
            "edges": [
                {"source_node": "read", "target_node": "derive"},
                {"source_node": "derive", "target_node": "write"},
            ],
        }
    )

    with pytest.raises(BackendCapabilityMissing):
        compile_dataflow(flow, "sas")
