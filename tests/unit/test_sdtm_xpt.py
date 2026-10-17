"""SDTM XPORT v5 deterministic generation and conformance tests."""

import io

import pyreadstat
import pytest

from app.common.problems import ProblemException
from app.sdtm.contracts import SdtmDomain
from app.sdtm.xpt import build_xpt_v5, inspect_xpt_v5


def _domain() -> SdtmDomain:
    return SdtmDomain.model_validate(
        {
            "code": "DM",
            "label": "Demographics",
            "domain_class": "Special Purpose",
            "structure": "One record per subject",
            "keys": ["STUDYID", "USUBJID"],
            "sort_order": ["STUDYID", "USUBJID"],
            "expected_output_name": "dm.xpt",
            "variables": [
                {
                    "name": "STUDYID",
                    "label": "Study Identifier",
                    "data_type": "character",
                    "length": 20,
                    "role": "Identifier",
                    "core": "Req",
                    "origin": "Assigned",
                },
                {
                    "name": "USUBJID",
                    "label": "Unique Subject Identifier",
                    "data_type": "character",
                    "length": 40,
                    "role": "Identifier",
                    "core": "Req",
                    "origin": "Derived",
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


def test_xpt_v5_is_deterministic_and_reads_back_metadata() -> None:
    csv_data = b"STUDYID,USUBJID,AGE\nSYN-001,SYN-001-01,42\n"

    first = build_xpt_v5(csv_data, _domain())
    second = build_xpt_v5(csv_data, _domain())
    frame, metadata = pyreadstat.read_xport(io.BytesIO(first.data))

    assert first.data == second.data
    assert first.manifest["format_version"] == 5
    assert metadata.table_name == "DM"
    assert metadata.variable_storage_width["STUDYID"] == 20
    assert metadata.variable_storage_width["USUBJID"] == 40
    assert frame.to_dict(orient="records") == [
        {"STUDYID": "SYN-001", "USUBJID": "SYN-001-01", "AGE": 42.0}
    ]


def test_import_inspection_extracts_only_physical_xpt_metadata() -> None:
    product = build_xpt_v5(
        (b"STUDYID,USUBJID,AGE\nSYN-001,SYN-001-01,42\nSYN-001,SYN-001-02,38\n"),
        _domain(),
    )

    extracted = inspect_xpt_v5(product.data, "DM")

    assert extracted.domain_code == "DM"
    assert extracted.row_count == 2
    assert [variable.model_dump() for variable in extracted.variables] == [
        {
            "name": "STUDYID",
            "label": "Study Identifier",
            "data_type": "character",
            "length": 20,
            "ordinal": 1,
        },
        {
            "name": "USUBJID",
            "label": "Unique Subject Identifier",
            "data_type": "character",
            "length": 40,
            "ordinal": 2,
        },
        {
            "name": "AGE",
            "label": "Age",
            "data_type": "numeric",
            "length": None,
            "ordinal": 3,
        },
    ]


def test_import_inspection_rejects_wrong_domain_member() -> None:
    product = build_xpt_v5(b"STUDYID,USUBJID,AGE\n", _domain())

    with pytest.raises(ProblemException) as captured:
        inspect_xpt_v5(product.data, "SE")

    assert captured.value.code == "sdtm_import_domain_mismatch"


def test_import_inspection_rejects_xport_v8_header() -> None:
    product = build_xpt_v5(b"STUDYID,USUBJID,AGE\n", _domain())
    version_eight_header = product.data.replace(b"MEMBER  HEADER", b"MEMBV8  HEADER", 1)

    with pytest.raises(ProblemException) as captured:
        inspect_xpt_v5(version_eight_header, "DM")

    assert captured.value.code == "sdtm_import_xpt_version_unsupported"


def test_xpt_rejects_character_value_beyond_declared_length() -> None:
    csv_data = b"STUDYID,USUBJID,AGE\nSYN-001,SUBJECT-IDENTIFIER-THAT-IS-FAR-TOO-LONG-FOR-DM,42\n"

    with pytest.raises(ProblemException) as captured:
        build_xpt_v5(csv_data, _domain())

    assert captured.value.code == "sdtm_output_value_too_long"


def test_xpt_preserves_missing_character_and_numeric_values() -> None:
    csv_data = b"STUDYID,USUBJID,AGE\nSYN-001,,\n"

    product = build_xpt_v5(csv_data, _domain())
    frame, _ = pyreadstat.read_xport(io.BytesIO(product.data))
    rows = frame.astype(object).where(frame.notna(), None).to_dict(orient="records")

    assert rows == [{"STUDYID": "SYN-001", "USUBJID": "", "AGE": None}]


def test_xpt_supports_empty_dataset_with_declared_metadata() -> None:
    product = build_xpt_v5(b"STUDYID,USUBJID,AGE\n", _domain())
    frame, metadata = pyreadstat.read_xport(io.BytesIO(product.data))

    assert frame.empty
    assert metadata.number_rows == 0
    assert metadata.column_names == ["STUDYID", "USUBJID", "AGE"]
    assert metadata.variable_storage_width["STUDYID"] == 20
    assert metadata.variable_storage_width["USUBJID"] == 40
    assert product.manifest["row_count"] == 0
