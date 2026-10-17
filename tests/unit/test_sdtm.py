"""SDTM document and aCRF authoring invariants."""

import pytest
from pydantic import ValidationError

from app.sdtm.contracts import (
    AcrfAnnotationCreate,
    AcrfRegion,
    SdtmCsdrgModel,
    SdtmDefineModel,
)
from app.sdtm.service import (
    _csdrg_document,
)


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
