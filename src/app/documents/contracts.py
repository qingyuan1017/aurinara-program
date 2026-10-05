"""Versioned, manually authored Documents content contracts."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class DocumentType(StrEnum):
    PROTOCOL = "protocol"
    PROTOCOL_AMENDMENT = "protocol_amendment_summary_of_change"
    PROTOCOL_DEVIATION_DOCUMENT = "protocol_deviation_document"
    AGGREGATE_STUDY_RISK_PROFILE = "aggregate_study_risk_profile"
    DATA_MANAGEMENT_PLAN = "data_management_plan"
    SAP = "statistical_analysis_plan"
    MONITORING_SETUP = "centralized_monitoring_platform_setup_documentation"
    PROTOCOL_DEVIATION_DATASET = "protocol_deviation_dataset"
    AGGREGATE_STUDY_BRIEF = "aggregate_study_brief"
    STUDY_DATA_SUMMARY = "study_data_summary"
    QUALITY_QE_DETAILS = "standard_quality_dashboard_qe_details"
    QUALITY_SQE_AUDIT_CAPA = "standard_quality_dashboard_sqe_audit_capa_details"
    QUALITY_AUDIT_OBSERVATION = "standard_quality_dashboard_audit_observation_detail"
    SIGNALS_REPORT = "signals_report"
    ACTIONS_REPORT = "actions_report"


WORKBOOK_DOCUMENT_TYPES = frozenset(
    {
        DocumentType.PROTOCOL_DEVIATION_DATASET,
        DocumentType.QUALITY_QE_DETAILS,
        DocumentType.QUALITY_SQE_AUDIT_CAPA,
        DocumentType.QUALITY_AUDIT_OBSERVATION,
        DocumentType.SIGNALS_REPORT,
        DocumentType.ACTIONS_REPORT,
    }
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentParagraph(StrictModel):
    text: str = Field(min_length=1)
    style: Literal["body", "note", "warning"] = "body"


class DocumentTable(StrictModel):
    headers: tuple[str, ...] = Field(min_length=1)
    rows: tuple[tuple[str, ...], ...] = ()

    @model_validator(mode="after")
    def validate_width(self) -> "DocumentTable":
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("every table row must match the header width")
        return self


class DocumentSection(StrictModel):
    section_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    heading: str = Field(min_length=1, max_length=500)
    paragraphs: tuple[DocumentParagraph, ...] = ()
    bullets: tuple[str, ...] = ()
    tables: tuple[DocumentTable, ...] = ()


class DocumentCover(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    subtitle: str | None = None
    document_code: str
    version: str
    effective_date: date | None = None


class RenderDocument(StrictModel):
    """Renderer-neutral narrative document."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    cover: DocumentCover
    sections: tuple[DocumentSection, ...]


class NarrativeSection(StrictModel):
    section_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    heading: str = Field(min_length=1, max_length=500)
    paragraphs: tuple[str, ...] = Field(min_length=1)


class RelatedRecord(StrictModel):
    document_id: UUID
    document_revision: int = Field(ge=1)
    relationship: str = Field(min_length=1, max_length=64)


