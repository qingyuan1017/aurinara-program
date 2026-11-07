"""Documents-owned narrative builders and deterministic workbook rendering."""

import io
from datetime import UTC, datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.artifacts.narrative import (
    DocumentCover,
    DocumentParagraph,
    DocumentSection,
    RenderDocument,
)
from app.common.zip_normalization import normalize_zip_bytes
from app.documents.contracts import (
    DocumentContentContract,
    NarrativeContent,
    StatisticalAnalysisPlanContent,
    WorkbookContentBase,
)

_FIXED_TIME = datetime(2000, 1, 1, tzinfo=UTC)


def content_to_document(code: str, content: DocumentContentContract) -> RenderDocument:
    """Translate persisted Documents content into the shared narrative representation."""

    cover = DocumentCover(
        title=content.title,
        document_code=code,
        version=getattr(content, "version", "1.0.0"),
        effective_date=getattr(content, "effective_date", None),
    )
    if isinstance(content, NarrativeContent):
        sections = tuple(
            DocumentSection(
                section_id=item.section_id,
                heading=item.heading,
                paragraphs=tuple(DocumentParagraph(text=text) for text in item.paragraphs),
            )
            for item in content.sections
        )
    elif isinstance(content, StatisticalAnalysisPlanContent):
        sap_sections: list[DocumentSection] = list(
            DocumentSection(
                section_id=item.section_id,
                heading=item.heading,
                paragraphs=tuple(DocumentParagraph(text=text) for text in item.paragraphs),
            )
            for item in content.narrative_sections
        )
        groups = (
            ("objectives", "Objectives", content.objectives),
            ("endpoints", "Endpoints", content.endpoints),
            ("estimands", "Estimands", content.estimands),
            ("populations", "Populations", content.populations),
            ("methods", "Statistical Methods", content.methods),
            ("missing_data", "Missing Data", content.missing_data),
            ("output_requirements", "Output Requirements", content.output_requirements),
            ("assumptions", "Assumptions", content.assumptions),
            ("quality_control", "Quality Control", content.qc_items),
        )
        for section_id, heading, records in groups:
            if records:
                sap_sections.append(
                    DocumentSection(
                        section_id=section_id,
                        heading=heading,
                        paragraphs=tuple(
                            DocumentParagraph(text=f"{item.name}: {item.description}")
                            for item in records
                        ),
                    )
                )
        sections = tuple(sap_sections)
    else:
        raise ValueError("workbook content cannot be converted to a narrative document")
    return RenderDocument(cover=cover, sections=sections)


def render_xlsx(content: WorkbookContentBase, template: dict[str, object] | None = None) -> bytes:
    """Render typed workbook rows in a protected, style-controlled workbook."""

    del template
    workbook = Workbook()
    worksheet = workbook.active
    if worksheet is None:
        raise RuntimeError("new workbook has no active worksheet")
    worksheet.title = "Data"
    rows = list(content.rows)
    headers = (
        list(rows[0].model_dump(mode="json").keys())
        if rows
        else ["row_id", "description", "category", "status", "owner"]
    )
    worksheet.append(headers)
    for row in rows:
        values = row.model_dump(mode="json")
        worksheet.append([_cell_value(values.get(column)) for column in headers])
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in worksheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(wrap_text=True)
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    for column_index, column in enumerate(worksheet.columns, start=1):
        width = min(60, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
        worksheet.column_dimensions[get_column_letter(column_index)].width = width
    metadata = workbook.create_sheet("Metadata")
    metadata.append(("schema_version", content.schema_version))
    metadata.append(("document_type", content.document_type))
    metadata.append(("title", content.title))
    metadata.sheet_state = "hidden"
    workbook.properties.creator = "Aurinara"
    workbook.properties.created = _FIXED_TIME.replace(tzinfo=None)
    workbook.properties.modified = _FIXED_TIME.replace(tzinfo=None)
    output = io.BytesIO()
    workbook.save(output)
    return normalize_zip_bytes(output.getvalue())


def workbook_payload(data: bytes) -> dict[str, object]:
    """Read a Documents workbook into a JSON payload without inferring values."""

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    if "Data" not in workbook.sheetnames or "Metadata" not in workbook.sheetnames:
        raise ValueError("workbook requires Data and Metadata sheets")
    metadata = {str(row[0]): row[1] for row in workbook["Metadata"].iter_rows(values_only=True)}
    values = list(workbook["Data"].iter_rows(values_only=True))
    if not values:
        raise ValueError("Data sheet requires a header row")
    headers = [str(value) for value in values[0]]
    if len(headers) != len(set(headers)) or any(not value for value in headers):
        raise ValueError("workbook columns must be non-empty and unique")
    return {
        "schema_version": metadata.get("schema_version"),
        "document_type": metadata.get("document_type"),
        "title": metadata.get("title"),
        "rows": [
            {header: value for header, value in zip(headers, row, strict=True) if value is not None}
            for row in values[1:]
            if any(value is not None for value in row)
        ],
    }


def _cell_value(value: object) -> object:
    if isinstance(value, (dict, list, tuple)):
        return str(value)
    return value
