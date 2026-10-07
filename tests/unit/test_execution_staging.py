"""Execution staging normalizes supported immutable tabular inputs."""

import io

import pytest
from openpyxl import Workbook

from app.execution.staging import tabular_csv_bytes


def test_json_input_is_staged_as_deterministic_csv() -> None:
    data = b'[{"SUBJID":"01","AGE":42},{"SUBJID":"02","AGE":null}]'
    assert tabular_csv_bytes(data, "demog.json") == b"SUBJID,AGE\n01,42\n02,\n"


def test_xlsx_input_is_staged_as_deterministic_csv() -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(("SUBJID", "AGE"))
    sheet.append(("01", 42))
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()

    assert tabular_csv_bytes(output.getvalue(), "demog.xlsx") == b"SUBJID,AGE\n01,42\n"


def test_staging_rejects_nested_json_values() -> None:
    with pytest.raises(ValueError, match="scalar"):
        tabular_csv_bytes(b'[{"SUBJID":{"value":"01"}}]', "demog.json")
