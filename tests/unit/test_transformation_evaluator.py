"""Bounded normalized-IR preview evaluation tests."""

import pytest

from app.common.problems import ProblemException
from app.transformation.contracts import DataflowIR
from app.transformation.evaluator import evaluate_dataflow


def test_evaluator_uses_typed_operators_and_declared_write() -> None:
    ir = DataflowIR.model_validate(
        {
            "nodes": [
                {"node_type": "read", "id": "read", "dataset": "DEMOG"},
                {
                    "node_type": "filter",
                    "id": "adult",
                    "predicate": {
                        "kind": "binary",
                        "operator": "ge",
                        "left": {"kind": "column", "dataset": "DEMOG", "column": "AGE"},
                        "right": {"kind": "literal", "value": 18},
                    },
                },
                {
                    "node_type": "derive",
                    "id": "derive",
                    "assignments": {
                        "STUDYID": {"kind": "literal", "value": "SYN-001"},
                        "USUBJID": {
                            "kind": "column",
                            "dataset": "DEMOG",
                            "column": "SUBJID",
                        },
                    },
                },
                {"node_type": "write", "id": "write", "dataset": "DM"},
            ],
            "edges": [
                {"source_node": "read", "target_node": "adult"},
                {"source_node": "adult", "target_node": "derive"},
                {"source_node": "derive", "target_node": "write"},
            ],
        }
    )

    outputs = evaluate_dataflow(
        ir,
        {"DEMOG": ({"SUBJID": "01", "AGE": 17}, {"SUBJID": "02", "AGE": 42})},
    )

    assert outputs["DM"] == ({"SUBJID": "02", "AGE": 42, "STUDYID": "SYN-001", "USUBJID": "02"},)


def test_evaluator_uses_explicit_assignment_order_after_mapping_reorder() -> None:
    ir = DataflowIR.model_validate(
        {
            "nodes": [
                {"node_type": "read", "id": "read", "dataset": "RAW"},
                {
                    "node_type": "derive",
                    "id": "derive",
                    # Simulate JSONB returning the dependent target first.
                    "assignments": {
                        "SUBJID": {"kind": "column", "dataset": "DM", "column": "SITEID"},
                        "SITEID": {"kind": "literal", "value": "101"},
                    },
                    "assignment_order": ["SITEID", "SUBJID"],
                },
                {"node_type": "write", "id": "write", "dataset": "DM"},
            ],
            "edges": [
                {"source_node": "read", "target_node": "derive"},
                {"source_node": "derive", "target_node": "write"},
            ],
        }
    )

    assert evaluate_dataflow(ir, {"RAW": ({},)})["DM"] == (
        {"SITEID": "101", "SUBJID": "101"},
    )


def test_evaluator_rejects_missing_selected_dataset() -> None:
    ir = DataflowIR.model_validate(
        {"nodes": [{"node_type": "read", "id": "read", "dataset": "MISSING"}]}
    )

    with pytest.raises(ProblemException) as captured:
        evaluate_dataflow(ir, {})

    assert captured.value.code == "preview_dataset_unknown"


