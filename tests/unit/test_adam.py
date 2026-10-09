"""ADaM Specification, plan alignment, and lowering invariants."""

from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.adam.contracts import (
    AdamAdrgModel,
    AdamDefineModel,
    AdamDerivationPlan,
    AdamSpecification,
)
from app.adam.descriptor import HANDLER
from app.adam.service import (
    lower_plan,
    validate_dependency_compatibility,
    validate_origins,
    validate_sdtm_sources,
)
from app.artifacts.storage import ObjectStorage
from app.common.problems import ProblemException
from app.kernel.dependencies import DependencySelectionResponse
from app.sdtm.contracts import SdtmDerivationPlan


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
                            "origin": {
                                "origin_type": "Derived",
                                "description": "Assigned from the randomized arm.",
                            },
                            "method_id": "MT.TRT01P",
                            "output_node_id": "derive_trt",
                        },
                    ],
                }
            ],
            "methods": [
                {
                    "id": "MT.TRT01P",
                    "name": "Planned treatment",
                    "description": "Copy the randomized treatment description.",
                    "plan_node_ids": ["derive_trt"],
                }
            ],
        }
    )


def _plan() -> AdamDerivationPlan:
    return AdamDerivationPlan.model_validate(
        {
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [
                {"node_type": "sdtm_read", "id": "read_dm", "dataset": "DM"},
                {
                    "node_type": "derive",
                    "id": "derive_trt",
                    "target_dataset": "ADSL",
                    "method_id": "MT.TRT01P",
                    "assignments": {
                        "TRT01P": {
                            "kind": "column",
                            "dataset": "DM",
                            "column": "ARM",
                        }
                    },
                },
                {"node_type": "dataset_write", "id": "write_adsl", "dataset": "ADSL"},
            ],
            "edges": [
                {"source_node": "read_dm", "target_node": "derive_trt"},
                {"source_node": "derive_trt", "target_node": "write_adsl"},
            ],
        }
    )


def test_specification_preserves_stable_dataset_and_variable_ids() -> None:
    specification = _specification()

    assert specification.datasets[0].id == UUID("10000000-0000-0000-0000-000000000001")
    assert specification.datasets[0].variables[1].method_id == "MT.TRT01P"


def test_specification_trace_target_must_resolve_to_declared_typed_entity() -> None:
    payload = _specification().model_dump(mode="json")
    payload["trace_targets"] = [
        {
            "relationship_type": "analyzes",
            "source": {
                "module": "documents",
                "entity_type": "sap_method",
                "entity_id": "60000000-0000-0000-0000-000000000001",
            },
            "target": {
                "module": "adam",
                "entity_type": "adam_variable",
                "entity_id": "20000000-0000-0000-0000-000000000099",
            },
        }
    ]

    with pytest.raises(ValidationError, match="trace targets must resolve"):
        AdamSpecification.model_validate(payload)


def test_define_xpt_reconciliation_checks_complete_physical_metadata() -> None:
    specification = _specification()
    artifact_id = UUID("30000000-0000-0000-0000-000000000099")
    model = AdamDefineModel.model_validate(
        {
            "specification_revision": 1,
            "input_selection_revision": 1,
            "study_oid": "STUDY.P4",
            "metadata_version_oid": "MDV.ADAM.1",
            "name": "ADaM Define",
            "standard_name": "ADaM-IG",
            "standard_version": "1.3",
            "output_artifact_ids": [artifact_id],
            "datasets": [item.model_dump(mode="json") for item in specification.datasets],
            "methods": [item.model_dump(mode="json") for item in specification.methods],
            "leaves": [
                {
                    "id": "LF.ADSL",
                    "title": "ADSL",
                    "href": "wrong.xpt",
                    "artifact_id": artifact_id,
                    "checksum": "a" * 64,
                }
            ],
        }
    )
    variables = [
        {
            "name": variable.name,
            "label": variable.label,
            "data_type": variable.data_type,
            "length": variable.length,
            "origin": variable.origin.model_dump(mode="json"),
            "method_id": variable.method_id,
        }
        for variable in reversed(specification.datasets[0].variables)
    ]
    variables[0]["label"] = "Changed label"
    variables[0]["origin"] = {"origin_type": "Assigned"}
    variables[0]["method_id"] = None
    variables.append(
        {
            "name": "EXTRA",
            "label": "Extra",
            "data_type": "character",
            "length": 8,
            "origin": {"origin_type": "Assigned"},
            "method_id": None,
        }
    )
    evaluation = HANDLER.evaluate_reconciliation(
        {
            "define": {
                "id": "40000000-0000-0000-0000-000000000099",
                "revision": 1,
                "payload": model.model_dump(mode="json"),
            },
            "artifacts": [
                {
                    "id": str(artifact_id),
                    "checksum": "a" * 64,
                    "filename": "wrong.xpt",
                    "manifest": {
                        "dataset": "ADSL",
                        "label": "Changed dataset label",
                        "variables": variables,
                    },
                }
            ],
        },
        cast(ObjectStorage, object()),
    )
    codes = {str(issue["code"]) for issue in evaluation.issues}

    assert {
        "ADAM_DEFINE_DATASET_FILENAME_MISMATCH",
        "ADAM_DEFINE_DATASET_LABEL_MISMATCH",
        "ADAM_DEFINE_VARIABLE_ORDER_MISMATCH",
        "ADAM_DEFINE_VARIABLE_LABEL_MISMATCH",
        "ADAM_DEFINE_VARIABLE_ORIGIN_MISMATCH",
        "ADAM_DEFINE_VARIABLE_METHOD_MISMATCH",
        "ADAM_XPT_VARIABLE_UNDEFINED",
    } <= codes


