"""Deterministic XPORT v5 generation and independent read-back verification."""

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

from app.common.problems import ProblemException
from app.sdtm.contracts import SdtmDomain

_XPT_TIMESTAMP = re.compile(rb"[0-9]{2}[A-Z]{3}[0-9]{2}:[0-9]{2}:[0-9]{2}:[0-9]{2}")
_NORMALIZED_TIMESTAMP = b"01JAN70:00:00:00"
_OBS_HEADER = b"HEADER RECORD*******OBS     HEADER RECORD!!!!!!!"


@dataclass(frozen=True, slots=True)
class XptProduct:
    data: bytes
    manifest: dict[str, object]


def _problem(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=422,
        code=code,
        title="SDTM XPT generation failed",
        detail=detail,
    )


def _rows(csv_data: bytes) -> tuple[list[str], list[dict[str, str | None]]]:
    try:
        reader = csv.DictReader(io.StringIO(csv_data.decode("utf-8-sig")))
        headers = list(reader.fieldnames or [])
        rows = []
        for row in reader:
            if None in row:
                raise _problem(
                    "sdtm_output_csv_invalid", "Execution output rows have too many values."
                )
            rows.append(cast(dict[str, str | None], dict(row)))
    except (UnicodeError, csv.Error) as error:
        raise _problem(
            "sdtm_output_csv_invalid", "Execution output is not valid UTF-8 CSV."
        ) from error
    if not headers or len(headers) != len(set(headers)):
        raise _problem(
            "sdtm_output_csv_invalid", "Execution output columns must be present and unique."
        )
    return headers, rows


def _dataframe(
    csv_data: bytes, domain: SdtmDomain
) -> tuple[pd.DataFrame, list[dict[str, object]], list[tuple[int, str]]]:
    headers, rows = _rows(csv_data)
    expected = [variable.name for variable in domain.variables]
    missing = [name for name in expected if name not in headers]
    if missing:
        raise _problem(
            "sdtm_output_variable_missing",
            f"Domain '{domain.code}' is missing variables: {', '.join(missing)}.",
        )
    columns: dict[str, pd.Series] = {}
    normalized_rows: list[dict[str, object]] = []
    missing_characters: list[tuple[int, str]] = []
    for row_index, row in enumerate(rows, start=1):
        normalized: dict[str, object] = {}
        for variable in domain.variables:
            value = row.get(variable.name)
            if value == "":
                value = None
            if variable.data_type == "numeric":
                try:
                    normalized[variable.name] = None if value is None else float(value)
                except ValueError as error:
                    raise _problem(
                        "sdtm_output_numeric_invalid",
                        f"{domain.code}.{variable.name} row {row_index} is not numeric.",
                    ) from error
            else:
                text = None if value is None else str(value)
                length = variable.length
                if length is None:
                    raise _problem(
                        "sdtm_character_length_required",
                        f"{domain.code}.{variable.name} requires a declared character length.",
                    )
                if text is not None and len(text) > length:
                    raise _problem(
                        "sdtm_output_value_too_long",
                        f"{domain.code}.{variable.name} row {row_index} exceeds length {length}.",
                    )
                if text is not None:
                    try:
                        text.encode("latin-1")
                    except UnicodeEncodeError as error:
                        raise _problem(
                            "xpt_character_encoding_unsupported",
                            f"{domain.code}.{variable.name} contains a character outside Latin-1.",
                        ) from error
                normalized[variable.name] = text
        normalized_rows.append(normalized)
    for variable in domain.variables:
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
    data: bytes, domain: SdtmDomain, missing: list[tuple[int, str]]
) -> bytes:
    if not missing:
        return data
    header_index = data.find(_OBS_HEADER)
    if header_index < 0:
        raise _problem("xpt_observation_header_missing", "XPT observation header is missing.")
    observation_start = header_index + 80
    offsets: dict[str, tuple[int, int]] = {}
    record_length = 0
    for variable in domain.variables:
        width = variable.length if variable.data_type == "character" else 8
        if width is None:
            raise _problem(
                "sdtm_character_length_required",
                f"{domain.code}.{variable.name} requires a declared character length.",
            )
        offsets[variable.name] = (record_length, width)
        record_length += width
    restored = bytearray(data)
    for row_index, variable_name in missing:
        offset, width = offsets[variable_name]
        start = observation_start + row_index * record_length + offset
        restored[start : start + width] = b" " * width
    return bytes(restored)


