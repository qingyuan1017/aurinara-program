"""Raw physical-reader and initialization contract tests."""

import io

import pytest

from app.common.problems import ProblemException
from app.raw.files import inspect_file, preview_rows


def test_csv_inspection_and_bounded_preview() -> None:
    data = b"SUBJID,AGE,ACTIVE\n01,42,true\n02,38,false\n"
    snapshot = inspect_file(io.BytesIO(data), "subjects.csv")
    assert [column.name for column in snapshot.columns] == ["SUBJID", "AGE", "ACTIVE"]
    assert snapshot.columns[1].physical_type == "integer"
    columns, rows, total = preview_rows(io.BytesIO(data), "subjects.csv", ("SUBJID", "AGE"), 1, 1)
    assert columns == ("SUBJID", "AGE")
    assert rows == ({"SUBJID": "02", "AGE": "38"},)
    assert total == 2


def test_nested_json_is_rejected() -> None:
    with pytest.raises(ProblemException) as captured:
        inspect_file(io.BytesIO(b'[{"id":"01","nested":{"x":1}}]'), "data.json")
    assert captured.value.code == "raw_json_shape_invalid"
