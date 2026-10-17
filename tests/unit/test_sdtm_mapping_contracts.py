"""Focused invariants for the SDTM mapping and workarea replacement."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.sdtm.authoring import _program_external_reference
from app.sdtm.contracts import (
    SdtmDomainMappingWrite,
    SdtmSpecification,
    SdtmVariableMappingWrite,
)


def test_each_code_run_owns_a_unique_platform_program_reference() -> None:
    common = {
        "workbench_id": UUID("10000000-0000-0000-0000-000000000001"),
        "workarea_id": UUID("20000000-0000-0000-0000-000000000002"),
        "code_revision": 3,
        "purpose": "test",
    }
    first = _program_external_reference(
        **common,
        run_id=UUID("30000000-0000-0000-0000-000000000003"),
    )
    second = _program_external_reference(
        **common,
        run_id=UUID("40000000-0000-0000-0000-000000000004"),
    )

    assert first != second
    assert first.endswith("test-run:30000000-0000-0000-0000-000000000003:program")


def test_value_contexts_are_typed_reusable_columns() -> None:
    specification = SdtmSpecification.model_validate(
        {
            "schema_version": "2.0.0",
            "domains": [
                {
                    "code": "LB",
                    "label": "Laboratory Test Results",
                    "domain_class": "Findings",
                    "structure": "One record per test per visit per subject",
                    "keys": ["STUDYID", "USUBJID", "LBSEQ"],
                    "sort_order": ["STUDYID", "USUBJID", "LBSEQ"],
                    "expected_output_name": "lb.xpt",
                    "variables": [
                        {
                            "name": name,
                            "label": name,
                            "data_type": "numeric" if name == "LBSEQ" else "character",
                            "length": None if name == "LBSEQ" else 40,
                            "role": "Identifier",
                            "core": "Req",
                            "origin": "Assigned",
                        }
                        for name in ("STUDYID", "USUBJID", "LBSEQ", "LBTESTCD")
                    ],
                    "value_contexts": [
                        {
                            "id": "alt",
                            "label": "Alanine aminotransferase",
                            "discriminator_variable": "LBTESTCD",
                            "operator": "eq",
                            "values": ["ALT"],
                        }
                    ],
                    "value_level_metadata": [
                        {
                            "id": "LB.ALT",
                            "variable": "LBTESTCD",
                            "context_id": "alt",
                            "label": "ALT test code",
                            "data_type": "character",
                            "length": 8,
                        }
                    ],
                }
            ],
        }
    )

    assert specification.domains[0].value_contexts[0].values == ("ALT",)


def test_eq_context_rejects_multiple_values() -> None:
    with pytest.raises(ValidationError, match="requires exactly one"):
        SdtmSpecification.model_validate(
            {
                "schema_version": "2.0.0",
                "domains": [
                    {
                        "code": "DM",
                        "label": "Demographics",
                        "domain_class": "Special Purpose",
                        "structure": "One record per subject",
                        "keys": ["STUDYID"],
                        "sort_order": ["STUDYID"],
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
                            }
                        ],
                        "value_contexts": [
                            {
                                "id": "bad",
                                "label": "Bad",
                                "discriminator_variable": "STUDYID",
                                "operator": "eq",
                                "values": ["A", "B"],
                            }
                        ],
                    }
                ],
            }
        )


def test_domain_mapping_requires_at_least_one_unique_input() -> None:
    with pytest.raises(ValidationError, match="at least one input"):
        SdtmDomainMappingWrite()
    with pytest.raises(ValidationError, match="must be unique"):
        SdtmDomainMappingWrite(raw_datasets=("RAW_DM", "RAW_DM"))


def test_variable_mapping_supports_ordered_multi_source_cells_and_sparse_matrix() -> None:
    mapping = SdtmVariableMappingWrite.model_validate(
        {
            "cells": [
                {
                    "target_variable": "USUBJID",
                    "context_id": None,
                    "sources": [
                        {"source_type": "raw", "dataset": "DM", "variable": "SUBJID"},
                        {"source_type": "raw", "dataset": "SITE", "variable": "SITEID"},
                    ],
                }
            ]
        }
    )

    assert [source.variable for source in mapping.cells[0].sources] == ["SUBJID", "SITEID"]
    assert len(mapping.cells) == 1


def test_variable_mapping_rejects_duplicate_cell_and_source() -> None:
    cell = {
        "target_variable": "USUBJID",
        "context_id": None,
        "sources": [{"source_type": "raw", "dataset": "DM", "variable": "SUBJID"}],
    }
    with pytest.raises(ValidationError, match="cells must be unique"):
        SdtmVariableMappingWrite.model_validate({"cells": [cell, cell]})
    with pytest.raises(ValidationError, match="sources must be unique"):
        SdtmVariableMappingWrite.model_validate(
            {"cells": [{**cell, "sources": [*cell["sources"], *cell["sources"]]}]}
        )
