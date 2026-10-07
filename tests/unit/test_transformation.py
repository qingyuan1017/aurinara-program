"""Internal IR safety, canonicalization, lineage, and compiler tests."""

import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.transformation.contracts import DataflowIR
from app.transformation.service import (
    BackendCapabilityMissing,
    compile_dataflow,
    ir_fingerprint,
    lineage,
)


def _flow() -> DataflowIR:
    return DataflowIR.model_validate(
        {
            "nodes": [
                {"node_type": "write", "id": "write_dm", "dataset": "DM"},
                {"node_type": "read", "id": "read_raw", "dataset": "DEMOG"},
                {"node_type": "select", "id": "select_vars", "columns": ["SUBJID"]},
            ],
            "edges": [
                {"source_node": "read_raw", "target_node": "select_vars"},
                {"source_node": "select_vars", "target_node": "write_dm"},
            ],
        }
    )


def _advanced_flow() -> DataflowIR:
    return DataflowIR.model_validate(
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
                    "id_columns": ["SEXDEC"],
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
                    "node_type": "window",
                    "id": "windowed",
                    "partition_by": ["SEXDEC"],
                    "order_by": ["VISIT"],
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
                {
                    "node_type": "aggregate",
                    "id": "summary",
                    "group_by": ["SEXDEC"],
                    "aggregations": {
                        "N": {"operation": "count"},
                        "TOTAL": {"operation": "sum", "column": "VALUE"},
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
                {"source_node": "sequenced", "target_node": "windowed"},
                {"source_node": "windowed", "target_node": "summary"},
                {"source_node": "summary", "target_node": "sorted"},
                {"source_node": "sorted", "target_node": "write"},
            ],
        }
    )


def test_ir_is_canonical_and_tracks_lineage() -> None:
    flow = _flow()
    assert len(ir_fingerprint(flow)) == 64
    assert lineage(flow) == {"DM": ("read_raw", "select_vars")}
    assert compile_dataflow(flow, "python").source == compile_dataflow(flow, "python").source


def test_ir_rejects_cycles_and_raw_code_fields() -> None:
    with pytest.raises(ValidationError):
        DataflowIR.model_validate(
            {
                "nodes": [
                    {"node_type": "read", "id": "a", "dataset": "A", "python": "evil()"},
                    {"node_type": "write", "id": "b", "dataset": "B"},
                ],
                "edges": [
                    {"source_node": "a", "target_node": "b"},
                    {"source_node": "b", "target_node": "a"},
                ],
            }
        )


def test_backend_capability_missing_precedes_publication() -> None:
    flow = DataflowIR.model_validate(
        {
            "nodes": [
                {
                    "node_type": "aggregate",
                    "id": "summary",
                    "group_by": [],
                    "aggregations": {"n": {"operation": "count"}},
                }
            ]
        }
    )
    with pytest.raises(BackendCapabilityMissing):
        compile_dataflow(flow, "sas")


def test_generated_python_program_runs_over_staged_csv(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    inputs.mkdir()
    with (inputs / "DEMOG.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["SUBJID", "AGE"])
        writer.writeheader()
        writer.writerow({"SUBJID": "01", "AGE": "42"})
    program = tmp_path / "program.py"
    program.write_text(compile_dataflow(_flow(), "python").source, encoding="utf-8")
    environment = {**os.environ, "AURINARA_WORKSPACE": str(tmp_path)}

    completed = subprocess.run(
        [sys.executable, "-I", str(program)],
        check=False,
        capture_output=True,
        env=environment,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr.decode()
    assert (outputs / "DM.csv").read_text(encoding="utf-8") == "SUBJID\n01\n"


def test_generated_python_program_runs_advanced_operators(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    inputs.mkdir()
    for name, rows in {
        "SUBJECTS": [
            {"SITEID": "A", "SEX": "M", "V1": "10", "V2": "20"},
            {"SITEID": "B", "SEX": "F", "V1": "4", "V2": "8"},
        ],
        "SITES": [{"SITEID": "A", "COUNTRY": "US"}],
    }.items():
        with (inputs / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    program = tmp_path / "program.py"
    program.write_text(compile_dataflow(_advanced_flow(), "python").source, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-I", str(program)],
        check=False,
        capture_output=True,
        env={**os.environ, "AURINARA_WORKSPACE": str(tmp_path)},
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr.decode()
    with (outputs / "SUMMARY.csv").open(encoding="utf-8", newline="") as stream:
        assert list(csv.DictReader(stream)) == [
            {"SEXDEC": "Female", "N": "2", "TOTAL": "12.0"},
            {"SEXDEC": "Male", "N": "2", "TOTAL": "30.0"},
        ]