def test_plan_lowers_to_internal_dataflow_ir() -> None:
    internal = lower_plan(_specification(), _plan())

    assert [node.node_type for node in internal.nodes] == ["read", "derive", "write"]
    assert internal.nodes[-1].dataset == "ADSL"


def test_plan_rejects_cycles_and_raw_backend_code() -> None:
    payload = _plan().model_dump(mode="json")
    payload["edges"].append({"source_node": "write_adsl", "target_node": "read_dm"})
    with pytest.raises(ValidationError):
        AdamDerivationPlan.model_validate(payload)

    payload = _plan().model_dump(mode="json")
    payload["nodes"][0]["python"] = "import os"
    with pytest.raises(ValidationError):
        AdamDerivationPlan.model_validate(payload)


def test_sdtm_and_adam_plan_envelopes_match_but_node_vocabularies_do_not() -> None:
    assert AdamDerivationPlan.model_fields.keys() == SdtmDerivationPlan.model_fields.keys()

    adam_payload = _plan().model_dump(mode="json")
    adam_payload["nodes"] = [
        {"node_type": "raw_read", "id": "read_raw", "raw_dataset_code": "DEMOG"}
    ]
    adam_payload["edges"] = []
    with pytest.raises(ValidationError):
        AdamDerivationPlan.model_validate(adam_payload)


def test_derived_dataset_requires_declared_write() -> None:
    payload = _plan().model_dump(mode="json")
    payload["nodes"] = payload["nodes"][:-1]
    payload["edges"] = payload["edges"][:-1]
    plan = AdamDerivationPlan.model_validate(payload)

    with pytest.raises(ProblemException) as captured:
        lower_plan(_specification(), plan)

    assert captured.value.code == "adam_plan_output_coverage_missing"


def test_plan_reads_only_exact_selected_sdtm_datasets() -> None:
    context = {"xpt_artifacts": [{"dataset_code": "AE"}]}

    with pytest.raises(ProblemException) as captured:
        validate_sdtm_sources(_plan(), context)

    assert captured.value.code == "adam_sdtm_input_missing"


def test_predecessor_origins_resolve_against_selected_sdtm_metadata() -> None:
    context = {
        "xpt_artifacts": [{"dataset_code": "DM"}],
        "datasets": [{"code": "DM", "variables": [{"name": "ARM"}]}],
    }

    with pytest.raises(ProblemException) as captured:
        validate_origins(_specification(), context)

    assert captured.value.code == "adam_origin_unresolved"