def test_evaluator_joins_maps_pivots_and_aggregates() -> None:
    ir = DataflowIR.model_validate(
        {
            "nodes": [
                {"node_type": "read", "id": "subjects", "dataset": "SUBJECTS"},
                {"node_type": "read", "id": "sites", "dataset": "SITES"},
                {
                    "node_type": "join",
                    "id": "joined",
                    "join_type": "left",
                    "left_input": "subjects",
                    "right_input": "sites",
                    "keys": [["SITEID", "SITEID"]],
                },
                {
                    "node_type": "terminology_map",
                    "id": "mapped",
                    "source_column": "SEX",
                    "target_column": "SEXDEC",
                    "mappings": {"M": "Male", "F": "Female"},
                },
                {
                    "node_type": "cast",
                    "id": "cast_values",
                    "casts": {
                        "V1": {"source_column": "V1", "target_type": "float"},
                        "V2": {"source_column": "V2", "target_type": "float"},
                    },
                },
                {
                    "node_type": "pivot_longer",
                    "id": "long",
                    "id_columns": ["SITEID", "SEXDEC"],
                    "value_columns": ["V1", "V2"],
                    "name_column": "VISIT",
                    "value_column": "VALUE",
                },
                {
                    "node_type": "sequence",
                    "id": "sequenced",
                    "group_by": ["SEXDEC"],
                    "order_by": ["VISIT"],
                    "target_column": "SEQ",
                },
                {
                    "node_type": "aggregate",
                    "id": "summary",
                    "group_by": ["SEXDEC"],
                    "aggregations": {
                        "N": {"operation": "count"},
                        "TOTAL": {"operation": "sum", "column": "VALUE"},
                        "MEAN": {"operation": "mean", "column": "VALUE"},
                    },
                },
                {"node_type": "sort", "id": "sorted", "keys": ["SEXDEC"]},
                {"node_type": "write", "id": "write", "dataset": "SUMMARY"},
            ],
            "edges": [
                {"source_node": "subjects", "target_node": "joined"},
                {"source_node": "sites", "target_node": "joined"},
                {"source_node": "joined", "target_node": "cast_values"},
                {"source_node": "cast_values", "target_node": "mapped"},
                {"source_node": "mapped", "target_node": "long"},
                {"source_node": "long", "target_node": "sequenced"},
                {"source_node": "sequenced", "target_node": "summary"},
                {"source_node": "summary", "target_node": "sorted"},
                {"source_node": "sorted", "target_node": "write"},
            ],
        }
    )

    outputs = evaluate_dataflow(
        ir,
        {
            "SUBJECTS": (
                {"SITEID": "A", "SEX": "M", "V1": 10, "V2": 20},
                {"SITEID": "B", "SEX": "F", "V1": 4, "V2": 8},
            ),
            "SITES": ({"SITEID": "A", "COUNTRY": "US"},),
        },
    )

    assert outputs["SUMMARY"] == (
        {"SEXDEC": "Female", "N": 2, "TOTAL": 12.0, "MEAN": 6.0},
        {"SEXDEC": "Male", "N": 2, "TOTAL": 30.0, "MEAN": 15.0},
    )


def test_evaluator_applies_partitioned_window_operations() -> None:
    ir = DataflowIR.model_validate(
        {
            "nodes": [
                {"node_type": "read", "id": "read", "dataset": "VALUES"},
                {
                    "node_type": "window",
                    "id": "windowed",
                    "partition_by": ["GROUP"],
                    "order_by": ["ORDER"],
                    "operations": {
                        "ROW_NUMBER": {"operation": "row_number"},
                        "PREVIOUS": {
                            "operation": "lag",
                            "source_column": "VALUE",
                        },
                        "RUNNING": {
                            "operation": "cumulative_sum",
                            "source_column": "VALUE",
                        },
                    },
                },
                {"node_type": "write", "id": "write", "dataset": "RESULT"},
            ],
            "edges": [
                {"source_node": "read", "target_node": "windowed"},
                {"source_node": "windowed", "target_node": "write"},
            ],
        }
    )

    outputs = evaluate_dataflow(
        ir,
        {
            "VALUES": (
                {"GROUP": "A", "ORDER": 2, "VALUE": 4},
                {"GROUP": "B", "ORDER": 1, "VALUE": 3},
                {"GROUP": "A", "ORDER": 1, "VALUE": 2},
            )
        },
    )

    assert outputs["RESULT"] == (
        {
            "GROUP": "A",
            "ORDER": 1,
            "VALUE": 2,
            "ROW_NUMBER": 1,
            "PREVIOUS": None,
            "RUNNING": 2.0,
        },
        {
            "GROUP": "A",
            "ORDER": 2,
            "VALUE": 4,
            "ROW_NUMBER": 2,
            "PREVIOUS": 2,
            "RUNNING": 6.0,
        },
        {
            "GROUP": "B",
            "ORDER": 1,
            "VALUE": 3,
            "ROW_NUMBER": 1,
            "PREVIOUS": None,
            "RUNNING": 3.0,
        },
    )
