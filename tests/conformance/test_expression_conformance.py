"""Cross-language conformance for the conditional expression kind.

Compiles a conditional-derive Dataflow IR to Python and R, executes both in a
temporary workspace, and compares normalized outputs. R assertions are guarded
behind ``shutil.which("Rscript")`` but, when R is present, a Python-vs-R
mismatch fails the test rather than being skipped. SAS is non-failing: the test
asserts the SAS program is generated when result types are present and that
``BackendCapabilityMissing`` is the only reason it is withheld when absent.
"""

import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.transformation.contracts import DataflowIR
from app.transformation.service import BackendCapabilityMissing, compile_dataflow

_RSCRIPT = shutil.which("Rscript")


def _binary(operator: str, left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    return {"kind": "binary", "operator": operator, "left": left, "right": right}


def _column(name: str) -> dict[str, object]:
    return {"kind": "column", "dataset": "src", "column": name}


def _literal(value: object) -> dict[str, object]:
    return {"kind": "literal", "value": value}


def _ittfl_expression() -> dict[str, object]:
    return {
        "kind": "conditional",
        "branches": [
            {
                "when": _binary(
                    "and",
                    _binary("eq", _column("SAFFL"), _literal("Y")),
                    _binary("eq", _column("RANDFL"), _literal("Y")),
                ),
                "then": _literal("Y"),
            }
        ],
        "otherwise": _literal(None),
    }


def _short_circuit_expression() -> dict[str, object]:
    """A matched first branch must hide a later divide-by-zero (D1 + short-circuit)."""

    return {
        "kind": "conditional",
        "branches": [
            {
                "when": _binary("eq", _column("GRP"), _literal("safe")),
                "then": _literal("OK"),
            },
            {
                "when": _literal(True),
                "then": _binary("div", _literal(1), _literal(0)),
            },
        ],
        "otherwise": _literal(None),
    }


def _conditional_ir(assignments: dict[str, object], result_types: dict[str, str]) -> DataflowIR:
    return DataflowIR.model_validate(
        {
            "nodes": [
                {"node_type": "read", "id": "read", "dataset": "src"},
                {
                    "node_type": "derive",
                    "id": "derive",
                    "assignments": assignments,
                    "result_types": result_types,
                },
                {"node_type": "write", "id": "write", "dataset": "out"},
            ],
            "edges": [
                {"source_node": "read", "target_node": "derive"},
                {"source_node": "derive", "target_node": "write"},
            ],
        }
    )


def _stage_inputs(workspace: Path, rows: list[dict[str, str]]) -> None:
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (inputs / "src.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (workspace / "outputs").mkdir(parents=True, exist_ok=True)


def _read_output(workspace: Path) -> list[dict[str, str]]:
    with (workspace / "outputs" / "out.csv").open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _normalize(value: str | None) -> str:
    return "" if value is None else value


def _run_python(ir: DataflowIR, workspace: Path) -> list[dict[str, str]]:
    program = workspace / "program.py"
    program.write_text(compile_dataflow(ir, "python").source, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-I", str(program)],
        check=False,
        capture_output=True,
        env={**os.environ, "AURINARA_WORKSPACE": str(workspace)},
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    return _read_output(workspace)


def _run_r(ir: DataflowIR, workspace: Path) -> list[dict[str, str]]:
    assert _RSCRIPT is not None
    program = workspace / "program.R"
    program.write_text(compile_dataflow(ir, "r").source, encoding="utf-8")
    completed = subprocess.run(
        [_RSCRIPT, "--vanilla", str(program)],
        check=False,
        capture_output=True,
        env={**os.environ, "AURINARA_WORKSPACE": str(workspace)},
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    return _read_output(workspace)


def _column_values(rows: list[dict[str, str]], column: str) -> list[str]:
    return [_normalize(row.get(column)) for row in rows]


def test_ittfl_python_and_r_agree(tmp_path: Path) -> None:
    ir = _conditional_ir({"ITTFL": _ittfl_expression()}, {"ITTFL": "character"})
    rows = [
        {"SUBJID": "01", "SAFFL": "Y", "RANDFL": "Y"},
        {"SUBJID": "02", "SAFFL": "Y", "RANDFL": "N"},
        {"SUBJID": "03", "SAFFL": "", "RANDFL": "Y"},
        {"SUBJID": "04", "SAFFL": "Ñ", "RANDFL": "Ñ"},
    ]

    python_workspace = tmp_path / "py"
    _stage_inputs(python_workspace, rows)
    python_rows = _run_python(ir, python_workspace)
    assert _column_values(python_rows, "ITTFL") == ["Y", "", "", ""]

    if _RSCRIPT is None:
        pytest.skip("Rscript is not on PATH")
    r_workspace = tmp_path / "r"
    _stage_inputs(r_workspace, rows)
    r_rows = _run_r(ir, r_workspace)
    assert _column_values(r_rows, "ITTFL") == _column_values(python_rows, "ITTFL")


def test_short_circuit_division_resolves_to_null(tmp_path: Path) -> None:
    ir = _conditional_ir({"FLAG": _short_circuit_expression()}, {"FLAG": "character"})
    rows = [
        {"SUBJID": "01", "GRP": "safe"},
        {"SUBJID": "02", "GRP": "other"},
    ]

    python_workspace = tmp_path / "py"
    _stage_inputs(python_workspace, rows)
    python_rows = _run_python(ir, python_workspace)
    # Row 1 matches first branch; row 2 falls into the div-by-zero branch -> null (D1).
    assert _column_values(python_rows, "FLAG") == ["OK", ""]

    if _RSCRIPT is None:
        pytest.skip("Rscript is not on PATH")
    r_workspace = tmp_path / "r"
    _stage_inputs(r_workspace, rows)
    r_rows = _run_r(ir, r_workspace)
    assert _column_values(r_rows, "FLAG") == _column_values(python_rows, "FLAG")


def test_null_when_falls_through_to_otherwise(tmp_path: Path) -> None:
    expression = {
        "kind": "conditional",
        "branches": [
            {
                "when": _binary("eq", _column("MISS"), _literal("Y")),
                "then": _literal("HIT"),
            }
        ],
        "otherwise": _literal("ELSE"),
    }
    ir = _conditional_ir({"RES": expression}, {"RES": "character"})
    rows = [{"SUBJID": "01", "MISS": ""}, {"SUBJID": "02", "MISS": "Y"}]

    python_workspace = tmp_path / "py"
    _stage_inputs(python_workspace, rows)
    python_rows = _run_python(ir, python_workspace)
    assert _column_values(python_rows, "RES") == ["ELSE", "HIT"]

    if _RSCRIPT is None:
        pytest.skip("Rscript is not on PATH")
    r_workspace = tmp_path / "r"
    _stage_inputs(r_workspace, rows)
    r_rows = _run_r(ir, r_workspace)
    assert _column_values(r_rows, "RES") == _column_values(python_rows, "RES")


def test_sas_generated_with_result_types_and_missing_without() -> None:
    with_types = _conditional_ir({"ITTFL": _ittfl_expression()}, {"ITTFL": "character"})
    program = compile_dataflow(with_types, "sas")
    assert "IFC(" in program.source

    without_types = _conditional_ir({"ITTFL": _ittfl_expression()}, {})
    with pytest.raises(BackendCapabilityMissing):
        compile_dataflow(without_types, "sas")
