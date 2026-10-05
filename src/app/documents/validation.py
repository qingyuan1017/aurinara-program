"""Clinical-document contract and relationship validation without content inference."""

from collections.abc import Iterable
from uuid import UUID, uuid5

from app.documents.contracts import (
    DocumentContentContract,
    NarrativeContent,
    ProtocolContent,
    StatisticalAnalysisPlanContent,
    UsdmDocument,
    WorkbookContentBase,
)
from app.validation.contracts import IssueSeverity, ValidationIssue

_ISSUE_NAMESPACE = UUID("ea6fa6a4-2d9c-4a9a-8ab3-c827f29b52b4")


def validate_document(
    *,
    document_id: UUID,
    content: DocumentContentContract | None,
    usdm: UsdmDocument | None = None,
    evidence_entity_ids: Iterable[str] = (),
    protocol_entity_ids: Iterable[str] = (),
    related_document_ids: Iterable[UUID] = (),
) -> tuple[ValidationIssue, ...]:
    """Validate completeness and exact authored references for one revision."""

    issues: list[ValidationIssue] = []
    if content is None:
        issues.append(
            _issue(
                document_id,
                "document_content_missing",
                "content",
                "Document content is missing.",
            )
        )
        return tuple(issues)
    if isinstance(content, NarrativeContent):
        headings = {section.section_id for section in content.sections}
        if len(headings) != len(content.sections):
            issues.append(
                _issue(
                    document_id,
                    "duplicate_section_id",
                    "content.sections",
                    "Document section identifiers must be unique.",
                )
            )
    if isinstance(content, ProtocolContent) and usdm is None:
        issues.append(
            _issue(
                document_id,
                "protocol_usdm_missing",
                "usdm",
                "Protocol USDM content is missing.",
            )
        )
    if isinstance(content, WorkbookContentBase):
        rows = list(content.rows)
        row_ids = [row.row_id for row in rows]
        if len(row_ids) != len(set(row_ids)):
            issues.append(
                _issue(
                    document_id,
                    "duplicate_row_id",
                    "content.rows",
                    "Workbook row identifiers must be unique.",
                )
            )
        allowed_related = set(related_document_ids)
        for index, row in enumerate(rows):
            if (
                row.related_document_id is not None
                and row.related_document_id not in allowed_related
            ):
                issues.append(
                    _issue(
                        document_id,
                        "related_document_not_selected",
                        f"content.rows.{index}.related_document_id",
                        "The referenced document is not in the aggregate's explicit related "
                        "documents.",
                    )
                )
    if isinstance(content, StatisticalAnalysisPlanContent):
        if not set(protocol_entity_ids):
            issues.append(
                _issue(
                    document_id,
                    "sap_protocol_context_missing",
                    "related_document_ids",
                    "The SAP requires an explicitly selected Protocol with saved USDM.",
                )
            )
        population_ids = {item.id for item in content.populations}
        for index, estimand in enumerate(content.estimands):
            if estimand.population_id not in population_ids:
                issues.append(
                    _issue(
                        document_id,
                        "estimand_population_unresolved",
                        f"content.estimands.{index}.population_id",
                        "The estimand population does not resolve within the SAP.",
                    )
                )
        known_protocol = set(protocol_entity_ids)
        for group_name in ("protocol_alignment", "objectives", "endpoints", "estimands", "methods"):
            for index, item in enumerate(getattr(content, group_name)):
                for entity_id in item.protocol_entity_ids:
                    if entity_id not in known_protocol:
                        issues.append(
                            _issue(
                                document_id,
                                "protocol_reference_unresolved",
                                f"content.{group_name}.{index}.protocol_entity_ids",
                                f"Protocol entity '{entity_id}' does not exist in the linked "
                                "revision.",
                            )
                        )
        section_ids = {item.section_id for item in content.narrative_sections}
        for index, citation in enumerate(content.citations):
            if any(section_id not in section_ids for section_id in citation.section_ids):
                issues.append(
                    _issue(
                        document_id,
                        "citation_section_unresolved",
                        f"content.citations.{index}.section_ids",
                        "The citation references a missing narrative section.",
                    )
                )
        for index, assumption in enumerate(content.assumptions):
            if assumption.material and assumption.resolution_status != "resolved":
                issues.append(
                    _issue(
                        document_id,
                        "material_assumption_unresolved",
                        f"content.assumptions.{index}.resolution_status",
                        "A material assumption remains unresolved.",
                    )
                )
    if usdm is not None:
        covered = set(evidence_entity_ids)
        for entity in usdm.entities:
            if entity.entity_type in {"objective", "endpoint"} and entity.id not in covered:
                issues.append(
                    _issue(
                        document_id,
                        "protocol_evidence_missing",
                        f"usdm.entities.{entity.id}",
                        f"Protocol {entity.entity_type} '{entity.id}' has no evidence region.",
                        severity=IssueSeverity.WARNING,
                    )
                )
    return tuple(issues)


def _issue(
    entity_id: UUID,
    code: str,
    field_path: str,
    message: str,
    *,
    severity: IssueSeverity = IssueSeverity.ERROR,
) -> ValidationIssue:
    return ValidationIssue(
        id=uuid5(_ISSUE_NAMESPACE, f"{entity_id}:{code}:{field_path}"),
        code=code,
        severity=severity,
        message=message,
        suggestion="Correct the authored value and validate a new immutable revision.",
        module="documents",
        entity_type="document",
        entity_id=entity_id,
        field_path=field_path,
    )
