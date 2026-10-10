"""Documents application service and registered capability implementation."""

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID, uuid5

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact, SourceFile
from app.artifacts.storage import ObjectStorage
from app.common.asset_content import read_verified_asset_json_object
from app.common.canonical import fingerprint
from app.common.problems import ProblemException
from app.common.repository_assets import verify_repository_asset
from app.documents.contracts import (
    DocumentContentContract,
    DocumentCover,
    DocumentParagraph,
    DocumentSection,
    DocumentTable,
    DocumentType,
    EvidenceRegion,
    RenderDocument,
    StatisticalAnalysisPlanContent,
    UsdmDocument,
    WorkbookContentBase,
    validate_content,
)
from app.documents.models import (
    Document,
    DocumentContent,
    ProtocolEvidence,
    ProtocolUsdmDocument,
)
from app.documents.rendering import (
    RENDERER_VERSION,
    content_to_document,
    render_docx,
    render_pdf,
    render_xlsx,
)
from app.kernel.dependencies import RenderedArtifact, SqlDependencyCapability
from app.packaging.contracts import PackageContribution
from app.templates.models import TemplateVersion
from app.validation.models import ValidationRun

ENTITY_NAMESPACE = UUID("5c5980e8-ee30-43ba-8b9a-6c589857e118")

DOCUMENT_ARTIFACT_TYPES = (
    "documents_dependency_manifest",
    "protocol_original",
    "protocol_usdm",
    "protocol_summary_docx",
    "protocol_summary_pdf",
    "protocol_annotated_evidence",
    "protocol_evidence_manifest_json",
    "protocol_evidence_manifest_csv",
    "protocol_amendment_summary_of_change_pdf",
    "protocol_deviation_document_pdf",
    "aggregate_study_risk_profile_pdf",
    "data_management_plan_pdf",
    "statistical_analysis_plan_structured_content_json",
    "statistical_analysis_plan_docx",
    "statistical_analysis_plan_pdf",
    "centralized_monitoring_platform_setup_documentation_pdf",
    "protocol_deviation_dataset_xlsx",
    "aggregate_study_brief_pdf",
    "study_data_summary_pdf",
    "standard_quality_dashboard_qe_details_xlsx",
    "standard_quality_dashboard_sqe_audit_capa_details_xlsx",
    "standard_quality_dashboard_audit_observation_detail_xlsx",
    "signals_report_xlsx",
    "actions_report_xlsx",
    "document_citation_report_json",
    "document_citation_report_csv",
    "document_validation_report_json",
    "document_validation_report_pdf",
)

PRIMARY_ARTIFACT = {
    DocumentType.PROTOCOL_AMENDMENT: "protocol_amendment_summary_of_change_pdf",
    DocumentType.PROTOCOL_DEVIATION_DOCUMENT: "protocol_deviation_document_pdf",
    DocumentType.AGGREGATE_STUDY_RISK_PROFILE: "aggregate_study_risk_profile_pdf",
    DocumentType.DATA_MANAGEMENT_PLAN: "data_management_plan_pdf",
    DocumentType.MONITORING_SETUP: "centralized_monitoring_platform_setup_documentation_pdf",
    DocumentType.PROTOCOL_DEVIATION_DATASET: "protocol_deviation_dataset_xlsx",
    DocumentType.AGGREGATE_STUDY_BRIEF: "aggregate_study_brief_pdf",
    DocumentType.STUDY_DATA_SUMMARY: "study_data_summary_pdf",
    DocumentType.QUALITY_QE_DETAILS: "standard_quality_dashboard_qe_details_xlsx",
    DocumentType.QUALITY_SQE_AUDIT_CAPA: "standard_quality_dashboard_sqe_audit_capa_details_xlsx",
    DocumentType.QUALITY_AUDIT_OBSERVATION: (
        "standard_quality_dashboard_audit_observation_detail_xlsx"
    ),
    DocumentType.SIGNALS_REPORT: "signals_report_xlsx",
    DocumentType.ACTIONS_REPORT: "actions_report_xlsx",
}

