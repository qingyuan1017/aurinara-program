"""ADaM Specification XLSX exchange tests."""

import io

import pytest
from openpyxl import load_workbook

from app.adam.contracts import AdamSpecification
from app.adam.specification_workbook import (
    parse_specification_xlsx,
    render_specification_xlsx,
)


def _specification() -> AdamSpecification:
    return AdamSpecification.model_validate(
        {
            "datasets": [
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
                            "origin": {"origin_type": "Derived", "description": "Copy ARM."},
                            "method_id": "MT.TRT01P",
                            "output_node_id": "derive_trt",
                            "terminology_binding": {
                                "terminology_release_id": "30000000-0000-0000-0000-000000000001",
                                "codelist_code": "ARM",
                            },
                        },
                    ],
                    "parameters": [
                        {
                            "id": "50000000-0000-0000-0000-000000000001",
                            "code": "TRT",
                            "label": "Treatment parameter",
                            "variable": "TRT01P",
                            "value": "Placebo",
                        }
                    ],
                    "value_level_metadata": [
                        {
                            "id": "40000000-0000-0000-0000-000000000001",
                            "variable": "TRT01P",
                            "condition": {
                                "kind": "binary",
                                "operator": "eq",
                                "left": {
                                    "kind": "column",
                                    "dataset": "ADSL",
                                    "column": "TRT01P",
                                },
                                "right": {"kind": "literal", "value": "Placebo"},
                            },
                            "label": "Placebo treatment",
                            "data_type": "character",
                            "length": 20,
                            "origin": {"origin_type": "Derived"},
                            "method_id": "MT.TRT01P",
                        }
                    ],
                }
            ],
            "methods": [
                {
                    "id": "MT.TRT01P",
                    "name": "Planned treatment",
                    "description": "Copy the planned arm from SDTM DM.",
                    "plan_node_ids": ["derive_trt"],
                }
            ],
            "trace_targets": [
                {
                    "relationship_type": "analyzes",
                    "source": {
                        "module": "documents",
                        "entity_type": "sap_method",
                        "entity_id": "60000000-0000-0000-0000-000000000001",
                    },
                    "target": {
                        "module": "adam",
                        "entity_type": "adam_parameter",
                        "entity_id": "50000000-0000-0000-0000-000000000001",
                    },
                }
            ],
        }
    )


def test_workbook_round_trip_is_lossless_and_deterministic() -> None:
    specification = _specification()

    first = render_specification_xlsx(specification)
    second = render_specification_xlsx(specification)

    assert first == second
    assert parse_specification_xlsx(first) == specification


def test_workbook_rejects_unknown_or_missing_sheets() -> None:
    workbook = load_workbook(io.BytesIO(render_specification_xlsx(_specification())))
    del workbook["Methods"]
    changed = io.BytesIO()
    workbook.save(changed)
    workbook.close()

    with pytest.raises(ValueError, match="workbook sheets must be exactly"):
        parse_specification_xlsx(changed.getvalue())
