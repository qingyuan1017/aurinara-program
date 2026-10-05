"""Phase 2 Documents contracts, validation, and deterministic renderer tests."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.documents.contracts import (
    ActionsReportContent,
    EvidenceRegion,
    ProtocolContent,
    StatisticalAnalysisPlanContent,
    UsdmDocument,
    validate_content,
)
from app.documents.rendering import (
    content_to_document,
    normalized_docx_text,
    normalized_pdf_text,
    render_docx,
    render_pdf,
    render_xlsx,
    workbook_payload,
)
from app.documents.validation import validate_document

GOLDEN = Path(__file__).resolve().parents[1] / "golden/documents/renderer-sha256.json"


def _protocol_content() -> ProtocolContent:
    return ProtocolContent.model_validate(
        {
            "document_type": "protocol",
            "title": "Synthetic Protocol",
            "version": "1.0",
            "sections": [
                {
                    "section_id": "overview",
                    "heading": "Study Overview",
                    "paragraphs": ["Manually authored synthetic protocol content."],
                }
            ],
        }
    )


def test_docx_and_pdf_share_normalized_authored_content() -> None:
    document = content_to_document("PROTO-001", _protocol_content())
    docx = render_docx(document)
    pdf = render_pdf(document)

    assert docx == render_docx(document)
    assert pdf == render_pdf(document)
    docx_text = " ".join(normalized_docx_text(docx))
    pdf_text = " ".join(normalized_pdf_text(pdf))
    for expected in (
        "Synthetic Protocol",
        "PROTO-001",
        "Study Overview",
        "Manually authored synthetic protocol content.",
    ):
        assert expected in docx_text
        assert expected in pdf_text


def test_workbook_round_trip_preserves_user_values() -> None:
    content = ActionsReportContent.model_validate(
        {
            "document_type": "actions_report",
            "title": "Actions",
            "rows": [
                {
                    "row_id": "ACT-1",
                    "description": "Verify the synthetic listing",
                    "category": "quality",
                    "status": "open",
                    "owner": "Data Management",
                    "action_type": "review",
                    "notes": "No inferred values",
                }
            ],
        }
    )
    data = render_xlsx(content)
    imported = validate_content("actions_report", workbook_payload(data))

    assert imported.model_dump(mode="json") == content.model_dump(mode="json")
    assert data == render_xlsx(content)


def test_renderer_bytes_match_reviewed_golden_fingerprints() -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    protocol = content_to_document("PROTO-001", _protocol_content())
    actions = ActionsReportContent.model_validate(
        {
            "document_type": "actions_report",
            "title": "Actions",
            "rows": [
                {
                    "row_id": "ACT-1",
                    "description": "Verify the synthetic listing",
                    "category": "quality",
                    "status": "open",
                    "owner": "Data Management",
                    "action_type": "review",
                    "notes": "No inferred values",
                }
            ],
        }
    )
    observed = {
        "protocol_summary_docx": hashlib.sha256(render_docx(protocol)).hexdigest(),
        "protocol_summary_pdf": hashlib.sha256(render_pdf(protocol)).hexdigest(),
        "actions_report_xlsx": hashlib.sha256(render_xlsx(actions)).hexdigest(),
    }
    assert observed == {key: expected[key] for key in observed}


def test_usdm_rejects_dangling_relationship_and_evidence_rejects_bad_coordinates() -> None:
    with pytest.raises(ValidationError):
        UsdmDocument.model_validate(
            {
                "usdm_version": "4.0",
                "study_version": "1",
                "entities": [{"id": "OBJ1", "entity_type": "objective", "name": "Objective"}],
                "relationships": [
                    {
                        "relationship_type": "measured_by",
                        "source_entity_id": "OBJ1",
                        "target_entity_id": "MISSING",
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        EvidenceRegion(page_width=612, page_height=792, rectangle=(600, 10, 20, 20))


def test_sap_validation_reports_manual_reference_and_assumption_gaps() -> None:
    document_id = uuid4()
    content = StatisticalAnalysisPlanContent.model_validate(
        {
            "document_type": "statistical_analysis_plan",
            "title": "Synthetic SAP",
            "version": "1",
            "protocol_alignment": [
                {
                    "id": "ALIGN1",
                    "name": "Alignment",
                    "description": "Authored alignment",
                    "protocol_entity_ids": ["OBJ-MISSING"],
                }
            ],
            "objectives": [{"id": "OBJ1", "name": "Objective", "description": "Text"}],
            "endpoints": [{"id": "END1", "name": "Endpoint", "description": "Text"}],
            "estimands": [
                {
                    "id": "EST1",
                    "name": "Estimand",
                    "description": "Text",
                    "population_id": "POP-MISSING",
                    "treatment_condition": "A versus B",
                    "variable": "Change",
                    "intercurrent_event_strategy": "Treatment policy",
                    "summary_measure": "Difference in means",
                }
            ],
            "populations": [{"id": "POP1", "name": "ITT", "description": "Text"}],
            "methods": [{"id": "M1", "name": "ANCOVA", "description": "Text"}],
            "missing_data": [{"id": "MD1", "name": "Missing", "description": "Text"}],
            "output_requirements": [{"id": "O1", "name": "Table", "description": "Text"}],
            "assumptions": [
                {
                    "id": "A1",
                    "name": "Material",
                    "description": "Text",
                    "material": True,
                    "resolution_status": "open",
                }
            ],
            "qc_items": [{"id": "Q1", "name": "QC", "description": "Text"}],
            "narrative_sections": [
                {"section_id": "methods", "heading": "Methods", "paragraphs": ["Text"]}
            ],
            "citations": [
                {
                    "citation_id": "C1",
                    "title": "Reference",
                    "reference": "Synthetic source",
                    "section_ids": ["missing-section"],
                }
            ],
        }
    )

    issues = validate_document(
        document_id=document_id,
        content=content,
        protocol_entity_ids={"OBJ1"},
    )
    assert {item.code for item in issues} == {
        "estimand_population_unresolved",
        "protocol_reference_unresolved",
        "citation_section_unresolved",
        "material_assumption_unresolved",
    }
