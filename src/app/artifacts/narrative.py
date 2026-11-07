"""Renderer-neutral narrative contracts and deterministic DOCX/PDF renderers."""

import io
from datetime import UTC, date, datetime
from typing import Any, Literal

from docx import Document as DocxDocument
from docx.shared import Inches, Pt
from pydantic import BaseModel, ConfigDict, Field, model_validator
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

from app.common.zip_normalization import normalize_zip_bytes

RENDERER_VERSION = "1.0.0"
_FIXED_TIME = datetime(2000, 1, 1, tzinfo=UTC)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentParagraph(_StrictModel):
    text: str = Field(min_length=1)
    style: Literal["body", "note", "warning"] = "body"


class DocumentTable(_StrictModel):
    headers: tuple[str, ...] = Field(min_length=1)
    rows: tuple[tuple[str, ...], ...] = ()

    @model_validator(mode="after")
    def validate_width(self) -> "DocumentTable":
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("every table row must match the header width")
        return self


class DocumentSection(_StrictModel):
    section_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    heading: str = Field(min_length=1, max_length=500)
    paragraphs: tuple[DocumentParagraph, ...] = ()
    bullets: tuple[str, ...] = ()
    tables: tuple[DocumentTable, ...] = ()


class DocumentCover(_StrictModel):
    title: str = Field(min_length=1, max_length=500)
    subtitle: str | None = None
    document_code: str
    version: str
    effective_date: date | None = None


class RenderDocument(_StrictModel):
    """Stable representation shared by narrative artifact builders."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    cover: DocumentCover
    sections: tuple[DocumentSection, ...]


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
    return normalize_zip_bytes(output.getvalue())


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
            flow.append(Paragraph(f"&#8226; {_escape(bullet)}", styles["BodyText"]))
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


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