def build_xpt_v5(csv_data: bytes, domain: SdtmDomain) -> XptProduct:
    """Write deterministic XPT v5 bytes and verify them through an independent read path."""

    frame, expected_rows, missing_characters = _dataframe(csv_data, domain)
    labels: dict[str, str | None] = {variable.name: variable.label for variable in domain.variables}
    formats = {
        variable.name: (f"${variable.length}." if variable.data_type == "character" else "8.")
        for variable in domain.variables
    }
    with tempfile.TemporaryDirectory(prefix="aurinara-xpt-") as temporary:
        path = Path(temporary) / domain.expected_output_name
        pyreadstat.write_xport(
            frame,
            path,
            file_label=domain.label,
            column_labels=labels,
            table_name=domain.code,
            file_format_version=5,
            variable_format=formats,
        )
        data = _XPT_TIMESTAMP.sub(_NORMALIZED_TIMESTAMP, path.read_bytes())
        if expected_rows:
            data = _restore_character_missing_values(data, domain, missing_characters)
        else:
            header_index = data.find(_OBS_HEADER)
            if header_index < 0:
                raise _problem(
                    "xpt_observation_header_missing", "XPT observation header is missing."
                )
            data = data[: header_index + 80]
    observed, metadata = pyreadstat.read_xport(io.BytesIO(data), output_format="pandas")
    names = [variable.name for variable in domain.variables]
    if metadata.table_name != domain.code or list(metadata.column_names) != names:
        raise _problem(
            "xpt_readback_metadata_mismatch", "XPT table or variable names changed on read-back."
        )
    if list(metadata.column_labels) != [labels[name] for name in names]:
        raise _problem("xpt_readback_label_mismatch", "XPT variable labels changed on read-back.")
    if metadata.number_rows != len(expected_rows):
        raise _problem("xpt_readback_row_count_mismatch", "XPT row count changed on read-back.")
    for variable in domain.variables:
        observed_type = metadata.readstat_variable_types[variable.name]
        expected_type = "string" if variable.data_type == "character" else "double"
        if observed_type != expected_type:
            raise _problem(
                "xpt_readback_type_mismatch",
                f"{domain.code}.{variable.name} read back as {observed_type}, "
                f"expected {expected_type}.",
            )
        if (
            variable.data_type == "character"
            and metadata.variable_storage_width[variable.name] != variable.length
        ):
            raise _problem(
                "xpt_readback_length_mismatch",
                f"{domain.code}.{variable.name} storage width changed on read-back.",
            )
    raw_observed_rows = (
        observed.astype(object).where(pd.notna(observed), None).to_dict(orient="records")
    )
    observed_rows = [
        {name: None if value == "" else value for name, value in row.items()}
        for row in raw_observed_rows
    ]
    if observed_rows != expected_rows:
        raise _problem("xpt_readback_value_mismatch", "XPT values changed on read-back.")
    return XptProduct(
        data=data,
        manifest={
            "schema_version": "1.0.0",
            "format": "SAS XPORT",
            "format_version": 5,
            "dataset": domain.code,
            "label": domain.label,
            "row_count": len(expected_rows),
            "variables": [
                {
                    "name": variable.name,
                    "label": variable.label,
                    "data_type": variable.data_type,
                    "length": variable.length,
                }
                for variable in domain.variables
            ],
            "header_timestamps_normalized_to": "1970-01-01T00:00:00Z",
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )
