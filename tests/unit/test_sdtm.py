"""SDTM Specification, plan alignment, and lowering invariants."""

import pytest
from pydantic import ValidationError

from app.common.problems import ProblemException
from app.sdtm.contracts import (
    AcrfAnnotationCreate,
    AcrfRegion,
    SdtmCsdrgModel,
    SdtmDefineModel,
    SdtmDerivationPlan,
    SdtmSpecification,
)
from app.sdtm.service import _csdrg_document, lower_plan


def _multi_domain_specification() -> SdtmSpecification:
    base = _specification().model_dump(mode="json")
    base["domains"].append(
        {
            "code": "AE",
            "label": "Adverse Events",
            "domain_class": "Events",
            "structure": "One record per event",
            "keys": ["STUDYID", "USUBJID"],
            "sort_order": ["STUDYID", "USUBJID"],
            "expected_output_name": "ae.xpt",
            "variables": [
                {
                    "name": "STUDYID",
                    "label": "Study Identifier",
                    "data_type": "character",
                    "length": 20,
                    "role": "Identifier",
                    "core": "Req",
                    "origin": "Assigned",
                    "derived": False,
                },
                {
                    "name": "USUBJID",
                    "label": "Unique Subject Identifier",
                    "data_type": "character",
                    "length": 40,
                    "role": "Identifier",
                    "core": "Req",
                    "origin": "Derived",
                    "derived": True,
                },
            ],
        }
    )
    return SdtmSpecification.model_validate(base)


def test_csdrg_document_keeps_manual_narrative_and_exact_facts_separate() -> None:
    model = SdtmCsdrgModel.model_validate(
        {
            "title": "Synthetic cSDRG",
            "version": "1.0",
            "specification_revision": 2,
            "define_revision": 3,
            "reconciliation_run_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "output_artifact_ids": ["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"],
            "dataset_facts": [
                {
                    "dataset": "DM",
                    "label": "Demographics",
                    "structure": "One record per subject",
                    "xpt_artifact_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "checksum": "c" * 64,
                    "row_count": 2,
                    "variable_count": 3,
                }
            ],
            "narrative_sections": [
                {
                    "section_id": "data_conformance",
                    "heading": "Data Conformance",
                    "paragraphs": ["A manually authored observation."],
                }
            ],
        }
    )
    rendered = _csdrg_document(model)
    assert rendered.sections[0].tables[0].rows[0][0] == "DM"
    assert rendered.sections[1].paragraphs[0].text == "A manually authored observation."
    assert rendered.sections[-1].tables[0].rows[-1][1] == str(model.reconciliation_run_id)


def _specification() -> SdtmSpecification:
    return SdtmSpecification.model_validate(
        {
            "domains": [
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
                            "derived": True,
                        },
                        {
                            "name": "USUBJID",
                            "label": "Unique Subject Identifier",
                            "data_type": "character",
                            "length": 40,
                            "role": "Identifier",
                            "core": "Req",
                            "origin": "Derived",
                            "derived": True,
                        },
                    ],
                }
            ]
        }
    )


def test_plan_lowers_to_internal_ir_with_output_coverage() -> None:
    plan = SdtmDerivationPlan.model_validate(
        {
            "domain": "DM",
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [
                {"node_type": "raw_read", "id": "read_demog", "raw_dataset_code": "DEMOG"},
                {
                    "node_type": "derive",
                    "id": "derive_ids",
                    "target_domain": "DM",
                    "assignments": {
                        "STUDYID": {"kind": "literal", "value": "SYN-001"},
                        "USUBJID": {
                            "kind": "column",
                            "dataset": "DEMOG",
                            "column": "SUBJID",
                        },
                    },
                },
                {"node_type": "domain_write", "id": "write_dm", "domain": "DM"},
            ],
            "edges": [
                {"source_node": "read_demog", "target_node": "derive_ids"},
                {"source_node": "derive_ids", "target_node": "write_dm"},
            ],
        }
    )
    assert plan.schema_version == "1.1.0"
    internal = lower_plan(_specification(), plan)
    assert [node.node_type for node in internal.nodes] == ["read", "derive", "write"]


def test_sdtm_read_lowers_to_ir_read() -> None:
    plan = SdtmDerivationPlan.model_validate(
        {
            "domain": "AE",
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [
                {"node_type": "sdtm_read", "id": "read_dm", "dataset": "DM"},
                {"node_type": "domain_write", "id": "write_ae", "domain": "AE"},
            ],
            "edges": [{"source_node": "read_dm", "target_node": "write_ae"}],
        }
    )
    internal = lower_plan(_multi_domain_specification(), plan)
    read_node = next(node for node in internal.nodes if node.node_type == "read")
    assert read_node.dataset == "DM"