ALLOWED_BY_TYPE: dict[DocumentType, frozenset[str]] = {
    DocumentType.PROTOCOL: frozenset(
        {
            "documents_dependency_manifest",
            "protocol_original",
            "protocol_usdm",
            "protocol_summary_docx",
            "protocol_summary_pdf",
            "protocol_annotated_evidence",
            "protocol_evidence_manifest_json",
            "protocol_evidence_manifest_csv",
            "document_citation_report_json",
            "document_citation_report_csv",
            "document_validation_report_json",
            "document_validation_report_pdf",
        }
    ),
    DocumentType.SAP: frozenset(
        {
            "documents_dependency_manifest",
            "statistical_analysis_plan_structured_content_json",
            "statistical_analysis_plan_docx",
            "statistical_analysis_plan_pdf",
            "document_citation_report_json",
            "document_citation_report_csv",
            "document_validation_report_json",
            "document_validation_report_pdf",
        }
    ),
    **{
        document_type: frozenset(
            {
                "documents_dependency_manifest",
                artifact_type,
                "document_citation_report_json",
                "document_citation_report_csv",
                "document_validation_report_json",
                "document_validation_report_pdf",
            }
        )
        for document_type, artifact_type in PRIMARY_ARTIFACT.items()
    },
}

FILENAMES = {
    "protocol_original": "protocol.pdf",
    "protocol_usdm": "protocol-usdm.json",
    "protocol_summary_docx": "protocol-summary.docx",
    "protocol_summary_pdf": "protocol-summary.pdf",
    "protocol_annotated_evidence": "protocol-annotated-evidence.pdf",
    "protocol_evidence_manifest_json": "protocol-evidence.json",
    "protocol_evidence_manifest_csv": "protocol-evidence.csv",
    "protocol_amendment_summary_of_change_pdf": "protocol-amendment-summary-of-change.pdf",
    "protocol_deviation_document_pdf": "protocol-deviation-document.pdf",
    "aggregate_study_risk_profile_pdf": "aggregate-study-risk-profile.pdf",
    "data_management_plan_pdf": "data-management-plan.pdf",
    "statistical_analysis_plan_structured_content_json": "statistical-analysis-plan.json",
    "statistical_analysis_plan_docx": "statistical-analysis-plan.docx",
    "statistical_analysis_plan_pdf": "statistical-analysis-plan.pdf",
    "centralized_monitoring_platform_setup_documentation_pdf": (
        "centralized-monitoring-platform-setup-documentation.pdf"
    ),
    "protocol_deviation_dataset_xlsx": "protocol-deviation-dataset.xlsx",
    "aggregate_study_brief_pdf": "aggregate-study-brief.pdf",
    "study_data_summary_pdf": "study-data-summary.pdf",
    "standard_quality_dashboard_qe_details_xlsx": "standard-quality-dashboard-qe-details.xlsx",
    "standard_quality_dashboard_sqe_audit_capa_details_xlsx": (
        "standard-quality-dashboard-sqe-audit-capa-details.xlsx"
    ),
    "standard_quality_dashboard_audit_observation_detail_xlsx": (
        "standard-quality-dashboard-audit-observation-detail.xlsx"
    ),
    "signals_report_xlsx": "signals-report.xlsx",
    "actions_report_xlsx": "actions-report.xlsx",
}

TEMPLATE_CONTROLLED_SUFFIXES = ("_docx", "_pdf", "_xlsx")
SOURCE_SPECIFIC_ARTIFACTS = frozenset({"protocol_original", "protocol_annotated_evidence"})

REQUIRED_PACKAGE_ARTIFACTS: dict[DocumentType, frozenset[str]] = {
    DocumentType.PROTOCOL: frozenset(
        {
            "protocol_original",
            "protocol_usdm",
            "protocol_summary_docx",
            "protocol_summary_pdf",
            "protocol_annotated_evidence",
            "protocol_evidence_manifest_json",
            "protocol_evidence_manifest_csv",
        }
    ),
    DocumentType.SAP: frozenset(
        {
            "statistical_analysis_plan_structured_content_json",
            "statistical_analysis_plan_docx",
            "statistical_analysis_plan_pdf",
        }
    ),
    **{
        document_type: frozenset({artifact_type})
        for document_type, artifact_type in PRIMARY_ARTIFACT.items()
    },
}


