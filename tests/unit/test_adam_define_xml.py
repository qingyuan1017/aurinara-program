"""ADaM Define rendering preserves analysis metadata and validates offline."""

from uuid import UUID, uuid4

from lxml import etree

from app.adam.contracts import AdamDefineModel, AdamSpecification
from app.adam.define import validate_define_metadata
from app.adam.define_xml import render_define_xml, validate_define_xml


def _model() -> AdamDefineModel:
    artifact_id = UUID("30000000-0000-0000-0000-000000000001")
    release_id = uuid4()
    return AdamDefineModel.model_validate(
        {
            "specification_revision": 1,
            "input_selection_revision": 1,
            "study_oid": "STUDY.P4",
            "metadata_version_oid": "MDV.ADAM.1",
            "name": "ADaM Define",
            "standard_name": "ADaM-IG",
            "standard_version": "1.3",
            "output_artifact_ids": [artifact_id],
            "datasets": [
                {
                    "id": uuid4(),
                    "code": "ADSL",
                    "label": "Subject-Level Analysis Dataset",
                    "dataset_class": "SUBJECT LEVEL ANALYSIS DATASET",
                    "structure": "One record per subject",
                    "keys": ["USUBJID"],
                    "sort_order": ["USUBJID"],
                    "expected_output_name": "adsl.xpt",
                    "variables": [
                        {
                            "id": uuid4(),
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
                            "terminology_binding": {
                                "terminology_release_id": release_id,
                                "codelist_code": "SUBJID",
                            },
                        }
                    ],
                    "parameters": [
                        {
                            "id": "50000000-0000-0000-0000-000000000001",
                            "code": "P1",
                            "label": "Synthetic parameter",
                            "variable": "USUBJID",
                            "value": "01",
                        }
                    ],
                    "value_level_metadata": [
                        {
                            "id": uuid4(),
                            "variable": "USUBJID",
                            "condition": {"kind": "literal", "value": True},
                            "label": "Synthetic value-level metadata",
                            "data_type": "character",
                            "length": 40,
                            "origin": {
                                "origin_type": "Derived",
                                "description": "Maintained derivation.",
                            },
                            "method_id": "MT.VLM",
                        }
                    ],
                }
            ],
            "methods": [
                {
                    "id": "MT.VLM",
                    "name": "Value-level method",
                    "description": "Synthetic maintained method.",
                    "plan_node_ids": ["read_dm"],
                }
            ],
            "leaves": [
                {
                    "id": "LF.ADSL",
                    "title": "ADSL",
                    "href": "adsl.xpt",
                    "artifact_id": artifact_id,
                    "checksum": "a" * 64,
                }
            ],
        }
    )


def test_adam_define_renders_both_pinned_xsd_versions() -> None:
    for version in ("2.0", "2.1"):
        data = render_define_xml(_model(), version)

        validate_define_xml(data, version)
        assert b"COM.PARAM.ADSL" in data
        assert b"COM.VLM.ADSL.USUBJID" in data
        assert b"Aurinara Terminology Binding" in data
        assert b"ValueListDef" not in data