def test_sdtm_read_rejects_self_and_unknown_targets() -> None:
    self_plan = SdtmDerivationPlan.model_validate(
        {
            "domain": "AE",
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [
                {"node_type": "sdtm_read", "id": "read_ae", "dataset": "AE"},
                {"node_type": "domain_write", "id": "write_ae", "domain": "AE"},
            ],
            "edges": [{"source_node": "read_ae", "target_node": "write_ae"}],
        }
    )
    with pytest.raises(ProblemException) as self_error:
        lower_plan(_multi_domain_specification(), self_plan)
    assert self_error.value.code == "sdtm_read_self"

    unknown_plan = SdtmDerivationPlan.model_validate(
        {
            "domain": "AE",
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [
                {"node_type": "sdtm_read", "id": "read_zz", "dataset": "ZZ"},
                {"node_type": "domain_write", "id": "write_ae", "domain": "AE"},
            ],
            "edges": [{"source_node": "read_zz", "target_node": "write_ae"}],
        }
    )
    with pytest.raises(ProblemException) as unknown_error:
        lower_plan(_multi_domain_specification(), unknown_plan)
    assert unknown_error.value.code == "sdtm_read_target_unknown"


def test_plan_rejects_write_out_of_scope() -> None:
    plan = SdtmDerivationPlan.model_validate(
        {
            "domain": "AE",
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [
                {"node_type": "raw_read", "id": "read", "raw_dataset_code": "AE"},
                {"node_type": "domain_write", "id": "write_dm", "domain": "DM"},
            ],
            "edges": [{"source_node": "read", "target_node": "write_dm"}],
        }
    )
    with pytest.raises(ProblemException) as captured:
        lower_plan(_multi_domain_specification(), plan)
    assert captured.value.code == "sdtm_plan_output_scope"


def test_plan_rejects_duplicate_writes() -> None:
    plan = SdtmDerivationPlan.model_validate(
        {
            "domain": "DM",
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [
                {"node_type": "raw_read", "id": "read", "raw_dataset_code": "DEMOG"},
                {"node_type": "domain_write", "id": "write_dm", "domain": "DM"},
                {"node_type": "domain_write", "id": "write_dm2", "domain": "DM"},
            ],
            "edges": [{"source_node": "read", "target_node": "write_dm"}],
        }
    )
    with pytest.raises(ProblemException) as captured:
        lower_plan(_specification(), plan)
    assert captured.value.code == "sdtm_plan_output_duplicate"


def test_non_derived_domain_accepts_zero_write() -> None:
    base = _specification().model_dump(mode="json")
    base["domains"].append(
        {
            "code": "SU",
            "label": "Substance Use",
            "domain_class": "Interventions",
            "structure": "One record per use",
            "keys": ["STUDYID", "USUBJID"],
            "sort_order": ["STUDYID", "USUBJID"],
            "expected_output_name": "su.xpt",
            "variables": [
                {
                    "name": "STUDYID",
                    "label": "Study Identifier",
                    "data_type": "character",
                    "length": 20,
                    "role": "Identifier",
                    "core": "Req",
                    "origin": "Collected",
                    "derived": False,
                },
                {
                    "name": "USUBJID",
                    "label": "Unique Subject Identifier",
                    "data_type": "character",
                    "length": 40,
                    "role": "Identifier",
                    "core": "Req",
                    "origin": "Collected",
                    "derived": False,
                },
            ],
        }
    )
    specification = SdtmSpecification.model_validate(base)
    plan = SdtmDerivationPlan.model_validate(
        {
            "domain": "SU",
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [{"node_type": "raw_read", "id": "read", "raw_dataset_code": "SU"}],
        }
    )
    internal = lower_plan(specification, plan)
    assert [node.node_type for node in internal.nodes] == ["read"]


def test_plan_rejects_raw_backend_code() -> None:
    with pytest.raises(ValidationError):
        SdtmDerivationPlan.model_validate(
            {
                "domain": "DM",
                "specification_revision": 1,
                "input_selection_revision": 1,
                "nodes": [
                    {
                        "node_type": "raw_read",
                        "id": "read",
                        "raw_dataset_code": "DEMOG",
                        "python": "import os",
                    }
                ],
            }
        )


