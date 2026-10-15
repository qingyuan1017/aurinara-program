"""SDTM Specification initialization from selected industry metadata."""

from uuid import UUID

import pytest

from app.sdtm.contracts import SdtmSpecification
from app.sdtm.standard_specification import (
    initialize_specification_from_standard,
    standard_domain_options,
)
from app.standards.metadata_resolution import ResolvedStandardMetadata


def _metadata(*, product_code: str = "SDTMIG") -> ResolvedStandardMetadata:
    return ResolvedStandardMetadata(
        version_id=UUID("10000000-0000-0000-0000-000000000101"),
        product_code=product_code,
        product_name="Synthetic SDTM Implementation Guide",
        version="9.9",
        canonical_href="/mdr/sdtmig/9-9",
        checksum="a" * 64,
        payload={
            "classes": [
                {
                    "datasets": [
                        {
                            "_links": {
                                "parentClass": {"title": "Special-Purpose Datasets"}
                            },
                            "name": "DM",
                            "label": "Demographics",
                            "datasetStructure": "One record per subject",
                            "datasetVariables": [
                                {
                                    "name": "STUDYID",
                                    "label": "Study Identifier",
                                    "simpleDatatype": "Char",
                                    "role": "Identifier",
                                    "core": "Req",
                                },
                                {
                                    "name": "USUBJID",
                                    "label": "Unique Subject Identifier",
                                    "simpleDatatype": "Char",
                                    "role": "Identifier",
                                    "core": "Req",
                                },
                                {
                                    "name": "AGE",
                                    "label": "Age",
                                    "simpleDatatype": "Num",
                                    "role": "Record Qualifier",
                                    "core": "Exp",
                                },
                                {
                                    "name": "RACE",
                                    "label": "Race",
                                    "simpleDatatype": "Char",
                                    "role": "Record Qualifier",
                                    "core": "Perm",
                                },
                            ],
                        },
                        {
                            "_links": {
                                "parentClass": {"title": "Events"}
                            },
                            "name": "AE",
                            "label": "Adverse Events",
                            "datasetStructure": "One record per adverse event",
                            "datasetVariables": [
                                {
                                    "name": "STUDYID",
                                    "label": "Study Identifier",
                                    "simpleDatatype": "Char",
                                    "role": "Identifier",
                                    "core": "Req",
                                },
                                {
                                    "name": "AETERM",
                                    "label": "Reported Term for the Adverse Event",
                                    "simpleDatatype": "Char",
                                    "role": "Topic",
                                    "core": "Exp",
                                },
                                {
                                    "name": "AEBODSYS",
                                    "label": "Body System or Organ Class",
                                    "simpleDatatype": "Char",
                                    "role": "Record Qualifier",
                                    "core": "Perm",
                                },
                            ],
                        },
                        {
                            "name": "SUPPQUAL",
                            "label": "Supplemental Qualifiers for [domain name]",
                            "datasetStructure": "One record per qualifier",
                            "datasetVariables": [
                                {
                                    "name": "STUDYID",
                                    "label": "Study Identifier",
                                    "simpleDatatype": "Char",
                                    "role": "Identifier",
                                    "core": "Req",
                                }
                            ],
                        },
                    ]
                }
            ]
        },
    )


def test_initializes_concrete_domains_from_exact_sdtmig_metadata() -> None:
    result = initialize_specification_from_standard(_metadata())

    assert [item.code for item in result.domains] == ["DM", "AE"]
    domain = result.domains[0]
    assert domain.domain_class == "Special-Purpose Datasets"
    assert domain.keys == ("STUDYID", "USUBJID")
    assert domain.sort_order == domain.keys
    assert domain.expected_output_name == "dm.xpt"
    assert [(item.name, item.data_type, item.origin) for item in domain.variables] == [
        ("STUDYID", "character", "Standard"),
        ("USUBJID", "character", "Standard"),
        ("AGE", "numeric", "Standard"),
        ("RACE", "character", "Standard"),
    ]


def test_reinitialization_preserves_manual_values_and_adds_only_missing_variables() -> None:
    initialized = initialize_specification_from_standard(_metadata())
    domain = initialized.domains[0]
    current = SdtmSpecification(
        domains=(
            domain.model_copy(
                update={
                    "label": "Manually maintained demographics",
                    "keys": ("USUBJID",),
                    "sort_order": ("USUBJID",),
                    "variables": (
                        domain.variables[1].model_copy(
                            update={"label": "Manual subject identifier", "origin": "Derived"}
                        ),
                    ),
                }
            ),
        )
    )

    result = initialize_specification_from_standard(_metadata(), current)

    assert result.domains[0].label == "Manually maintained demographics"
    assert result.domains[0].keys == ("USUBJID",)
    assert [item.name for item in result.domains[0].variables] == [
        "USUBJID",
        "STUDYID",
        "AGE",
        "RACE",
    ]
    assert result.domains[0].variables[0].label == "Manual subject identifier"
    assert result.domains[0].variables[0].origin == "Derived"


def test_lists_concrete_domain_options_with_core_counts() -> None:
    options = standard_domain_options(_metadata())

    assert [(item.code, item.label) for item in options] == [
        ("DM", "Demographics"),
        ("AE", "Adverse Events"),
    ]
    assert options[0].required_variable_count == 2
    assert options[0].expected_variable_count == 1
    assert options[0].permissible_variable_count == 1


def test_initializes_only_selected_domains_and_required_expected_variables() -> None:
    result = initialize_specification_from_standard(
        _metadata(),
        domain_codes=("AE",),
        core_variables_only=True,
    )

    assert [item.code for item in result.domains] == ["AE"]
    assert [item.name for item in result.domains[0].variables] == [
        "STUDYID",
        "AETERM",
    ]


def test_reinitialization_filters_only_new_variables_and_preserves_existing_permissible() -> None:
    initialized = initialize_specification_from_standard(
        _metadata(), domain_codes=("DM",)
    )
    result = initialize_specification_from_standard(
        _metadata(),
        initialized,
        domain_codes=("DM",),
        core_variables_only=True,
    )

    assert [item.name for item in result.domains[0].variables] == [
        "STUDYID",
        "USUBJID",
        "AGE",
        "RACE",
    ]


def test_rejects_unknown_selected_domain() -> None:
    with pytest.raises(ValueError, match="does not contain concrete domain.*ZZ"):
        initialize_specification_from_standard(
            _metadata(), domain_codes=("ZZ",)
        )


def test_rejects_a_selected_standard_that_is_not_sdtmig() -> None:
    with pytest.raises(ValueError, match="SDTM implementation guide"):
        initialize_specification_from_standard(_metadata(product_code="ADAMIG"))


def test_rejects_standard_variables_without_required_factual_metadata() -> None:
    metadata = _metadata()
    payload = dict(metadata.payload)
    classes = list(payload["classes"])
    datasets = list(classes[0]["datasets"])
    variables = list(datasets[0]["datasetVariables"])
    variables[0] = {**variables[0], "simpleDatatype": "Date"}
    datasets[0] = {**datasets[0], "datasetVariables": variables}
    classes[0] = {**classes[0], "datasets": datasets}
    invalid = ResolvedStandardMetadata(
        version_id=metadata.version_id,
        product_code=metadata.product_code,
        product_name=metadata.product_name,
        version=metadata.version,
        canonical_href=metadata.canonical_href,
        checksum=metadata.checksum,
        payload={**payload, "classes": classes},
    )

    with pytest.raises(ValueError, match="unsupported datatype Date"):
        initialize_specification_from_standard(invalid)