class NarrativeContent(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    title: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=64)
    effective_date: date | None = None
    sections: tuple[NarrativeSection, ...] = Field(min_length=1)
    related_records: tuple[RelatedRecord, ...] = ()

    @model_validator(mode="after")
    def unique_sections(self) -> "NarrativeContent":
        ids = [item.section_id for item in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("section_id values must be unique")
        return self


class ProtocolContent(NarrativeContent):
    document_type: Literal["protocol"] = "protocol"


class ProtocolAmendmentContent(NarrativeContent):
    document_type: Literal["protocol_amendment_summary_of_change"]
    amendment_number: str = Field(min_length=1)


class ProtocolDeviationDocumentContent(NarrativeContent):
    document_type: Literal["protocol_deviation_document"]


class AggregateStudyRiskProfileContent(NarrativeContent):
    document_type: Literal["aggregate_study_risk_profile"]


class DataManagementPlanContent(NarrativeContent):
    document_type: Literal["data_management_plan"]


class MonitoringSetupContent(NarrativeContent):
    document_type: Literal["centralized_monitoring_platform_setup_documentation"]


class AggregateStudyBriefContent(NarrativeContent):
    document_type: Literal["aggregate_study_brief"]


class StudyDataSummaryContent(NarrativeContent):
    document_type: Literal["study_data_summary"]


class SapNamedItem(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    protocol_entity_ids: tuple[str, ...] = ()


class SapEstimand(SapNamedItem):
    population_id: str
    treatment_condition: str = Field(min_length=1)
    variable: str = Field(min_length=1)
    intercurrent_event_strategy: str = Field(min_length=1)
    summary_measure: str = Field(min_length=1)


class SapCitation(StrictModel):
    citation_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    title: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    section_ids: tuple[str, ...] = Field(min_length=1)


class SapAssumption(SapNamedItem):
    material: bool = False
    resolution_status: Literal["open", "resolved"] = "open"


class StatisticalAnalysisPlanContent(StrictModel):
    document_type: Literal["statistical_analysis_plan"]
    schema_version: Literal["1.0.0"] = "1.0.0"
    title: str = Field(min_length=1)
    version: str = Field(min_length=1)
    effective_date: date | None = None
    protocol_alignment: tuple[SapNamedItem, ...] = Field(min_length=1)
    objectives: tuple[SapNamedItem, ...] = Field(min_length=1)
    endpoints: tuple[SapNamedItem, ...] = Field(min_length=1)
    estimands: tuple[SapEstimand, ...] = Field(min_length=1)
    populations: tuple[SapNamedItem, ...] = Field(min_length=1)
    methods: tuple[SapNamedItem, ...] = Field(min_length=1)
    multiplicity: tuple[SapNamedItem, ...] = ()
    missing_data: tuple[SapNamedItem, ...] = Field(min_length=1)
    sensitivity_analyses: tuple[SapNamedItem, ...] = ()
    output_requirements: tuple[SapNamedItem, ...] = Field(min_length=1)
    assumptions: tuple[SapAssumption, ...] = ()
    qc_items: tuple[SapNamedItem, ...] = Field(min_length=1)
    narrative_sections: tuple[NarrativeSection, ...] = Field(min_length=1)
    citations: tuple[SapCitation, ...] = ()


class WorkbookRow(StrictModel):
    row_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    description: str = Field(min_length=1)
    category: str = Field(min_length=1)
    status: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    related_document_id: UUID | None = None
    occurred_on: date | None = None
    due_on: date | None = None
    notes: str | None = None


class ProtocolDeviationRow(WorkbookRow):
    subject_id: str | None = None
    site_id: str | None = None
    protocol_section: str | None = None


class QualityEventRow(WorkbookRow):
    severity: str | None = None
    root_cause: str | None = None


class CapaRow(QualityEventRow):
    corrective_action: str | None = None
    preventive_action: str | None = None


class AuditObservationRow(QualityEventRow):
    observation: str = Field(min_length=1)


class SignalRow(WorkbookRow):
    signal_type: str = Field(min_length=1)
    impact: str | None = None


class ActionRow(WorkbookRow):
    action_type: str = Field(min_length=1)


class WorkbookContentBase(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: str
    title: str = Field(min_length=1)
    rows: tuple[WorkbookRow, ...] = ()


class ProtocolDeviationDatasetContent(WorkbookContentBase):
    document_type: Literal["protocol_deviation_dataset"]
    rows: tuple[ProtocolDeviationRow, ...]


class QualityQeDetailsContent(WorkbookContentBase):
    document_type: Literal["standard_quality_dashboard_qe_details"]
    rows: tuple[QualityEventRow, ...]


class QualitySqeAuditCapaContent(WorkbookContentBase):
    document_type: Literal["standard_quality_dashboard_sqe_audit_capa_details"]
    rows: tuple[CapaRow, ...]


class QualityAuditObservationContent(WorkbookContentBase):
    document_type: Literal["standard_quality_dashboard_audit_observation_detail"]
    rows: tuple[AuditObservationRow, ...]


class SignalsReportContent(WorkbookContentBase):
    document_type: Literal["signals_report"]
    rows: tuple[SignalRow, ...]


class ActionsReportContent(WorkbookContentBase):
    document_type: Literal["actions_report"]
    rows: tuple[ActionRow, ...]


DocumentContentContract = Annotated[
    ProtocolContent
    | ProtocolAmendmentContent
    | ProtocolDeviationDocumentContent
    | AggregateStudyRiskProfileContent
    | DataManagementPlanContent
    | StatisticalAnalysisPlanContent
    | MonitoringSetupContent
    | ProtocolDeviationDatasetContent
    | AggregateStudyBriefContent
    | StudyDataSummaryContent
    | QualityQeDetailsContent
    | QualitySqeAuditCapaContent
    | QualityAuditObservationContent
    | SignalsReportContent
    | ActionsReportContent,
    Field(discriminator="document_type"),
]

CONTENT_ADAPTER: TypeAdapter[DocumentContentContract] = TypeAdapter(DocumentContentContract)


class UsdmEntity(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    entity_type: Literal[
        "study",
        "objective",
        "endpoint",
        "arm",
        "epoch",
        "intervention",
        "eligibility",
        "schedule",
        "amendment",
    ]
    code: str | None = None
    name: str = Field(min_length=1)
    description: str | None = None


class UsdmRelationship(StrictModel):
    relationship_type: str = Field(min_length=1, max_length=64)
    source_entity_id: str
    target_entity_id: str


class UsdmDocument(StrictModel):
    """Pinned platform subset for USDM JSON authored by a user."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    usdm_version: str = Field(min_length=1)
    study_version: str = Field(min_length=1)
    entities: tuple[UsdmEntity, ...] = Field(min_length=1)
    relationships: tuple[UsdmRelationship, ...] = ()

    @model_validator(mode="after")
    def validate_relationships(self) -> "UsdmDocument":
        ids = [item.id for item in self.entities]
        if len(ids) != len(set(ids)):
            raise ValueError("USDM entity IDs must be unique")
        known = set(ids)
        for relationship in self.relationships:
            if (
                relationship.source_entity_id not in known
                or relationship.target_entity_id not in known
            ):
                raise ValueError("USDM relationships must reference existing entity IDs")
        return self


class EvidenceRegion(StrictModel):
    coordinate_system: Literal["pdf_points_top_left"] = "pdf_points_top_left"
    page_width: float = Field(gt=0)
    page_height: float = Field(gt=0)
    rectangle: tuple[float, float, float, float] | None = None
    polygon: tuple[tuple[float, float], ...] | None = None

    @model_validator(mode="after")
    def validate_geometry(self) -> "EvidenceRegion":
        if (self.rectangle is None) == (self.polygon is None):
            raise ValueError("provide exactly one rectangle or polygon")
        points: tuple[tuple[float, float], ...]
        if self.rectangle is not None:
            x, y, width, height = self.rectangle
            if width <= 0 or height <= 0:
                raise ValueError("evidence rectangle width and height must be positive")
            points = ((x, y), (x + width, y + height))
        else:
            assert self.polygon is not None
            if len(self.polygon) < 3:
                raise ValueError("evidence polygon must have at least three points")
            points = self.polygon
        if any(x < 0 or y < 0 or x > self.page_width or y > self.page_height for x, y in points):
            raise ValueError("evidence coordinates must be within the declared page")
        return self


def validate_content(document_type: str, payload: object) -> DocumentContentContract:
    """Validate one exact type-specific content payload."""

    if not isinstance(payload, dict):
        raise ValueError("document content must be a JSON object")
    value = dict(payload)
    value.setdefault("document_type", document_type)
    if value["document_type"] != document_type:
        raise ValueError("content document_type does not match the aggregate")
    return CONTENT_ADAPTER.validate_python(value)