def test_plan_lowers_join_reshape_terminology_and_aggregate_operators() -> None:
    plan = SdtmDerivationPlan.model_validate(
        {
            "domain": "DM",
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [
                {"node_type": "raw_read", "id": "read_demog", "raw_dataset_code": "DEMOG"},
                {"node_type": "raw_read", "id": "read_sites", "raw_dataset_code": "SITES"},
                {
                    "node_type": "join",
                    "id": "join_site",
                    "join_type": "left",
                    "left_input": "read_demog",
                    "right_input": "read_sites",
                    "keys": [["SITEID", "SITEID"]],
                },
                {
                    "node_type": "terminology_map",
                    "id": "map_sex",
                    "source_column": "SEX",
                    "target_column": "SEXDEC",
                    "mappings": {"M": "Male", "F": "Female"},
                },
                {
                    "node_type": "cast",
                    "id": "cast_values",
                    "casts": {
                        "V1": {"source_column": "V1", "target_type": "float"},
                        "V2": {"source_column": "V2", "target_type": "float"},
                    },
                },
                {
                    "node_type": "pivot_longer",
                    "id": "visits",
                    "id_columns": ["SITEID", "SEXDEC"],
                    "value_columns": ["V1", "V2"],
                    "name_column": "VISIT",
                    "value_column": "VALUE",
                },
                {
                    "node_type": "sequence",
                    "id": "sequenced",
                    "group_by": ["SEXDEC"],
                    "order_by": ["VISIT"],
                    "target_column": "SEQ",
                },
                {
                    "node_type": "aggregate",
                    "id": "summary",
                    "group_by": ["SEXDEC"],
                    "aggregations": {
                        "N": {"operation": "count"},
                        "TOTAL": {"operation": "sum", "column": "VALUE"},
                    },
                },
                {"node_type": "domain_write", "id": "write_dm", "domain": "DM"},
            ],
            "edges": [
                {"source_node": "read_demog", "target_node": "join_site"},
                {"source_node": "read_sites", "target_node": "join_site"},
                {"source_node": "join_site", "target_node": "cast_values"},
                {"source_node": "cast_values", "target_node": "map_sex"},
                {"source_node": "map_sex", "target_node": "visits"},
                {"source_node": "visits", "target_node": "sequenced"},
                {"source_node": "sequenced", "target_node": "summary"},
                {"source_node": "summary", "target_node": "write_dm"},
            ],
        }
    )

    internal = lower_plan(_specification(), plan)

    assert [node.node_type for node in internal.nodes] == [
        "read",
        "read",
        "join",
        "terminology_map",
        "cast",
        "pivot_longer",
        "sequence",
        "aggregate",
        "write",
    ]


def test_plan_join_requires_declared_left_and_right_edges() -> None:
    with pytest.raises(ValidationError):
        SdtmDerivationPlan.model_validate(
            {
                "domain": "DM",
                "specification_revision": 1,
                "input_selection_revision": 1,
                "nodes": [
                    {"node_type": "raw_read", "id": "left", "raw_dataset_code": "A"},
                    {"node_type": "raw_read", "id": "right", "raw_dataset_code": "B"},
                    {
                        "node_type": "join",
                        "id": "joined",
                        "join_type": "inner",
                        "left_input": "left",
                        "right_input": "right",
                        "keys": [["ID", "ID"]],
                    },
                ],
                "edges": [{"source_node": "left", "target_node": "joined"}],
            }
        )


def test_derived_domain_requires_declared_write() -> None:
    plan = SdtmDerivationPlan.model_validate(
        {
            "domain": "DM",
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [{"node_type": "raw_read", "id": "read", "raw_dataset_code": "DEMOG"}],
        }
    )
    with pytest.raises(ProblemException) as captured:
        lower_plan(_specification(), plan)
    assert captured.value.code == "sdtm_plan_output_coverage_missing"


def test_acrf_region_must_fit_normalized_page() -> None:
    with pytest.raises(ValidationError):
        AcrfRegion(x=0.9, y=0.1, width=0.2, height=0.1)


def test_acrf_annotation_rejects_duplicate_exact_links() -> None:
    link = {
        "target_type": "sdtm_variable",
        "specification_revision": 1,
        "domain": "DM",
        "variable": "USUBJID",
    }
    with pytest.raises(ValidationError):
        AcrfAnnotationCreate.model_validate(
            {
                "source_pdf_artifact_id": "52cac611-5621-4770-932b-991b97e8cc8f",
                "page_number": 1,
                "region": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
                "links": [link, link],
            }
        )


def test_define_model_requires_resolved_leaf_references() -> None:
    with pytest.raises(ValidationError):
        SdtmDefineModel.model_validate(
            {
                "specification_revision": 1,
                "study_oid": "STUDY.TEST",
                "metadata_version_oid": "MDV.TEST",
                "name": "Test Define",
                "standard_name": "SDTM-IG",
                "standard_version": "3.3",
                "datasets": [
                    {
                        "oid": "IG.DM",
                        "name": "DM",
                        "label": "Demographics",
                        "dataset_class": "Special Purpose",
                        "structure": "One record per subject",
                        "leaf_id": "LF.DM",
                        "items": [
                            {
                                "oid": "IT.DM.USUBJID",
                                "name": "USUBJID",
                                "label": "Unique Subject Identifier",
                                "data_type": "text",
                                "length": 40,
                                "mandatory": True,
                                "origin": {"origin_type": "Derived"},
                            }
                        ],
                    }
                ],
            }
        )
