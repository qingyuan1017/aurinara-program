"""Define-XML 2.0/2.1 outputs conform to repository-pinned XSDs."""

import pytest
from lxml import etree

from app.common.problems import ProblemException
from app.sdtm.contracts import SdtmDefineModel
from app.sdtm.define_xml import (
    define_schema_fingerprint,
    render_define_xml,
    validate_define_xml,
)


def _model() -> SdtmDefineModel:
    return SdtmDefineModel.model_validate(
        {
            "specification_revision": 1,
            "study_oid": "STUDY.TEST",
            "metadata_version_oid": "MDV.TEST",
            "name": "Synthetic SDTM Define",
            "description": "Synthetic conformance fixture",
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
                            "role": "Identifier",
                            "mandatory": True,
                            "origin": {
                                "origin_type": "Derived",
                                "description": "Derived from the source identifier.",
                                "document_reference_ids": ["DOC.SAP"],
                            },
                            "codelist_id": "CL.SUBJECT",
                            "method_id": "MT.SUBJECT",
                            "comment_id": "COM.SUBJECT",
                        }
                    ],
                }
            ],
            "leaves": [{"id": "LF.DM", "title": "Demographics", "href": "dm.xpt"}],
            "document_references": [{"id": "DOC.SAP", "title": "Synthetic SAP", "href": "sap.pdf"}],
            "codelists": [
                {
                    "id": "CL.SUBJECT",
                    "name": "Synthetic subject values",
                    "data_type": "text",
                    "items": [{"coded_value": "01", "decode": "Subject 01", "rank": 1}],
                }
            ],
            "methods": [
                {
                    "id": "MT.SUBJECT",
                    "name": "Subject derivation",
                    "description": "Concatenate the manually specified study and subject IDs.",
                }
            ],
            "comments": [{"id": "COM.SUBJECT", "description": "Synthetic test comment."}],
        }
    )


@pytest.mark.parametrize("version", ["2.0", "2.1"])
def test_rendered_define_xml_conforms_to_pinned_schema(version: str) -> None:
    data = render_define_xml(_model(), version)  # type: ignore[arg-type]
    root = etree.fromstring(data)

    validate_define_xml(data, version)  # type: ignore[arg-type]
    assert root.tag == "{http://www.cdisc.org/ns/odm/v1.3}ODM"
    assert b"Synthetic SDTM Define" in data
    assert len(define_schema_fingerprint(version)) == 64  # type: ignore[arg-type]


def test_schema_validation_rejects_nonconforming_xml() -> None:
    with pytest.raises(ProblemException) as captured:
        validate_define_xml(b"<ODM/>", "2.1")
    assert captured.value.code == "define_xsd_validation_failed"
