"""Deterministic renderers for shared narrative and workbook contracts."""

import io
import re
import zipfile
from datetime import UTC, datetime
from typing import Any

from docx import Document as DocxDocument
from docx.shared import Inches, Pt
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.documents.contracts import (
    DocumentContentContract,
    DocumentCover,
    DocumentParagraph,
    DocumentSection,
    NarrativeContent,
    RenderDocument,
    StatisticalAnalysisPlanContent,
    WorkbookContentBase,
)

RENDERER_VERSION = "1.0.0"
_FIXED_TIME = datetime(2000, 1, 1, tzinfo=UTC)


def content_to_document(code: str, content: DocumentContentContract) -> RenderDocument:
    """Translate persisted authored content into the shared rendering representation."""

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


def render_docx(document: RenderDocument, template: dict[str, object] | None = None) -> bytes:
    """Render a shared document as deterministic, style-controlled DOCX bytes."""

    output = io.BytesIO()
    target = DocxDocument()
    section = target.sections[0]
    section.top_margin = Inches(0.75)
    section.bottom_margin = Inches(0.75)
    styles = target.styles
    styles["Normal"].font.name = "Arial"
    styles["Normal"].font.size = Pt(10)
    target.core_properties.created = _FIXED_TIME
    target.core_properties.modified = _FIXED_TIME
    template_styles = template.get("styles", {}) if template else {}
    style_names = template_styles if isinstance(template_styles, dict) else {}
    title_style = str(style_names.get("title", "Title"))
    heading_style = str(style_names.get("heading", "Heading 1"))
    body_style = str(style_names.get("body", "Normal"))
    target.add_paragraph(document.cover.title, style=title_style)
    target.add_paragraph(f"Document code: {document.cover.document_code}")
    target.add_paragraph(f"Version: {document.cover.version}")
    if document.cover.effective_date is not None:
        target.add_paragraph(f"Effective date: {document.cover.effective_date.isoformat()}")
    target.add_page_break()  # type: ignore[no-untyped-call]
    for item in document.sections:
        target.add_paragraph(item.heading, style=heading_style)
        for paragraph in item.paragraphs:
            target.add_paragraph(paragraph.text, style=body_style)
        for bullet in item.bullets:
            target.add_paragraph(bullet, style="List Bullet")
        for table_contract in item.tables:
            table = target.add_table(rows=1, cols=len(table_contract.headers))
            table.style = "Table Grid"
            for cell, value in zip(table.rows[0].cells, table_contract.headers, strict=True):
                cell.text = value
            for row in table_contract.rows:
                cells = table.add_row().cells
                for cell, value in zip(cells, row, strict=True):
                    cell.text = value
    target.save(output)
    return _normalize_zip(output.getvalue())


def render_pdf(document: RenderDocument, template: dict[str, object] | None = None) -> bytes:
    """Render a shared document as stable PDF bytes."""

    del template
    output = io.BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], alignment=TA_CENTER))
    pdf = SimpleDocTemplate(
        output,
        pagesize=LETTER,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title=document.cover.title,
        author="Aurinara",
        invariant=True,
    )
    flow: list[Any] = [
        Spacer(1, 1.5 * inch),
        Paragraph(_escape(document.cover.title), styles["CoverTitle"]),
        Spacer(1, 0.4 * inch),
        Paragraph(f"Document code: {_escape(document.cover.document_code)}", styles["Normal"]),
        Paragraph(f"Version: {_escape(document.cover.version)}", styles["Normal"]),
    ]
    if document.cover.effective_date is not None:
        flow.append(
            Paragraph(
                f"Effective date: {document.cover.effective_date.isoformat()}", styles["Normal"]
            )
        )
    flow.append(PageBreak())
    for item in document.sections:
        flow.append(Paragraph(_escape(item.heading), styles["Heading1"]))
        for paragraph in item.paragraphs:
            flow.extend((Paragraph(_escape(paragraph.text), styles["BodyText"]), Spacer(1, 6)))
        for bullet in item.bullets:
            flow.append(Paragraph(f"• {_escape(bullet)}", styles["BodyText"]))
        for table_contract in item.tables:
            data = [list(table_contract.headers), *[list(row) for row in table_contract.rows]]
            table = Table(data, repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9EAF7")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            flow.extend((table, Spacer(1, 8)))
    pdf.build(flow)
    return output.getvalue()


def render_xlsx(content: WorkbookContentBase, template: dict[str, object] | None = None) -> bytes:
    """Render typed workbook rows in a protected, style-controlled workbook."""

    del template
    workbook = Workbook()
    worksheet = workbook.active
    if worksheet is None:
        raise RuntimeError("new workbook has no active worksheet")
    worksheet.title = "Data"
    rows = list(content.rows)
    if rows:
        headers = list(rows[0].model_dump(mode="json").keys())
    else:
        row_annotation = type(content).model_fields["rows"].annotation
        headers = ["row_id", "description", "category", "status", "owner"]
        del row_annotation
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
    return _normalize_zip(output.getvalue())


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


def normalized_docx_text(data: bytes) -> tuple[str, ...]:
    document = DocxDocument(io.BytesIO(data))
    values = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
    for table in document.tables:
        values.extend(" | ".join(cell.text for cell in row.cells) for row in table.rows)
    return tuple(values)


def normalized_pdf_text(data: bytes) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for page in PdfReader(io.BytesIO(data)).pages
        for line in (page.extract_text() or "").splitlines()
        if line.strip()
    )


def _normalize_zip(data: bytes) -> bytes:
    source = io.BytesIO(data)
    target = io.BytesIO()
    with (
        zipfile.ZipFile(source, "r") as reader,
        zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as writer,
    ):
        for name in sorted(reader.namelist()):
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            member = reader.read(name)
            if name == "docProps/core.xml":
                member = re.sub(
                    rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                    rb"\g<1>2000-01-01T00:00:00Z\g<2>",
                    member,
                )
            writer.writestr(info, member)
    return target.getvalue()


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cell_value(value: object) -> object:
    if isinstance(value, (dict, list, tuple)):
        return str(value)
    return value