@dataclass(frozen=True, slots=True)
class DocumentsCapability(SqlDependencyCapability):
    """Documents-owned dependency, artifact, context, and entity capability."""

    def package_contributions(
        self,
        session: Session,
        study_id: UUID,
        artifacts: tuple[Artifact, ...],
        options: dict[str, object],
    ) -> tuple[PackageContribution, ...]:
        """Apply explicit per-document-type completeness before assigning paths."""

        selected_types = options.get("document_types")
        if (
            set(options) - {"schema_version", "document_types"}
            or not isinstance(selected_types, list)
            or not selected_types
        ):
            raise ProblemException(
                status_code=422,
                code="documents_package_options_invalid",
                title="Documents package options are invalid",
                detail="Select a non-empty document_types list and no arbitrary options.",
            )
        document_types = {str(value) for value in selected_types}
        try:
            for value in document_types:
                DocumentType(value)
        except ValueError as error:
            raise ProblemException(
                status_code=422,
                code="documents_package_type_invalid",
                title="Documents package type is invalid",
                detail="Every selected document type must be registered by Documents.",
            ) from error
        observed: dict[DocumentType, dict[UUID, set[str]]] = {
            DocumentType(value): {} for value in document_types
        }
        documents: dict[UUID, Document] = {}
        for artifact in artifacts:
            document = session.get(Document, artifact.owner_id)
            if document is None or document.study_id != study_id:
                raise ProblemException(
                    status_code=422,
                    code="documents_package_artifact_invalid",
                    title="Documents package artifact is invalid",
                    detail="Every selected artifact must be owned by a document in this study.",
                )
            if document.document_type not in document_types:
                raise ProblemException(
                    status_code=422,
                    code="documents_package_artifact_unselected",
                    title="Documents package artifact is not selected",
                    detail="Every document artifact must match an explicit document_types value.",
                )
            document_type = DocumentType(document.document_type)
            if artifact.artifact_type not in ALLOWED_BY_TYPE[document_type]:
                raise ProblemException(
                    status_code=422,
                    code="documents_package_artifact_invalid",
                    title="Documents package artifact is invalid",
                    detail="An artifact is not valid for its owning document type.",
                )
            documents[document.id] = document
            observed[document_type].setdefault(document.id, set()).add(artifact.artifact_type)
        missing = sorted(value.value for value, owners in observed.items() if not owners)
        if missing:
            raise ProblemException(
                status_code=422,
                code="documents_package_incomplete",
                title="Documents package selection is incomplete",
                detail=f"Select required artifacts for: {', '.join(missing)}.",
            )
        for document_type, owners in observed.items():
            required = REQUIRED_PACKAGE_ARTIFACTS[document_type]
            for document_id, artifact_types in owners.items():
                missing_artifacts = sorted(required - artifact_types)
                if missing_artifacts:
                    document = documents[document_id]
                    raise ProblemException(
                        status_code=422,
                        code="documents_package_incomplete",
                        title="Documents package selection is incomplete",
                        detail=(
                            f"Document '{document.code}' is missing required artifacts: "
                            f"{', '.join(missing_artifacts)}."
                        ),
                    )
        validated = SqlDependencyCapability.package_contributions(
            self, session, study_id, artifacts, {}
        )
        artifacts_by_id = {artifact.id: artifact for artifact in artifacts}
        contributions: list[PackageContribution] = []
        for item in validated:
            artifact = artifacts_by_id[item.artifact_id]
            document = documents[artifact.owner_id]
            safe_code = "".join(
                character if character.isalnum() or character in "_-" else "-"
                for character in document.code
            ).strip("-")
            suffix = Path(artifact.filename).suffix.lower()
            contributions.append(
                PackageContribution(
                    artifact_id=artifact.id,
                    archive_path=(
                        f"documents/{document.document_type}/{safe_code or document.id.hex}/"
                        f"{artifact.artifact_type}{suffix}"
                    ),
                )
            )
        return tuple(contributions)

    def latest_content(self, session: Session, document_id: UUID) -> DocumentContent | None:
        return session.scalar(
            select(DocumentContent)
            .where(DocumentContent.document_id == document_id)
            .order_by(DocumentContent.revision.desc())
            .limit(1)
        )

    def latest_usdm(self, session: Session, document_id: UUID) -> ProtocolUsdmDocument | None:
        return session.scalar(
            select(ProtocolUsdmDocument)
            .where(ProtocolUsdmDocument.document_id == document_id)
            .order_by(ProtocolUsdmDocument.revision.desc())
            .limit(1)
        )

    def resolve_entity(self, session: Session, entity_type: str, entity_id: UUID) -> UUID | None:
        if entity_type == "document":
            return SqlDependencyCapability.resolve_entity(self, session, entity_type, entity_id)
        evidence = session.get(ProtocolEvidence, entity_id)
        if entity_type == "protocol_evidence" and evidence is not None:
            return evidence.study_id
        if entity_type not in {
            "protocol_objective",
            "protocol_endpoint",
            "sap_objective",
            "sap_endpoint",
            "sap_estimand",
            "sap_population",
            "sap_method",
            "document_record",
        }:
            return None
        for document in session.scalars(select(Document)):
            for endpoint_type, endpoint_id in self.entity_endpoints(session, document):
                if endpoint_type == entity_type and endpoint_id == entity_id:
                    return document.study_id
        return None

    def entity_endpoints(
        self, session: Session, document: Document
    ) -> tuple[tuple[str, UUID], ...]:
        endpoints: list[tuple[str, UUID]] = []
        if document.document_type == DocumentType.PROTOCOL:
            record = self.latest_usdm(session, document.id)
            if record is not None:
                usdm = UsdmDocument.model_validate(record.payload)
                for item in usdm.entities:
                    if item.entity_type in {"objective", "endpoint"}:
                        endpoints.append(
                            (
                                f"protocol_{item.entity_type}",
                                stable_entity_id(document.id, item.entity_type, item.id),
                            )
                        )
        content_record = self.latest_content(session, document.id)
        if content_record is not None:
            content = validate_content(document.document_type, content_record.payload)
            if isinstance(content, StatisticalAnalysisPlanContent):
                for objective in content.objectives:
                    endpoints.append(
                        (
                            "sap_objective",
                            stable_entity_id(document.id, "objective", objective.id),
                        )
                    )
                for endpoint in content.endpoints:
                    endpoints.append(
                        (
                            "sap_endpoint",
                            stable_entity_id(document.id, "endpoint", endpoint.id),
                        )
                    )
                for estimand in content.estimands:
                    endpoints.append(
                        (
                            "sap_estimand",
                            stable_entity_id(document.id, "estimand", estimand.id),
                        )
                    )
                for population in content.populations:
                    endpoints.append(
                        (
                            "sap_population",
                            stable_entity_id(document.id, "population", population.id),
                        )
                    )
                for method in content.methods:
                    endpoints.append(
                        ("sap_method", stable_entity_id(document.id, "method", method.id))
                    )
            if isinstance(content, WorkbookContentBase):
                for row in content.rows:
                    endpoints.append(
                        (
                            "document_record",
                            stable_entity_id(document.id, "row", row.row_id),
                        )
                    )
        return tuple(endpoints)

    def build_artifact_payload(
        self, session: Session, aggregate_id: UUID, study_id: UUID, artifact_type: str
    ) -> dict[str, object]:
        if artifact_type == "documents_dependency_manifest":
            payload = SqlDependencyCapability.build_artifact_payload(
                self, session, aggregate_id, study_id, artifact_type
            )
            payload["artifact_type"] = artifact_type
            return payload
        document = cast(Document, self.require(session, aggregate_id, study_id))
        document_type = DocumentType(document.document_type)
        if artifact_type not in ALLOWED_BY_TYPE[document_type]:
            raise ProblemException(
                status_code=422,
                code="artifact_type_unsupported",
                title="Artifact type is unsupported",
                detail=f"'{artifact_type}' is not valid for '{document.document_type}'.",
            )
        selection = self.get_selection(session, aggregate_id, study_id)
        if selection.state != "current":
            raise ProblemException(
                status_code=409,
                code="dependency_refresh_required",
                title="Dependency refresh is required",
                detail="Refresh or reaffirm the exact dependency selection first.",
            )
        content_record = self.latest_content(session, document.id)
        usdm_record = self.latest_usdm(session, document.id)
        evidence = tuple(
            session.scalars(
                select(ProtocolEvidence)
                .where(ProtocolEvidence.document_id == document.id)
                .order_by(ProtocolEvidence.page_number, ProtocolEvidence.id)
            )
        )
        related_documents = related_document_snapshot(session, document, self)
        exact_input = document_input_snapshot(
            document,
            content_record,
            usdm_record,
            evidence,
            selection.fingerprint,
            related_documents,
        )
        validation = session.scalar(
            select(ValidationRun)
            .where(
                ValidationRun.owner_type == "document",
                ValidationRun.owner_id == document.id,
                ValidationRun.input_fingerprint == fingerprint(exact_input),
                ValidationRun.status == "succeeded",
            )
            .order_by(ValidationRun.created_at.desc())
            .limit(1)
        )
        if validation is None and artifact_type not in {
            "protocol_original",
            "protocol_usdm",
            "statistical_analysis_plan_structured_content_json",
        }:
            raise ProblemException(
                status_code=409,
                code="successful_validation_required",
                title="Successful validation is required",
                detail="Validate these exact document inputs before building this artifact.",
            )
        if (
            artifact_type.endswith(TEMPLATE_CONTROLLED_SUFFIXES)
            and artifact_type not in SOURCE_SPECIFIC_ARTIFACTS
        ):
            selected_templates = [
                item for item in selection.templates if item.artifact_type == artifact_type
            ]
            if len(selected_templates) != 1:
                raise ProblemException(
                    status_code=409,
                    code="artifact_template_selection_required",
                    title="Exact artifact template is required",
                    detail=(
                        "Select exactly one compatible Template version for this artifact type."
                    ),
                )
            version = session.get(TemplateVersion, selected_templates[0].template_version_id)
            if version is None:
                raise RuntimeError("validated Template version is missing")
            presentation_template_ref: dict[str, object] | None = {
                "checksum": version.checksum,
                "renderer_versions": version.renderer_versions,
                "asset_path": version.asset_path,
            }
        else:
            presentation_template_ref = None
        source_file = (
            session.get(SourceFile, document.source_pdf_file_id)
            if document.source_pdf_file_id is not None
            else None
        )
        manifest: dict[str, object] = {
            "schema_version": "1.0.0",
            "artifact_type": artifact_type,
            "document_id": str(document.id),
            "document_code": document.code,
            "document_type": document.document_type,
            "document_revision": document.revision,
            "content_revision": content_record.revision if content_record else None,
            "content_fingerprint": content_record.fingerprint if content_record else None,
            "usdm_revision": usdm_record.revision if usdm_record else None,
            "usdm_fingerprint": usdm_record.fingerprint if usdm_record else None,
            "source_file_id": str(source_file.id) if source_file else None,
            "source_file_sha256": source_file.sha256 if source_file else None,
            "validation_run_id": str(validation.id) if validation else None,
            "validation_counts": {
                "error": validation.error_count,
                "warning": validation.warning_count,
                "info": validation.info_count,
            }
            if validation
            else None,
            "validation_warnings": [
                item for item in validation.issues if item.get("severity") == "warning"
            ]
            if validation
            else [],
            "related_documents": related_documents,
            "dependency_selection_revision": selection.revision,
            "dependency_fingerprint": selection.fingerprint,
            "resolved_dependencies": self._resolve_manifest(session, selection),
            "renderer_version": RENDERER_VERSION,
        }
        return {
            "artifact_type": artifact_type,
            "dependency_selection": selection.model_dump(mode="json"),
            "manifest": manifest,
            "content": content_record.payload if content_record else None,
            "usdm": usdm_record.payload if usdm_record else None,
            "evidence": [evidence_payload(item) for item in evidence],
            "validation": {
                "id": str(validation.id),
                "issues": validation.issues,
                "counts": {
                    "error": validation.error_count,
                    "warning": validation.warning_count,
                    "info": validation.info_count,
                },
            }
            if validation
            else None,
            "presentation_template_ref": presentation_template_ref,
            "_source_object_key": source_file.object_key if source_file else None,
        }

    def render_artifact(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> RenderedArtifact:
        artifact_type = str(payload["artifact_type"])
        if artifact_type == "documents_dependency_manifest":
            return SqlDependencyCapability.render_artifact(self, payload, storage)
        manifest = cast(dict[str, object], payload["manifest"])
        code = str(manifest["document_code"])
        content_payload = payload.get("content")
        content = (
            validate_content(str(manifest["document_type"]), content_payload)
            if content_payload is not None
            else None
        )
        validation_id = manifest.get("validation_run_id")
        ref = cast(dict[str, object] | None, payload.get("presentation_template_ref"))
        presentation_template = (
            load_presentation_template(storage, ref) if ref is not None else None
        )
        if artifact_type == "protocol_original":
            data = self._source_bytes(payload, storage)
            media_type = "application/pdf"
        elif artifact_type == "protocol_annotated_evidence":
            data = annotate_evidence_pdf(
                self._source_bytes(payload, storage),
                cast(list[dict[str, object]], payload["evidence"]),
            )
            media_type = "application/pdf"
        elif artifact_type == "protocol_usdm":
            data = canonical_json_bytes(payload.get("usdm"))
            media_type = "application/json"
        elif artifact_type.startswith("protocol_evidence_manifest_"):
            evidence = cast(list[dict[str, object]], payload["evidence"])
            if artifact_type.endswith("_json"):
                data, media_type = canonical_json_bytes({"evidence": evidence}), "application/json"
            else:
                data, media_type = evidence_csv(evidence), "text/csv"
        elif artifact_type == "statistical_analysis_plan_structured_content_json":
            data, media_type = canonical_json_bytes(content_payload), "application/json"
        elif artifact_type.startswith("document_citation_report_"):
            citations = citation_rows(content)
            if artifact_type.endswith("_json"):
                data, media_type = (
                    canonical_json_bytes({"citations": citations}),
                    "application/json",
                )
            else:
                data, media_type = rows_csv(citations), "text/csv"
        elif artifact_type == "document_validation_report_json":
            data, media_type = canonical_json_bytes(payload.get("validation")), "application/json"
        elif artifact_type == "document_validation_report_pdf":
            data = render_pdf(
                validation_document(code, cast(dict[str, object], payload["validation"])),
                presentation_template,
            )
            media_type = "application/pdf"
        elif artifact_type.endswith("_xlsx"):
            if not isinstance(content, WorkbookContentBase):
                raise ValueError("XLSX artifact requires workbook content")
            data, media_type = (
                render_xlsx(content, presentation_template),
                ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            )
        elif artifact_type.endswith("_docx"):
            if content is None:
                raise ValueError("DOCX artifact requires content")
            data, media_type = (
                render_docx(content_to_document(code, content), presentation_template),
                ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            )
        elif artifact_type.endswith("_pdf"):
            if content is None:
                raise ValueError("PDF artifact requires content")
            data, media_type = (
                render_pdf(content_to_document(code, content), presentation_template),
                "application/pdf",
            )
        else:
            raise ValueError(f"no renderer for {artifact_type}")
        filename = FILENAMES.get(artifact_type, f"{code}-{artifact_type.rsplit('_', 1)[-1]}")
        return RenderedArtifact(
            data=data,
            filename=filename,
            media_type=media_type,
            manifest=manifest,
            validation_run_id=UUID(str(validation_id)) if validation_id else None,
        )

    @staticmethod
    def _source_bytes(payload: dict[str, object], storage: ObjectStorage) -> bytes:
        key = payload.get("_source_object_key")
        if not isinstance(key, str):
            raise ProblemException(
                status_code=409,
                code="protocol_source_pdf_required",
                title="Protocol source PDF is required",
                detail="Associate an immutable study PDF source file first.",
            )
        with storage.open(key) as source:
            return source.read()


def stable_entity_id(document_id: UUID, entity_type: str, natural_id: str) -> UUID:
    return uuid5(ENTITY_NAMESPACE, f"{document_id}:{entity_type}:{natural_id}")


def load_presentation_template(storage: ObjectStorage, ref: dict[str, object]) -> dict[str, object]:
    """Load and enforce the presentation-only boundary of one exact Template asset."""

    checksum = str(ref["checksum"])
    asset_path = str(ref["asset_path"])
    renderer_versions = cast(list[str], ref["renderer_versions"])
    local_fallback = (
        (
            lambda: verify_repository_asset(
                Path(__file__).resolve().parents[3],
                asset_path,
                checksum,
                allowed_root="templates",
            )[0]
        )
        if storage.local_fallback_enabled
        else None
    )
    value = read_verified_asset_json_object(storage, checksum, local_fallback=local_fallback)
    allowed_keys = {"schema_version", "renderer", "styles", "blank_structure"}
    if not set(value) <= allowed_keys:
        raise ProblemException(
            status_code=409,
            code="template_content_boundary_violation",
            title="Template contains unsupported content",
            detail="Templates may contain only presentation styles and blank structure.",
        )
    styles = value.get("styles")
    blank_structure = value.get("blank_structure")
    if (
        not isinstance(styles, dict)
        or any(
            not isinstance(key, str) or not isinstance(item, str) for key, item in styles.items()
        )
        or not isinstance(blank_structure, list)
        or any(not isinstance(item, str) for item in blank_structure)
    ):
        raise ProblemException(
            status_code=409,
            code="template_content_boundary_violation",
            title="Template contains unsupported content",
            detail="Template styles and blank structures must be presentation-only strings.",
        )
    if "document-1" not in renderer_versions or value.get("renderer") != "document-1":
        raise ProblemException(
            status_code=409,
            code="template_renderer_incompatible",
            title="Template renderer is incompatible",
            detail="The exact Template version does not support this renderer.",
        )
    return value


def document_input_snapshot(
    document: Document,
    content: DocumentContent | None,
    usdm: ProtocolUsdmDocument | None,
    evidence: tuple[ProtocolEvidence, ...],
    dependency_fingerprint: str,
    related_documents: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "document_id": str(document.id),
        "document_revision": document.revision,
        "document_type": document.document_type,
        "content_revision": content.revision if content else None,
        "content_fingerprint": content.fingerprint if content else None,
        "usdm_revision": usdm.revision if usdm else None,
        "usdm_fingerprint": usdm.fingerprint if usdm else None,
        "source_pdf_file_id": (
            str(document.source_pdf_file_id) if document.source_pdf_file_id else None
        ),
        "related_document_ids": document.related_document_ids,
        "related_documents": related_documents or [],
        "evidence": [{"id": str(item.id), "revision": item.revision} for item in evidence],
        "dependency_fingerprint": dependency_fingerprint,
    }


def related_document_snapshot(
    session: Session, document: Document, handler: DocumentsCapability
) -> list[dict[str, object]]:
    """Resolve exact related Documents without selecting a newer relationship implicitly."""

    resolved: list[dict[str, object]] = []
    for related_id in document.related_document_ids:
        related = session.get(Document, UUID(related_id))
        if related is None or related.study_id != document.study_id:
            raise ProblemException(
                status_code=409,
                code="related_document_unavailable",
                title="Related document is unavailable",
                detail="An explicitly selected related document no longer resolves in this study.",
            )
        content = handler.latest_content(session, related.id)
        usdm = handler.latest_usdm(session, related.id)
        resolved.append(
            {
                "document_id": str(related.id),
                "document_type": related.document_type,
                "document_revision": related.revision,
                "content_revision": content.revision if content else None,
                "content_fingerprint": content.fingerprint if content else None,
                "usdm_revision": usdm.revision if usdm else None,
                "usdm_fingerprint": usdm.fingerprint if usdm else None,
            }
        )
    return resolved


def evidence_payload(item: ProtocolEvidence) -> dict[str, object]:
    return {
        "id": str(item.id),
        "revision": item.revision,
        "source_pdf_file_id": str(item.source_pdf_file_id),
        "page_number": item.page_number,
        "region": item.region,
        "excerpt": item.excerpt,
        "linked_usdm_entity_ids": item.linked_usdm_entity_ids,
        "question": item.question,
        "resolution": item.resolution,
        "status": item.status,
    }


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def evidence_csv(rows: list[dict[str, object]]) -> bytes:
    flattened = [
        {
            "id": item["id"],
            "page_number": item["page_number"],
            "linked_usdm_entity_ids": "|".join(cast(list[str], item["linked_usdm_entity_ids"])),
            "status": item["status"],
            "excerpt": item["excerpt"],
            "question": item["question"],
            "resolution": item["resolution"],
        }
        for item in rows
    ]
    return rows_csv(flattened)


def rows_csv(rows: list[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    headers = list(rows[0]) if rows else ["id"]
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def citation_rows(content: DocumentContentContract | None) -> list[dict[str, object]]:
    if not isinstance(content, StatisticalAnalysisPlanContent):
        return []
    return [item.model_dump(mode="json") for item in content.citations]


def validation_document(code: str, validation: dict[str, object]) -> RenderDocument:
    counts = cast(dict[str, object], validation["counts"])
    issues = cast(list[dict[str, object]], validation["issues"])
    table = DocumentTable(
        headers=("Code", "Severity", "Message", "Field"),
        rows=tuple(
            (
                str(item["code"]),
                str(item["severity"]),
                str(item["message"]),
                str(item.get("field_path") or ""),
            )
            for item in issues
        ),
    )
    return RenderDocument(
        cover=DocumentCover(title="Document Validation Report", document_code=code, version="1.0"),
        sections=(
            DocumentSection(
                section_id="summary",
                heading="Summary",
                paragraphs=(
                    DocumentParagraph(
                        text=(
                            f"Errors: {counts['error']}; Warnings: {counts['warning']}; "
                            f"Information: {counts['info']}"
                        )
                    ),
                ),
            ),
            DocumentSection(section_id="issues", heading="Issues", tables=(table,)),
        ),
    )


def annotate_evidence_pdf(source: bytes, evidence: list[dict[str, object]]) -> bytes:
    reader = PdfReader(io.BytesIO(source))
    writer = PdfWriter()
    by_page: dict[int, list[dict[str, object]]] = {}
    for item in evidence:
        by_page.setdefault(int(str(item["page_number"])), []).append(item)
    for page_number, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        overlay_stream = io.BytesIO()
        canvas = Canvas(overlay_stream, pagesize=(width, height), invariant=1)
        canvas.setStrokeColorRGB(0.85, 0.1, 0.1)
        canvas.setLineWidth(1.5)
        for item in by_page.get(page_number, []):
            region = EvidenceRegion.model_validate(item["region"])
            if region.rectangle is not None:
                x, y, box_width, box_height = region.rectangle
                canvas.rect(x, height - y - box_height, box_width, box_height, stroke=1, fill=0)
            else:
                assert region.polygon is not None
                path = canvas.beginPath()
                first_x, first_y = region.polygon[0]
                path.moveTo(first_x, height - first_y)
                for x, y in region.polygon[1:]:
                    path.lineTo(x, height - y)
                path.close()
                canvas.drawPath(path, stroke=1, fill=0)
        canvas.save()
        overlay_stream.seek(0)
        overlay = PdfReader(overlay_stream).pages[0]
        writer.add_page(page)
        writer.pages[-1].merge_page(overlay)
    writer.add_metadata({"/Title": "Annotated Protocol Evidence", "/Producer": "Aurinara"})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
