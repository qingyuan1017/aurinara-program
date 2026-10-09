"""Execution staging normalizes supported immutable tabular inputs."""

import io

import pytest
from openpyxl import Workbook

from app.execution.staging import tabular_csv_bytes
from app.sdtm.contracts import SdtmDomain
from app.sdtm.xpt import build_xpt_v5


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


def test_xpt_input_is_staged_as_deterministic_csv() -> None:
    domain = SdtmDomain.model_validate(
        {
            "code": "DM",
            "label": "Demographics",
            "domain_class": "Special Purpose",
            "structure": "One record per subject",
            "keys": ["USUBJID"],
            "sort_order": ["USUBJID"],
            "expected_output_name": "dm.xpt",
            "variables": [
                {
                    "name": "USUBJID",
                    "label": "Unique Subject Identifier",
                    "data_type": "character",
                    "length": 40,
                    "role": "Identifier",
                    "core": "Req",
                    "origin": "Assigned",
                },
                {
                    "name": "AGE",
                    "label": "Age",
                    "data_type": "numeric",
                    "role": "Topic",
                    "core": "Perm",
                    "origin": "Collected",
                },
            ],
        }
    )
    product = build_xpt_v5(b"USUBJID,AGE\n01,42\n02,\n", domain)

    assert tabular_csv_bytes(product.data, "dm.xpt") == b"USUBJID,AGE\n01,42.0\n02,\n"
