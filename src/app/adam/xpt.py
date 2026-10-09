"""Deterministic ADaM XPORT v5 generation with independent read-back verification."""

import csv
import hashlib
import io
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pandas as pd
import pyreadstat

from app.adam.contracts import AdamDataset
from app.common.problems import ProblemException

_XPT_TIMESTAMP = re.compile(rb"[0-9]{2}[A-Z]{3}[0-9]{2}:[0-9]{2}:[0-9]{2}:[0-9]{2}")
_NORMALIZED_TIMESTAMP = b"01JAN70:00:00:00"
_OBS_HEADER = b"HEADER RECORD*******OBS     HEADER RECORD!!!!!!!"


@dataclass(frozen=True, slots=True)
class AdamXptProduct:
    data: bytes
    manifest: dict[str, object]


def _problem(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=422,
        code=code,
        title="ADaM XPT generation failed",
        detail=detail,
    )


def _rows(csv_data: bytes) -> tuple[list[str], list[dict[str, str | None]]]:
    try:
        reader = csv.DictReader(io.StringIO(csv_data.decode("utf-8-sig")))
        headers = list(reader.fieldnames or [])
        rows = []
        for row in reader:
            if None in row:
                raise _problem("adam_output_csv_invalid", "Execution rows have too many values.")
            rows.append(cast(dict[str, str | None], dict(row)))
    except (UnicodeError, csv.Error) as error:
        raise _problem(
            "adam_output_csv_invalid", "Execution output is not valid UTF-8 CSV."
        ) from error
    if not headers or len(headers) != len(set(headers)):
        raise _problem("adam_output_csv_invalid", "Output columns must be present and unique.")
    return headers, rows


def _dataframe(
    csv_data: bytes, dataset: AdamDataset
) -> tuple[pd.DataFrame, list[dict[str, object]], list[tuple[int, str]]]:
    headers, rows = _rows(csv_data)
    expected = [variable.name for variable in dataset.variables]
    missing = [name for name in expected if name not in headers]
    unexpected = [name for name in headers if name not in expected]
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        raise _problem(
            "adam_output_schema_mismatch",
            f"Dataset '{dataset.code}' output columns do not match ({'; '.join(details)}).",
        )
    normalized_rows: list[dict[str, object]] = []
    missing_characters: list[tuple[int, str]] = []
    for row_index, row in enumerate(rows, start=1):
        normalized: dict[str, object] = {}
        for variable in dataset.variables:
            value = row.get(variable.name)
            if value == "":
                value = None
            if variable.data_type == "numeric":
                try:
                    normalized[variable.name] = None if value is None else float(value)
                except ValueError as error:
                    raise _problem(
                        "adam_output_numeric_invalid",
                        f"{dataset.code}.{variable.name} row {row_index} is not numeric.",
                    ) from error
            else:
                length = variable.length
                if length is None:
                    raise _problem(
                        "adam_character_length_required",
                        f"{dataset.code}.{variable.name} requires a character length.",
                    )
                text = None if value is None else str(value)
                if text is not None and len(text) > length:
                    raise _problem(
                        "adam_output_value_too_long",
                        f"{dataset.code}.{variable.name} row {row_index} exceeds length {length}.",
                    )
                if text is not None:
                    try:
                        text.encode("latin-1")
                    except UnicodeEncodeError as error:
                        raise _problem(
                            "xpt_character_encoding_unsupported",
                            f"{dataset.code}.{variable.name} contains a character outside Latin-1.",
                        ) from error
                normalized[variable.name] = text
        normalized_rows.append(normalized)

    columns: dict[str, pd.Series] = {}
    for variable in dataset.variables:
        values = [row[variable.name] for row in normalized_rows]
        if variable.data_type == "numeric":
            columns[variable.name] = pd.Series(values or [0.0], dtype="float64")
        else:
            length = variable.length or 1
            padded: list[str] = []
            for row_index, cell in enumerate(values):
                if isinstance(cell, str):
                    padded.append(cell.ljust(length))
                else:
                    padded.append("~" * length)
                    missing_characters.append((row_index, variable.name))
            if not padded:
                padded.append("~" * length)
            columns[variable.name] = pd.Series(padded, dtype="object")
    return pd.DataFrame(columns, columns=expected), normalized_rows, missing_characters


def _restore_character_missing_values(
    data: bytes, dataset: AdamDataset, missing: list[tuple[int, str]]
) -> bytes:
    if not missing:
        return data
    header_index = data.find(_OBS_HEADER)
    if header_index < 0:
        raise _problem("xpt_observation_header_missing", "XPT observation header is missing.")
    observation_start = header_index + 80
    offsets: dict[str, tuple[int, int]] = {}
    record_length = 0
    for variable in dataset.variables:
        width = variable.length if variable.data_type == "character" else 8
        if width is None:
            raise _problem(
                "adam_character_length_required",
                f"{dataset.code}.{variable.name} requires a character length.",
            )
        offsets[variable.name] = (record_length, width)
        record_length += width
    restored = bytearray(data)
    for row_index, variable_name in missing:
        offset, width = offsets[variable_name]
        start = observation_start + row_index * record_length + offset
        restored[start : start + width] = b" " * width
    return bytes(restored)


def build_adam_xpt_v5(csv_data: bytes, dataset: AdamDataset) -> AdamXptProduct:
    """Write deterministic ADaM XPT v5 bytes and verify metadata and values."""

    frame, expected_rows, missing_characters = _dataframe(csv_data, dataset)
    labels: dict[str, str | None] = {
        variable.name: variable.label for variable in dataset.variables
    }
    formats = {
        variable.name: (f"${variable.length}." if variable.data_type == "character" else "8.")
        for variable in dataset.variables
    }
    with tempfile.TemporaryDirectory(prefix="aurinara-adam-xpt-") as temporary:
        path = Path(temporary) / dataset.expected_output_name
        pyreadstat.write_xport(
            frame,
            path,
            file_label=dataset.label,
            column_labels=labels,
            table_name=dataset.code,
            file_format_version=5,
            variable_format=formats,
        )
        data = _XPT_TIMESTAMP.sub(_NORMALIZED_TIMESTAMP, path.read_bytes())
        if expected_rows:
            data = _restore_character_missing_values(data, dataset, missing_characters)
        else:
            header_index = data.find(_OBS_HEADER)
            if header_index < 0:
                raise _problem(
                    "xpt_observation_header_missing", "XPT observation header is missing."
                )
            data = data[: header_index + 80]
    observed, metadata = pyreadstat.read_xport(io.BytesIO(data), output_format="pandas")
    names = [variable.name for variable in dataset.variables]
    if metadata.table_name != dataset.code or list(metadata.column_names) != names:
        raise _problem(
            "adam_xpt_readback_metadata_mismatch", "XPT table or variable names changed."
        )
    if list(metadata.column_labels) != [labels[name] for name in names]:
        raise _problem("adam_xpt_readback_label_mismatch", "XPT labels changed on read-back.")
    if metadata.number_rows != len(expected_rows):
        raise _problem("adam_xpt_readback_row_count_mismatch", "XPT row count changed.")
    for variable in dataset.variables:
        observed_type = metadata.readstat_variable_types[variable.name]
        expected_type = "string" if variable.data_type == "character" else "double"
        if observed_type != expected_type:
            raise _problem(
                "adam_xpt_readback_type_mismatch",
                f"{dataset.code}.{variable.name} read back as {observed_type}.",
            )
        if (
            variable.data_type == "character"
            and metadata.variable_storage_width[variable.name] != variable.length
        ):
            raise _problem(
                "adam_xpt_readback_length_mismatch",
                f"{dataset.code}.{variable.name} storage width changed.",
            )
    raw_rows = observed.astype(object).where(pd.notna(observed), None).to_dict(orient="records")
    observed_rows = [
        {name: None if value == "" else value for name, value in row.items()} for row in raw_rows
    ]
    if observed_rows != expected_rows:
        raise _problem("adam_xpt_readback_value_mismatch", "XPT values changed on read-back.")
    return AdamXptProduct(
        data=data,
        manifest={
            "schema_version": "1.0.0",
            "format": "SAS XPORT",
            "format_version": 5,
            "dataset": dataset.code,
            "label": dataset.label,
            "row_count": len(expected_rows),
            "variables": [
                {
                    "name": variable.name,
                    "label": variable.label,
                    "data_type": variable.data_type,
                    "length": variable.length,
                    "origin": variable.origin.model_dump(mode="json"),
                    "method_id": variable.method_id,
                }
                for variable in dataset.variables
            ],
            "header_timestamps_normalized_to": "1970-01-01T00:00:00Z",
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )
