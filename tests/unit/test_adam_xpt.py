"""ADaM XPORT v5 generation is strict, deterministic, and read-back verified."""

import io

import pyreadstat
import pytest

from app.adam.contracts import AdamDataset
from app.adam.xpt import build_adam_xpt_v5
from app.common.problems import ProblemException


def _dataset() -> AdamDataset:
    return AdamDataset.model_validate(
        {
            "id": "10000000-0000-0000-0000-000000000001",
            "code": "ADSL",
            "label": "Subject-Level Analysis Dataset",
            "dataset_class": "SUBJECT LEVEL ANALYSIS DATASET",
            "structure": "One record per subject",
            "keys": ["USUBJID"],
            "sort_order": ["USUBJID"],
            "expected_output_name": "adsl.xpt",
            "variables": [
                {
                    "id": "20000000-0000-0000-0000-000000000001",
                    "name": "USUBJID",
                    "label": "Unique Subject Identifier",
                    "data_type": "character",
                    "length": 40,
                    "role": "Identifier",
                    "origin": {
                        "origin_type": "Predecessor",
                        "source_kind": "sdtm",
                        "source_dataset": "DM",
                        "source_variable": "USUBJID",
                    },
                    "output_node_id": "read_dm",
                },
                {
                    "id": "20000000-0000-0000-0000-000000000002",
                    "name": "TRT01P",
                    "label": "Planned Treatment for Period 01",
                    "data_type": "character",
                    "length": 20,
                    "role": "Treatment",
                    "origin": {"origin_type": "Assigned"},
                    "output_node_id": "derive_trt",
                },
            ],
        }
    )


def test_adam_xpt_is_deterministic_and_reads_back() -> None:
    data = b"USUBJID,TRT01P\n01,Placebo\n02,Active\n"

    first = build_adam_xpt_v5(data, _dataset())
    second = build_adam_xpt_v5(data, _dataset())
    frame, metadata = pyreadstat.read_xport(io.BytesIO(first.data))

    assert first.data == second.data
    assert metadata.table_name == "ADSL"
    assert metadata.variable_storage_width["USUBJID"] == 40
    assert frame.to_dict(orient="records") == [
        {"USUBJID": "01", "TRT01P": "Placebo"},
        {"USUBJID": "02", "TRT01P": "Active"},
    ]
    assert first.manifest["format_version"] == 5
    assert first.manifest["dataset"] == "ADSL"


def test_adam_xpt_rejects_columns_outside_the_specification() -> None:
    with pytest.raises(ProblemException) as captured:
        build_adam_xpt_v5(b"USUBJID,TRT01P,ARM\n01,Placebo,Placebo\n", _dataset())

    assert captured.value.code == "adam_output_schema_mismatch"
