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


# --- Phase 2: function catalog conformance -----------------------------------


def _fn(name: str, *arguments: dict[str, object]) -> dict[str, object]:
    return {"kind": "function", "function": name, "arguments": list(arguments)}


def _parse_date(column: str) -> dict[str, object]:
    return _fn("parse_date", _column(column))


# Columns whose values are compared exactly (string/int/bool/date results).
_EXACT_ASSIGNMENTS: dict[str, dict[str, object]] = {
    "F_CONCAT": _fn("concat", _column("A"), _literal("-"), _column("B")),
    "F_SUBSTRING": _fn("substring", _column("A"), _literal(2), _literal(2)),
    "F_UPPER": _fn("upper", _column("A")),
    "F_LOWER": _fn("lower", _column("A")),
    "F_TRIM": _fn("trim", _column("PADDED")),
    "F_LENGTH": _fn("length", _column("A")),
    "F_CONTAINS": _fn("contains", _column("A"), _literal("b")),
    "F_STARTS": _fn("startswith", _column("A"), _literal("a")),
    "F_ENDS": _fn("endswith", _column("A"), _literal("c")),
    "F_REPLACE": _fn("replace", _column("A"), _literal("a"), _literal("Z")),
    "F_INDEX": _fn("index_of", _column("A"), _literal("b")),
    "F_SCAN": _fn("scan_token", _column("CSV"), _literal(2), _literal(",")),
    "F_PADL": _fn("pad_left", _column("NUMTXT"), _literal(4), _literal("0")),
    "F_PADR": _fn("pad_right", _column("NUMTXT"), _literal(4), _literal("x")),
    "F_COALESCE": _fn("coalesce", _column("MAYBE"), _literal("default")),
    "F_NULLIF": _fn("nullif", _column("A"), _literal("abc")),
    "F_ISIN": _fn("is_in", _column("A"), {"kind": "list_literal", "values": ["abc", "xyz"]}),
    "F_NMISS": _fn("n_missing", _column("A"), _column("MAYBE")),
    "F_NPRES": _fn("n_present", _column("A"), _column("MAYBE")),
    "F_FLOOR": _fn("floor", _column("NUM")),
    "F_CEIL": _fn("ceil", _column("NUM")),
    "F_MODULO": _fn("modulo", _column("INTNEG"), _literal(3)),
    "F_TRUNC": _fn("truncate", _column("NUM")),
    "F_PARSE_DATE": _parse_date("DTC"),
    "F_YEAR": _fn("year", _parse_date("DTC")),
    "F_MONTH": _fn("month", _parse_date("DTC")),
    "F_DAY": _fn("day", _parse_date("DTC")),
    "F_DIFFDAYS": _fn("date_diff_days", _parse_date("DTC"), _parse_date("REF")),
    "F_ADDDAYS": _fn("date_add_days", _parse_date("REF"), _literal(10)),
    "F_STUDYDAY": _fn("study_day", _parse_date("DTC"), _parse_date("REF")),
    "F_DIFFMONTHS": _fn("date_diff_months", _parse_date("DTC"), _parse_date("REF")),
    "F_HOUR": _fn("hour", _fn("parse_datetime", _column("DTM"))),
    "F_MINUTE": _fn("minute", _fn("parse_datetime", _column("DTM"))),
    "F_SECOND": _fn("second", _fn("parse_datetime", _column("DTM"))),
}

# Boolean-valued columns: Python serializes True/False, R serializes TRUE/FALSE;
# the underlying result is identical, so compare case-insensitively.
_BOOLEAN_COLUMNS = frozenset({"F_CONTAINS", "F_STARTS", "F_ENDS", "F_ISIN"})

# Columns whose numeric results compare within tolerance (float formatting differs).
_FLOAT_ASSIGNMENTS: dict[str, dict[str, object]] = {
    "F_ROUND": _fn("round", _column("NUM"), _literal(1)),
    "F_ABS": _fn("abs", _column("INTNEG")),
    "F_SAFEDIV": _fn("safe_divide", _column("NUM"), _column("DEN")),
    "F_MINOF": _fn("min_of", _column("NUM"), _column("INTNEG")),
    "F_MAXOF": _fn("max_of", _column("NUM"), _column("INTNEG")),
}


def _catalog_ir() -> DataflowIR:
    assignments = {**_EXACT_ASSIGNMENTS, **_FLOAT_ASSIGNMENTS}
    result_types = {name: "character" for name in _EXACT_ASSIGNMENTS}
    result_types.update({name: "numeric" for name in _FLOAT_ASSIGNMENTS})
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


def _catalog_rows() -> list[dict[str, str]]:
    return [
        {
            "A": "abc",
            "B": "DEF",
            "PADDED": "  hi  ",
            "CSV": "p,,q,r",
            "NUMTXT": "7",
            "MAYBE": "",
            "NUM": "2.45",
            "DEN": "0",
            "INTNEG": "-7",
            "DTC": "2021-03-10",
            "REF": "2021-01-15",
            "DTM": "2021-03-10T08:30:45",
        },
        {
            "A": "xyz",
            "B": "Ñ",
            "PADDED": "x",
            "CSV": "only",
            "NUMTXT": "123",
            "MAYBE": "present",
            "NUM": "-1.5",
            "DEN": "3",
            "INTNEG": "4",
            "DTC": "2020-12-31",
            "REF": "2021-01-01",
            "DTM": "2021-01-01T00:00:00",
        },
    ]


def test_function_catalog_python_and_r_agree(tmp_path: Path) -> None:
    ir = _catalog_ir()
    rows = _catalog_rows()

    python_workspace = tmp_path / "py"
    _stage_inputs(python_workspace, rows)
    python_rows = _run_python(ir, python_workspace)

    # Spot-check a few representative Python results so the fixture is anchored.
    assert _column_values(python_rows, "F_STUDYDAY") == ["55", "-1"]
    assert _column_values(python_rows, "F_PADL") == ["0007", "0123"]
    assert _column_values(python_rows, "F_SCAN") == ["q", ""]
    assert _column_values(python_rows, "F_PARSE_DATE") == ["2021-03-10", "2020-12-31"]
    assert _column_values(python_rows, "F_HOUR") == ["8", "0"]

    if _RSCRIPT is None:
        pytest.skip("Rscript is not on PATH")
    r_workspace = tmp_path / "r"
    _stage_inputs(r_workspace, rows)
    r_rows = _run_r(ir, r_workspace)

    for column in _EXACT_ASSIGNMENTS:
        python_column = _column_values(python_rows, column)
        r_column = _column_values(r_rows, column)
        if column in _BOOLEAN_COLUMNS:
            python_column = [value.lower() for value in python_column]
            r_column = [value.lower() for value in r_column]
        assert r_column == python_column, column

    for column in _FLOAT_ASSIGNMENTS:
        for py_value, r_value in zip(
            _column_values(python_rows, column),
            _column_values(r_rows, column),
            strict=True,
        ):
            if py_value == "" or r_value == "":
                assert py_value == r_value, column
            else:
                assert abs(float(py_value) - float(r_value)) <= 1e-9, column


def test_function_catalog_generates_sas_program() -> None:
    program = compile_dataflow(_catalog_ir(), "sas")
    assert "data work." in program.source
    assert program.compiler_version == "1.5.0"