def test_adam_predecessor_reads_require_declared_output_edges() -> None:
    specification = AdamSpecification.model_validate(
        {
            "datasets": [
                {
                    "id": dataset_id,
                    "code": code,
                    "label": code,
                    "dataset_class": "ANALYSIS",
                    "structure": "One record per subject",
                    "keys": ["USUBJID"],
                    "sort_order": ["USUBJID"],
                    "expected_output_name": f"{code.lower()}.xpt",
                    "variables": [
                        {
                            "id": variable_id,
                            "name": "USUBJID",
                            "label": "Unique Subject Identifier",
                            "data_type": "character",
                            "length": 40,
                            "role": "Identifier",
                            "origin": {"origin_type": "Assigned"},
                            "output_node_id": output_node,
                        }
                    ],
                }
                for code, dataset_id, variable_id, output_node in (
                    (
                        "ADSL",
                        "10000000-0000-0000-0000-000000000001",
                        "20000000-0000-0000-0000-000000000001",
                        "write_adsl",
                    ),
                    (
                        "ADLB",
                        "10000000-0000-0000-0000-000000000002",
                        "20000000-0000-0000-0000-000000000002",
                        "write_adlb",
                    ),
                )
            ]
        }
    )
    plan = AdamDerivationPlan.model_validate(
        {
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [
                {"node_type": "adam_read", "id": "read_adsl", "dataset": "ADSL"},
                {"node_type": "dataset_write", "id": "write_adlb", "dataset": "ADLB"},
                {"node_type": "adam_read", "id": "read_adlb", "dataset": "ADLB"},
                {"node_type": "dataset_write", "id": "write_adsl", "dataset": "ADSL"},
            ],
            "edges": [
                {"source_node": "read_adsl", "target_node": "write_adlb"},
                {"source_node": "read_adlb", "target_node": "write_adsl"},
            ],
        }
    )

    with pytest.raises(ProblemException) as captured:
        lower_plan(specification, plan)

    assert captured.value.code == "adam_plan_predecessor_edge_missing"


def test_shared_sdtm_dependencies_must_select_exact_same_versions() -> None:
    adam_selection = DependencySelectionResponse.model_validate(
        {
            "standards": [
                {
                    "purpose": "define_xml",
                    "standard_version_id": "30000000-0000-0000-0000-000000000001",
                }
            ],
            "revision": 2,
            "state": "current",
            "fingerprint": "a" * 64,
        }
    )
    sdtm_selection = {
        "standards": [
            {
                "purpose": "define_xml",
                "standard_version_id": "30000000-0000-0000-0000-000000000002",
            }
        ],
        "revision": 3,
        "state": "current",
        "fingerprint": "b" * 64,
    }

    with pytest.raises(ProblemException) as captured:
        validate_dependency_compatibility(adam_selection, {"dependency_selection": sdtm_selection})

    assert captured.value.code == "adam_sdtm_dependencies_incompatible"


def test_adam_define_requires_one_exact_leaf_per_selected_output() -> None:
    artifact_id = UUID("30000000-0000-0000-0000-000000000001")
    specification = _specification()
    payload = {
        "specification_revision": 1,
        "input_selection_revision": 1,
        "study_oid": "STUDY.P4",
        "metadata_version_oid": "MDV.ADAM.1",
        "name": "ADaM Define",
        "standard_name": "ADaM-IG",
        "standard_version": "1.3",
        "output_artifact_ids": [artifact_id],
        "datasets": [item.model_dump(mode="json") for item in specification.datasets],
        "methods": [item.model_dump(mode="json") for item in specification.methods],
        "leaves": [],
    }

    with pytest.raises(ValidationError, match="at least 1 item"):
        AdamDefineModel.model_validate(payload)


def test_adrg_facts_must_cover_exact_selected_outputs() -> None:
    output_id = UUID("30000000-0000-0000-0000-000000000001")
    other_output_id = UUID("30000000-0000-0000-0000-000000000002")
    payload = {
        "title": "Analysis Data Reviewer's Guide",
        "version": "1.0",
        "specification_revision": 1,
        "input_selection_revision": 1,
        "plan_revision": 1,
        "define_revision": 1,
        "reconciliation_run_id": "30000000-0000-0000-0000-000000000003",
        "output_artifact_ids": [output_id],
        "dataset_facts": [
            {
                "dataset": "ADSL",
                "label": "Subject-Level Analysis Dataset",
                "structure": "One record per subject",
                "xpt_artifact_id": other_output_id,
                "checksum": "a" * 64,
                "row_count": 2,
                "variable_count": 2,
            }
        ],
        "execution_facts": [
            {
                "execution_run_id": "30000000-0000-0000-0000-000000000004",
                "language": "python",
                "program_artifact_id": "30000000-0000-0000-0000-000000000005",
                "program_checksum": "b" * 64,
                "output_artifact_ids": [output_id],
            }
        ],
    }

    with pytest.raises(ValidationError, match="must cover exact selected outputs"):
        AdamAdrgModel.model_validate(payload)