def test_supported_value_level_condition_renders_machine_readable_define() -> None:
    payload = _model().model_dump(mode="json")
    payload["datasets"][0]["variables"].append(
        {
            "id": str(uuid4()),
            "name": "PARAMCD",
            "label": "Parameter Code",
            "data_type": "character",
            "length": 8,
            "role": "Identifier",
            "origin": {"origin_type": "Assigned"},
            "output_node_id": "read_dm",
        }
    )
    value_level = payload["datasets"][0]["value_level_metadata"][0]
    value_level["variable"] = "USUBJID"
    value_level["condition"] = {
        "kind": "binary",
        "operator": "eq",
        "left": {"kind": "column", "dataset": "ADSL", "column": "PARAMCD"},
        "right": {"kind": "literal", "value": "AGE"},
    }
    model = AdamDefineModel.model_validate(payload)

    for version in ("2.0", "2.1"):
        data = render_define_xml(model, version)
        document = etree.fromstring(data)
        namespaces = {
            "odm": "http://www.cdisc.org/ns/odm/v1.3",
            "def": f"http://www.cdisc.org/ns/def/v{version}",
        }
        value_lists = document.xpath("//def:ValueListDef", namespaces=namespaces)
        where_clauses = document.xpath("//def:WhereClauseDef", namespaces=namespaces)
        value_list_refs = document.xpath("//def:ValueListRef", namespaces=namespaces)
        range_checks = document.xpath("//def:WhereClauseDef/odm:RangeCheck", namespaces=namespaces)

        assert len(value_lists) == len(where_clauses) == len(value_list_refs) == 1
        assert len(range_checks) == 1
        assert range_checks[0].get("Comparator") == "EQ"
        assert range_checks[0].get(f"{{{namespaces['def']}}}ItemOID") == "IT.ADSL.PARAMCD"
        assert range_checks[0].find("odm:CheckValue", namespaces).text == "AGE"


def _sdtm_context() -> dict[str, object]:
    return {
        "datasets": [
            {
                "code": "DM",
                "variables": [{"name": "USUBJID"}],
            }
        ]
    }


def test_define_metadata_validation_covers_all_factual_component_classes() -> None:
    expected_model = _model()
    specification = AdamSpecification(
        datasets=expected_model.datasets,
        methods=expected_model.methods,
    )
    payload = expected_model.model_dump(mode="json")
    dataset = payload["datasets"][0]
    dataset["label"] = "Changed dataset label"
    variable = dataset["variables"][0]
    variable["origin"]["source_variable"] = "UNKNOWN"
    variable["terminology_binding"]["codelist_code"] = "OTHER"
    parameter = dataset["parameters"][0]
    parameter["label"] = "Changed parameter label"
    parameter["terminology_binding"] = {
        "terminology_release_id": str(uuid4()),
        "codelist_code": "PARAM",
    }
    value_level = dataset["value_level_metadata"][0]
    value_level["label"] = "Changed value-level label"
    value_level["method_id"] = None
    payload["methods"][0]["description"] = "Changed method text"
    observed = AdamDefineModel.model_validate(payload)

    codes = {
        str(issue["code"])
        for issue in validate_define_metadata(specification, observed, _sdtm_context())
    }

    assert {
        "adam_define_dataset_metadata_mismatch",
        "adam_define_origin_mismatch",
        "adam_define_terminology_binding_mismatch",
        "adam_define_parameter_metadata_mismatch",
        "adam_define_value_level_metadata_mismatch",
        "adam_define_method_binding_mismatch",
        "adam_define_method_metadata_mismatch",
        "adam_define_predecessor_unresolved",
    } <= codes


def test_define_metadata_validation_reports_missing_and_extra_components() -> None:
    expected_model = _model()
    specification = AdamSpecification(
        datasets=expected_model.datasets,
        methods=expected_model.methods,
    )
    payload = expected_model.model_dump(mode="json")
    dataset = payload["datasets"][0]
    dataset["parameters"] = []
    dataset["value_level_metadata"] = []
    dataset["variables"].append(
        {
            "id": str(uuid4()),
            "name": "EXTRA",
            "label": "Extra variable",
            "data_type": "character",
            "length": 8,
            "role": "Identifier",
            "origin": {"origin_type": "Assigned"},
            "output_node_id": "read_dm",
        }
    )
    payload["methods"] = []
    observed = AdamDefineModel.model_validate(payload)

    codes = {
        str(issue["code"])
        for issue in validate_define_metadata(specification, observed, _sdtm_context())
    }

    assert {
        "adam_define_variable_extra",
        "adam_define_parameter_missing",
        "adam_define_value_level_missing",
        "adam_define_method_missing",
    } <= codes
