"""Raw physical-reader and initialization contract tests."""

import io
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.common.problems import ProblemException
from app.raw.files import inspect_file, preview_rows
from app.raw.routes import _latest_validation_run_response, _manifest_raw_revision
from app.validation.models import ValidationRun


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (4, 4),
        (0, 0),
        (None, None),
        ("4", None),
        (4.0, None),
        (True, None),
        (False, None),
    ],
)
def test_manifest_raw_revision_coercion(value: object, expected: int | None) -> None:
    """Only genuine integers survive; booleans and non-ints become ``None``."""

    assert _manifest_raw_revision(value) == expected


def _succeeded_raw_run(**manifest: object) -> ValidationRun:
    return ValidationRun(
        id=uuid4(),
        study_id=uuid4(),
        module_key="raw",
        owner_type="raw_workbench",
        owner_id=uuid4(),
        status="succeeded",
        validator_name="raw-physical-schema-validator",
        validator_version="1.0.0",
        input_fingerprint="f" * 64,
        input_manifest=dict(manifest),
        completed_at=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
    )


def test_latest_validation_run_response_pins_run_and_revision() -> None:
    run = _succeeded_raw_run(raw_revision=4)

    response = _latest_validation_run_response(run)

    assert response.validation_run_id == run.id
    assert response.raw_revision == 4
    assert response.completed_at == run.completed_at
    assert response.input_fingerprint == "f" * 64


def test_latest_validation_run_response_tolerates_missing_revision() -> None:
    run = _succeeded_raw_run()

    response = _latest_validation_run_response(run)

    assert response.validation_run_id == run.id
    assert response.raw_revision is None
