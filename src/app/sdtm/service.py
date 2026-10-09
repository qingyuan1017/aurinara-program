"""SDTM revision services, lowering, and deterministic artifact generation."""

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal, cast
from uuid import UUID

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.problems import ProblemException
from app.documents.contracts import (
    DocumentCover,
    DocumentParagraph,
    DocumentSection,
    DocumentTable,
    RenderDocument,
)
from app.documents.rendering import render_docx, render_pdf
from app.documents.service import load_presentation_template
from app.execution.contracts import ExecutionProduct
from app.execution.models import ExecutionRun
from app.kernel.dependencies import RenderedArtifact, SqlDependencyCapability
from app.reconciliation.models import ReconciliationRun
from app.reconciliation.service import ReconciliationEvaluation
from app.sdtm.contracts import (
    SdtmCsdrgModel,
    SdtmDefineModel,
    SdtmDerivationPlan,
    SdtmSpecification,
)
from app.sdtm.define_xml import define_schema_fingerprint, render_define_xml
from app.sdtm.models import (
    SdtmAcrfAnnotation,
    SdtmCsdrgRevision,
    SdtmDefineRevision,
    SdtmDerivationPlanRevision,
    SdtmInputSelection,
    SdtmSpecificationRevision,
    SdtmWorkbench,
)
from app.sdtm.specification_workbook import render_specification_xlsx
from app.sdtm.xpt import build_xpt_v5, read_xpt_rows
from app.templates.models import TemplateVersion
from app.transformation.contracts import DataflowIR, Edge
from app.transformation.service import compile_dataflow, ir_fingerprint, lineage
from app.validation.models import ValidationRun

SDTM_BUILD_ARTIFACT_TYPES = (
    "sdtm_dependency_manifest",
    "sdtm_specification",
    "sdtm_specification_json",
    "sdtm_derivation_plan_json",
    "sdtm_derivation_report",
    "sdtm_lineage_report",
    "sdtm_lineage_report_json",
    "sdtm_program_python",
    "sdtm_program_r",
    "sdtm_program_sas",
    "sdtm_validation_report",
    "sdtm_validation_report_json",
    "sdtm_acrf",
    "sdtm_define_xml_20",
    "sdtm_define_xml_21",
    "sdtm_csdrg_docx",
    "sdtm_csdrg_pdf",
)
SDTM_ARTIFACT_TYPES = (
    *SDTM_BUILD_ARTIFACT_TYPES,
    "sdtm_dataset_csv",
    "sdtm_dataset_xpt",
    "sdtm_execution_log",
)


def _reconciliation_issue(
    code: str, dataset: str | None = None, variable: str | None = None
) -> dict[str, object]:
    return {
        "id": f"{code}:{dataset or ''}:{variable or ''}",
        "code": code,
        "severity": "error",
        "message": "SDTM Define metadata does not reconcile with its exact evidence inputs.",
        "suggestion": "Correct the maintained Define metadata or select matching exact evidence.",
        "module": "sdtm",
        "entity_type": "sdtm_define",
        "entity_id": None,
        "field_path": None,
        "dataset": dataset,
        "variable": variable,
        "artifact_id": None,
    }


def _find_define_reconciliation(
    session: Session,
    *,
    study_id: UUID,
    define_id: UUID,
    define_revision: int,
    output_checksums: dict[str, str],
) -> ReconciliationRun | None:
    """Find successful evidence that exactly matches one Define revision and its XPTs."""

    runs = session.scalars(
        select(ReconciliationRun)
        .where(
            ReconciliationRun.study_id == study_id,
            ReconciliationRun.reconciliation_type == "sdtm_define_outputs",
            ReconciliationRun.status == "succeeded",
            ReconciliationRun.error_count == 0,
        )
        .order_by(ReconciliationRun.completed_at.desc(), ReconciliationRun.created_at.desc())
    )
    for run in runs:
        entity_inputs = [
            item
            for item in run.inputs
            if item.get("entity_type") == "sdtm_define"
            and item.get("entity_id") == str(define_id)
            and item.get("revision") == define_revision
        ]
        if len(entity_inputs) != 1:
            continue
        artifact_inputs = {
            str(item["artifact_id"]): str(item["checksum"])
            for item in run.inputs
            if item.get("artifact_id") is not None
        }
        if artifact_inputs == output_checksums:
            return run
    return None


@dataclass(frozen=True, slots=True)
class SdtmCapability(SqlDependencyCapability):
    """SDTM module boundary without direct access to the Raw repository."""

    def resolve_entity(self, session: Session, entity_type: str, entity_id: UUID) -> UUID | None:
        if entity_type == "sdtm_workbench":
            return SqlDependencyCapability.resolve_entity(self, session, entity_type, entity_id)
        if entity_type == "sdtm_acrf_annotation":
            annotation = session.get(SdtmAcrfAnnotation, entity_id)
            return annotation.study_id if annotation is not None else None
        if entity_type == "sdtm_csdrg":
            csdrg = session.get(SdtmCsdrgRevision, entity_id)
            return csdrg.study_id if csdrg is not None else None
        return None

    def resolve_reconciliation_input(
        self, session: Session, entity_type: str, entity_id: UUID, revision: int
    ) -> UUID | None:
        if entity_type == "sdtm_workbench":
            return SqlDependencyCapability.resolve_reconciliation_input(
                self, session, entity_type, entity_id, revision
            )
        if entity_type == "sdtm_define":
            define_record = session.get(SdtmDefineRevision, entity_id)
            return (
                define_record.study_id
                if define_record is not None and define_record.revision == revision
                else None
            )
        if entity_type == "sdtm_acrf_annotation":
            annotation_record = session.get(SdtmAcrfAnnotation, entity_id)
            return (
                annotation_record.study_id
                if annotation_record is not None and annotation_record.revision == revision
                else None
            )
        return None

    def resolve_reconciliation(
        self,
        session: Session,
        study_id: UUID,
        reconciliation_type: str,
        inputs: list[dict[str, object]],
        options: dict[str, object],
    ) -> dict[str, object]:
        if reconciliation_type != "sdtm_define_outputs":
            raise ValueError("unsupported SDTM reconciliation type")
        del options
        define_inputs = [item for item in inputs if item.get("entity_type") == "sdtm_define"]
        if len(define_inputs) != 1:
            raise ValueError("SDTM reconciliation requires one exact Define revision")
        define_id = UUID(str(define_inputs[0]["entity_id"]))
        define_revision = int(str(define_inputs[0]["revision"]))
        define = session.get(SdtmDefineRevision, define_id)
        if define is None or define.study_id != study_id or define.revision != define_revision:
            raise ValueError("SDTM Define reconciliation input is stale")
        artifact_ids = {
            UUID(str(item["artifact_id"])): str(item["checksum"])
            for item in inputs
            if item.get("artifact_id") is not None
        }
        artifacts: list[dict[str, object]] = []
        for artifact_id, checksum in artifact_ids.items():
            artifact = session.get(Artifact, artifact_id)
            if (
                artifact is None
                or artifact.study_id != study_id
                or artifact.sha256 != checksum
                or artifact.artifact_type != "sdtm_dataset_xpt"
                or artifact.status != "available"
            ):
                raise ValueError("SDTM XPT reconciliation input is invalid")
            artifacts.append(
                {
                    "id": str(artifact.id),
                    "checksum": artifact.sha256,
                    "filename": artifact.filename,
                    "manifest": artifact.manifest,
                }
            )
        annotations: list[dict[str, object]] = []
        for item in inputs:
            if item.get("entity_type") != "sdtm_acrf_annotation":
                continue
            annotation = session.get(SdtmAcrfAnnotation, UUID(str(item["entity_id"])))
            if (
                annotation is None
                or annotation.study_id != study_id
                or annotation.sdtm_id != define.aggregate_id
                or annotation.revision != int(str(item["revision"]))
                or annotation.status == "deleted"
            ):
                raise ValueError("aCRF reconciliation input is invalid")
            annotations.append(
                {
                    "id": str(annotation.id),
                    "revision": annotation.revision,
                    "links": annotation.links,
                }
            )
        return {
            "study_id": str(study_id),
            "reconciliation_type": reconciliation_type,
            "define": {
                "id": str(define.id),
                "revision": define.revision,
                "fingerprint": define.fingerprint,
                "payload": define.payload,
            },
            "artifacts": sorted(artifacts, key=lambda item: str(item["id"])),
            "annotations": sorted(annotations, key=lambda item: str(item["id"])),
        }

    def evaluate_reconciliation(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> ReconciliationEvaluation:
        del storage
        define_snapshot = cast(dict[str, object], payload["define"])
        model = SdtmDefineModel.model_validate(define_snapshot["payload"])
        artifact_rows = cast(list[dict[str, object]], payload["artifacts"])
        artifacts_by_dataset = {
            str(cast(dict[str, object], item["manifest"])["dataset"]): item
            for item in artifact_rows
        }
        issues: list[dict[str, object]] = []
        for dataset in model.datasets:
            artifact = artifacts_by_dataset.get(dataset.name)
            if artifact is None:
                issues.append(_reconciliation_issue("SDTM_DEFINE_XPT_MISSING", dataset.name))
                continue
            manifest = cast(dict[str, object], artifact["manifest"])
            variables = {
                str(item["name"]): item
                for item in cast(list[dict[str, object]], manifest.get("variables", []))
            }
            for item in dataset.items:
                observed = variables.get(item.name)
                if observed is None:
                    issues.append(
                        _reconciliation_issue(
                            "SDTM_DEFINE_VARIABLE_MISSING", dataset.name, item.name
                        )
                    )
                    continue
                expected_type = "character" if item.data_type == "text" else "numeric"
                if observed.get("data_type") != expected_type:
                    issues.append(
                        _reconciliation_issue(
                            "SDTM_DEFINE_VARIABLE_TYPE_MISMATCH", dataset.name, item.name
                        )
                    )
                if item.length is not None and observed.get("length") != item.length:
                    issues.append(
                        _reconciliation_issue(
                            "SDTM_DEFINE_VARIABLE_LENGTH_MISMATCH", dataset.name, item.name
                        )
                    )
            leaf = next((leaf for leaf in model.leaves if leaf.id == dataset.leaf_id), None)
            if (
                leaf is None
                or str(leaf.artifact_id) != str(artifact["id"])
                or leaf.checksum != artifact["checksum"]
                or leaf.href != artifact["filename"]
            ):
                issues.append(_reconciliation_issue("SDTM_DEFINE_LEAF_MISMATCH", dataset.name))
        selected = set(artifacts_by_dataset)
        defined = {dataset.name for dataset in model.datasets}
        for extra_dataset in sorted(selected - defined):
            issues.append(_reconciliation_issue("SDTM_XPT_DATASET_UNDEFINED", extra_dataset))
        annotation_rows = cast(list[dict[str, object]], payload["annotations"])
        annotations = {str(item["id"]): item for item in annotation_rows}
        referenced: dict[str, tuple[str, str]] = {}
        for dataset in model.datasets:
            for item in dataset.items:
                for annotation_id in item.origin.acrf_annotation_ids:
                    referenced[str(annotation_id)] = (dataset.name, item.name)
                    annotation = annotations.get(str(annotation_id))
                    if annotation is None or not any(
                        link.get("target_type") == "sdtm_variable"
                        and link.get("domain") == dataset.name
                        and link.get("variable") == item.name
                        for link in cast(list[dict[str, object]], annotation.get("links", []))
                    ):
                        issues.append(
                            _reconciliation_issue(
                                "SDTM_DEFINE_ACRF_LINK_MISMATCH", dataset.name, item.name
                            )
                        )
        for annotation_key, annotation_snapshot in annotations.items():
            if annotation_key not in referenced and any(
                link.get("target_type") == "sdtm_variable"
                for link in cast(list[dict[str, object]], annotation_snapshot.get("links", []))
            ):
                issues.append(_reconciliation_issue("SDTM_ACRF_DEFINE_REFERENCE_MISSING"))
        return ReconciliationEvaluation(
            issues=tuple(issues),
            evidence={
                "define_id": define_snapshot["id"],
                "define_revision": define_snapshot["revision"],
                "xpt_artifact_ids": [item["id"] for item in artifact_rows],
                "annotation_revisions": [
                    {"id": item["id"], "revision": item["revision"]} for item in annotation_rows
                ],
            },
        )

    def current_input(self, session: Session, aggregate_id: UUID) -> SdtmInputSelection:
        record = session.scalar(
            select(SdtmInputSelection).where(SdtmInputSelection.aggregate_id == aggregate_id)
        )
        if record is None:
            raise ProblemException(
                status_code=409,
                code="sdtm_input_selection_required",
                title="SDTM input selection is required",
                detail="Select one exact validated Raw context first.",
            )
        return record

    def latest_specification(
        self, session: Session, aggregate_id: UUID
    ) -> SdtmSpecificationRevision | None:
        return session.scalar(
            select(SdtmSpecificationRevision)
            .where(SdtmSpecificationRevision.aggregate_id == aggregate_id)
            .order_by(SdtmSpecificationRevision.revision.desc())
        )

    def latest_plan(
        self, session: Session, aggregate_id: UUID
    ) -> SdtmDerivationPlanRevision | None:
        return session.scalar(
            select(SdtmDerivationPlanRevision)
            .where(SdtmDerivationPlanRevision.aggregate_id == aggregate_id)
            .order_by(SdtmDerivationPlanRevision.revision.desc())
        )

    def require_aligned(
        self, session: Session, aggregate_id: UUID
    ) -> tuple[SdtmSpecificationRevision, SdtmInputSelection, SdtmDerivationPlanRevision]:
        specification = self.latest_specification(session, aggregate_id)
        selection = self.current_input(session, aggregate_id)
        plan = self.latest_plan(session, aggregate_id)
        if specification is None or plan is None:
            raise ProblemException(
                status_code=409,
                code="sdtm_authoring_incomplete",
                title="SDTM authoring is incomplete",
                detail="A Specification and Derivation Plan are required.",
            )
        if (
            selection.state != "current"
            or plan.state != "aligned"
            or plan.specification_revision != specification.revision
            or plan.input_selection_revision != selection.revision
        ):
            raise ProblemException(
                status_code=409,
                code="sdtm_plan_misaligned",
                title="SDTM Derivation Plan is misaligned",
                detail=(
                    "Save a validated plan revision against the current Specification "
                    "and input selection."
                ),
            )
        return specification, selection, plan

    def context_snapshot(
        self, session: Session, sdtm_id: UUID, study_id: UUID
    ) -> dict[str, object]:
        """Export current aligned SDTM metadata and eligible immutable XPT evidence."""

        workbench = cast(SdtmWorkbench, self.require(session, sdtm_id, study_id))
        specification_record, input_selection, plan = self.require_aligned(session, sdtm_id)
        specification = context_from_record(specification_record)
        dependency_selection = self.get_selection(session, sdtm_id, study_id)
        output_artifacts = tuple(
            session.scalars(
                select(Artifact)
                .where(
                    Artifact.study_id == study_id,
                    Artifact.module_key == "sdtm",
                    Artifact.owner_type == "sdtm_workbench",
                    Artifact.owner_id == sdtm_id,
                    Artifact.artifact_type == "sdtm_dataset_xpt",
                    Artifact.status == "available",
                    Artifact.input_selection_revision == input_selection.revision,
                    Artifact.source_specification_revision == specification_record.revision,
                    Artifact.source_plan_revision == plan.revision,
                )
                .order_by(Artifact.created_at, Artifact.id)
            )
        )
        return {
            "schema_version": "1.0.0",
            "sdtm_id": str(workbench.id),
            "sdtm_revision": workbench.revision,
            "dependency_selection_revision": dependency_selection.revision,
            "dependency_fingerprint": dependency_selection.fingerprint,
            "dependency_selection": dependency_selection.model_dump(mode="json"),
            "input_selection_revision": input_selection.revision,
            "input_selection_fingerprint": input_selection.fingerprint,
            "specification_revision": specification_record.revision,
            "specification_fingerprint": specification_record.fingerprint,
            "plan_revision": plan.revision,
            "plan_fingerprint": plan.fingerprint,
            "datasets": [dataset.model_dump(mode="json") for dataset in specification.domains],
            "xpt_artifacts": [
                {
                    "artifact_id": str(artifact.id),
                    "dataset_code": artifact.manifest.get("dataset"),
                    "checksum": artifact.sha256,
                    "filename": artifact.filename,
                    "size": artifact.size,
                    "manifest": artifact.manifest,
                }
                for artifact in output_artifacts
            ],
        }

    def read_context_dataset(
        self,
        session: Session,
        storage: ObjectStorage,
        *,
        sdtm_id: UUID,
        study_id: UUID,
        dataset_code: str,
        artifact_id: UUID,
        expected_checksum: str,
        maximum_rows: int = 10_000,
    ) -> tuple[dict[str, object | None], ...]:
        """Read an exact current SDTM XPT through the owning module boundary."""

        _, input_selection, plan = self.require_aligned(session, sdtm_id)
        artifact = session.get(Artifact, artifact_id)
        if (
            artifact is None
            or artifact.study_id != study_id
            or artifact.module_key != "sdtm"
            or artifact.owner_type != "sdtm_workbench"
            or artifact.owner_id != sdtm_id
            or artifact.artifact_type != "sdtm_dataset_xpt"
            or artifact.status != "available"
            or artifact.sha256 != expected_checksum
            or artifact.manifest.get("dataset") != dataset_code
            or artifact.input_selection_revision != input_selection.revision
            or artifact.source_plan_revision != plan.revision
        ):
            raise ProblemException(
                status_code=409,
                code="sdtm_context_dataset_stale",
                title="SDTM context dataset is stale",
                detail=f"SDTM dataset '{dataset_code}' no longer matches the selected artifact.",
            )
        with storage.open(artifact.object_key) as stream:
            data = stream.read()
        if hashlib.sha256(data).hexdigest() != expected_checksum:
            raise ProblemException(
                status_code=409,
                code="sdtm_context_checksum_mismatch",
                title="SDTM context checksum does not match",
                detail="The immutable object bytes do not match the selected checksum.",
            )
        return read_xpt_rows(data, maximum_rows=maximum_rows)

    def mark_raw_refresh(self, session: Session, raw_id: UUID) -> tuple[UUID, ...]:
        affected: list[UUID] = []
        for selection in session.scalars(select(SdtmInputSelection)):
            if selection.payload.get("raw_id") == str(raw_id):
                selection.state = "input_refresh_required"
                plan = self.latest_plan(session, selection.aggregate_id)
                if plan is not None:
                    plan.state = "misaligned"
                for run in session.scalars(
                    select(ValidationRun).where(
                        ValidationRun.module_key == "sdtm",
                        ValidationRun.owner_id == selection.aggregate_id,
                        ValidationRun.status == "succeeded",
                    )
                ):
                    run.status = "stale"
                for execution in session.scalars(
                    select(ExecutionRun).where(
                        ExecutionRun.module_key == "sdtm",
                        ExecutionRun.owner_id == selection.aggregate_id,
                        ExecutionRun.status == "succeeded",
                    )
                ):
                    execution.status = "stale"
                affected.append(selection.aggregate_id)
        return tuple(affected)

    def build_artifact_payload(
        self, session: Session, aggregate_id: UUID, study_id: UUID, artifact_type: str
    ) -> dict[str, object]:
        if artifact_type == "sdtm_dependency_manifest":
            return SqlDependencyCapability.build_artifact_payload(
                self, session, aggregate_id, study_id, artifact_type
            )
        if artifact_type not in SDTM_BUILD_ARTIFACT_TYPES:
            raise ProblemException(
                status_code=422,
                code="artifact_type_unsupported",
                title="Artifact type is unsupported",
                detail=f"SDTM does not build '{artifact_type}'.",
            )
        if artifact_type in {"sdtm_csdrg_docx", "sdtm_csdrg_pdf"}:
            return self._build_csdrg_payload(session, aggregate_id, study_id, artifact_type)
        if artifact_type in {"sdtm_define_xml_20", "sdtm_define_xml_21"}:
            return self._build_define_xml_payload(session, aggregate_id, study_id, artifact_type)
        specification, selection, plan = self.require_aligned(session, aggregate_id)
        workbench = session.get(SdtmWorkbench, aggregate_id)
        if workbench is None or workbench.study_id != study_id:
            raise RuntimeError("SDTM workbench is missing")
        validation = session.scalar(
            select(ValidationRun)
            .where(
                ValidationRun.module_key == "sdtm",
                ValidationRun.owner_id == aggregate_id,
                ValidationRun.status == "succeeded",
            )
            .order_by(ValidationRun.completed_at.desc())
        )
        if validation is None or (
            (
                artifact_type == "sdtm_acrf"
                and validation.input_manifest.get("sdtm_revision") != workbench.revision
            )
            or validation.input_manifest.get("specification_revision") != specification.revision
            or validation.input_manifest.get("plan_revision") != plan.revision
            or validation.input_manifest.get("input_selection_revision") != selection.revision
        ):
            raise ProblemException(
                status_code=409,
                code="successful_validation_required",
                title="Current SDTM validation is required",
                detail="Validate the aligned current authoring revisions before building.",
            )
        base = SqlDependencyCapability.build_artifact_payload(
            self, session, aggregate_id, study_id, "sdtm_dependency_manifest"
        )
        specification_contract = context_from_record(specification)
        plan_contract = plan_from_record(plan)
        internal = lower_plan(specification_contract, plan_contract)
        result: dict[str, object] = {
            **base,
            "artifact_type": artifact_type,
            "input_selection": {
                "revision": selection.revision,
                "fingerprint": selection.fingerprint,
                "payload": selection.payload,
            },
            "specification": {
                "revision": specification.revision,
                "fingerprint": specification.fingerprint,
                "payload": specification.payload,
            },
            "source_plan": {
                "type": "sdtm_derivation_plan",
                "revision": plan.revision,
                "fingerprint": plan.fingerprint,
                "payload": plan.payload,
            },
            "normalized_ir": internal.model_dump(mode="json"),
            "ir_fingerprint": ir_fingerprint(internal),
            "validation_run": {
                "id": str(validation.id),
                "input_fingerprint": validation.input_fingerprint,
                "warning_count": validation.warning_count,
                "issues": validation.issues,
            },
        }
        if artifact_type == "sdtm_acrf":
            annotations = tuple(
                session.scalars(
                    select(SdtmAcrfAnnotation)
                    .where(
                        SdtmAcrfAnnotation.sdtm_id == aggregate_id,
                        SdtmAcrfAnnotation.status != "deleted",
                    )
                    .order_by(SdtmAcrfAnnotation.page_number, SdtmAcrfAnnotation.id)
                )
            )
            if not annotations or any(not item.links for item in annotations):
                raise ProblemException(
                    status_code=409,
                    code="acrf_annotations_incomplete",
                    title="aCRF annotations are incomplete",
                    detail=(
                        "At least one active annotation is required and every annotation "
                        "needs a link."
                    ),
                )
            source_ids = {item.source_pdf_artifact_id for item in annotations}
            if len(source_ids) != 1:
                raise ProblemException(
                    status_code=409,
                    code="acrf_source_pdf_mismatch",
                    title="aCRF source PDF is inconsistent",
                    detail="All active annotations must reference the same immutable source PDF.",
                )
            source = session.get(Artifact, source_ids.pop())
            if (
                source is None
                or source.study_id != study_id
                or source.status != "available"
                or source.media_type != "application/pdf"
            ):
                raise ProblemException(
                    status_code=409,
                    code="acrf_source_pdf_unavailable",
                    title="aCRF source PDF is unavailable",
                    detail="The exact annotated source PDF must still be available.",
                )
            result["acrf"] = {
                "schema_version": "1.0.0",
                "source_pdf_artifact_id": str(source.id),
                "source_pdf_checksum": source.sha256,
                "annotations": [
                    {
                        "id": str(item.id),
                        "revision": item.revision,
                        "page_number": item.page_number,
                        "region": item.region,
                        "annotation_text": item.annotation_text,
                        "links": item.links,
                        "status": item.status,
                        "fingerprint": item.fingerprint,
                    }
                    for item in annotations
                ],
            }
            result["_source_object_key"] = source.object_key
        return result

    def _build_define_xml_payload(
        self, session: Session, aggregate_id: UUID, study_id: UUID, artifact_type: str
    ) -> dict[str, object]:
        """Freeze validated Define metadata, XPT evidence, and local schema provenance."""

        specification, _, _ = self.require_aligned(session, aggregate_id)
        base = SqlDependencyCapability.build_artifact_payload(
            self, session, aggregate_id, study_id, "sdtm_dependency_manifest"
        )
        record = session.scalar(
            select(SdtmDefineRevision)
            .where(SdtmDefineRevision.aggregate_id == aggregate_id)
            .order_by(SdtmDefineRevision.revision.desc())
        )
        if record is None or record.study_id != study_id:
            raise ProblemException(
                status_code=409,
                code="sdtm_define_required",
                title="Define metadata is required",
                detail="Initialize and validate current Define metadata before building XML.",
            )
        schema_fingerprints = {
            "2.0": define_schema_fingerprint("2.0"),
            "2.1": define_schema_fingerprint("2.1"),
        }
        validation = session.scalar(
            select(ValidationRun)
            .where(
                ValidationRun.module_key == "sdtm",
                ValidationRun.owner_type == "sdtm_define",
                ValidationRun.owner_id == record.id,
                ValidationRun.status == "succeeded",
                ValidationRun.error_count == 0,
            )
            .order_by(ValidationRun.created_at.desc())
        )
        validation_current = (
            validation is not None
            and validation.input_manifest.get("define_revision") == record.revision
            and validation.input_manifest.get("define_fingerprint") == record.fingerprint
            and validation.input_manifest.get("specification_revision") == specification.revision
            and validation.input_manifest.get("output_artifact_ids") == record.output_artifact_ids
            and validation.input_manifest.get("define_xml_schema_fingerprints")
            == schema_fingerprints
        )
        if not validation_current or validation is None:
            raise ProblemException(
                status_code=409,
                code="successful_validation_required",
                title="Current Define validation is required",
                detail=(
                    "Validate the current Define revision against both pinned XSD versions "
                    "without errors before building XML."
                ),
            )
        output_checksums: dict[str, str] = {}
        for value in record.output_artifact_ids:
            artifact = session.get(Artifact, UUID(value))
            if (
                artifact is None
                or artifact.study_id != study_id
                or artifact.artifact_type != "sdtm_dataset_xpt"
                or artifact.status != "available"
                or artifact.sha256 is None
            ):
                raise ProblemException(
                    status_code=409,
                    code="define_output_artifact_unavailable",
                    title="Define output evidence is unavailable",
                    detail="Every exact XPT selected by Define must remain available.",
                )
            output_checksums[str(artifact.id)] = artifact.sha256
        reconciliation = _find_define_reconciliation(
            session,
            study_id=study_id,
            define_id=record.id,
            define_revision=record.revision,
            output_checksums=output_checksums,
        )
        if reconciliation is None:
            raise ProblemException(
                status_code=409,
                code="successful_reconciliation_required",
                title="Current Define reconciliation is required",
                detail=(
                    "Reconcile the exact Define revision and selected XPT checksums without "
                    "errors before building XML."
                ),
            )
        version: Literal["2.0", "2.1"] = "2.0" if artifact_type.endswith("_20") else "2.1"
        return {
            **base,
            "artifact_type": artifact_type,
            "define_xml_version": version,
            "define_xml_schema_fingerprint": schema_fingerprints[version],
            "define": {
                "id": str(record.id),
                "revision": record.revision,
                "fingerprint": record.fingerprint,
                "payload": record.payload,
            },
            "specification": {
                "revision": specification.revision,
                "fingerprint": specification.fingerprint,
            },
            "output_artifacts": [
                {"id": artifact_id, "checksum": checksum}
                for artifact_id, checksum in sorted(output_checksums.items())
            ],
            "validation_run": {
                "id": str(validation.id),
                "input_fingerprint": validation.input_fingerprint,
                "warning_count": validation.warning_count,
                "issues": validation.issues,
            },
            "reconciliation_run_id": str(reconciliation.id),
        }

    def _build_csdrg_payload(
        self, session: Session, aggregate_id: UUID, study_id: UUID, artifact_type: str
    ) -> dict[str, object]:
        """Freeze one validated cSDRG revision and its exact presentation dependency."""

        self.require_aligned(session, aggregate_id)
        base = SqlDependencyCapability.build_artifact_payload(
            self, session, aggregate_id, study_id, "sdtm_dependency_manifest"
        )
        selection = self.get_selection(session, aggregate_id, study_id)
        selected_templates = [
            item for item in selection.templates if item.artifact_type == artifact_type
        ]
        if len(selected_templates) != 1:
            raise ProblemException(
                status_code=409,
                code="artifact_template_selection_required",
                title="Exact artifact template is required",
                detail="Select exactly one compatible Template version for this cSDRG artifact.",
            )
        template = session.get(TemplateVersion, selected_templates[0].template_version_id)
        if template is None:
            raise RuntimeError("validated cSDRG Template version is missing")
        record = session.scalar(
            select(SdtmCsdrgRevision)
            .where(SdtmCsdrgRevision.aggregate_id == aggregate_id)
            .order_by(SdtmCsdrgRevision.revision.desc())
        )
        if record is None:
            raise ProblemException(
                status_code=409,
                code="sdtm_csdrg_required",
                title="cSDRG content is required",
                detail="Initialize and author cSDRG content before building.",
            )
        validation = session.scalar(
            select(ValidationRun)
            .where(
                ValidationRun.module_key == "sdtm",
                ValidationRun.owner_type == "sdtm_csdrg",
                ValidationRun.owner_id == record.id,
                ValidationRun.status == "succeeded",
                ValidationRun.error_count == 0,
            )
            .order_by(ValidationRun.created_at.desc())
        )
        expected_manifest = {
            "csdrg_revision": record.revision,
            "csdrg_fingerprint": record.fingerprint,
            "specification_revision": record.specification_revision,
            "define_revision": record.define_revision,
            "reconciliation_run_id": str(record.reconciliation_run_id),
            "output_artifact_ids": SdtmCsdrgModel.model_validate(record.payload).model_dump(
                mode="json"
            )["output_artifact_ids"],
        }
        if validation is None or validation.input_fingerprint != fingerprint(expected_manifest):
            raise ProblemException(
                status_code=409,
                code="successful_validation_required",
                title="Current cSDRG validation is required",
                detail="Validate the current cSDRG revision without errors before building.",
            )
        return {
            **base,
            "artifact_type": artifact_type,
            "csdrg": {
                "id": str(record.id),
                "revision": record.revision,
                "fingerprint": record.fingerprint,
                "payload": record.payload,
            },
            "validation_run": {
                "id": str(validation.id),
                "input_fingerprint": validation.input_fingerprint,
                "warning_count": validation.warning_count,
                "issues": validation.issues,
            },
            "reconciliation_run_id": str(record.reconciliation_run_id),
            "presentation_template_ref": {
                "id": str(template.id),
                "version": template.version,
                "checksum": template.checksum,
                "renderer_versions": template.renderer_versions,
                "asset_path": template.asset_path,
            },
        }

    def render_artifact(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> RenderedArtifact:
        artifact_type = str(payload.get("artifact_type", "sdtm_dependency_manifest"))
        if artifact_type == "sdtm_dependency_manifest":
            return SqlDependencyCapability.render_artifact(self, payload, storage)
        if artifact_type in {"sdtm_csdrg_docx", "sdtm_csdrg_pdf"}:
            csdrg_validation = cast(dict[str, object], payload["validation_run"])
            model = SdtmCsdrgModel.model_validate(
                cast(dict[str, object], payload["csdrg"])["payload"]
            )
            template = load_presentation_template(
                storage, cast(dict[str, object], payload["presentation_template_ref"])
            )
            data = (
                render_docx(_csdrg_document(model), template)
                if artifact_type.endswith("_docx")
                else render_pdf(_csdrg_document(model), template)
            )
            manifest = {key: value for key, value in payload.items() if not key.startswith("_")}
            return RenderedArtifact(
                data=data,
                filename="csdrg.docx" if artifact_type.endswith("_docx") else "csdrg.pdf",
                media_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    if artifact_type.endswith("_docx")
                    else "application/pdf"
                ),
                manifest=manifest,
                validation_run_id=UUID(str(csdrg_validation["id"])),
                reconciliation_run_id=UUID(str(payload["reconciliation_run_id"])),
            )
        if artifact_type in {"sdtm_define_xml_20", "sdtm_define_xml_21"}:
            define_validation = cast(dict[str, object], payload["validation_run"])
            define_snapshot = cast(dict[str, object], payload["define"])
            version: Literal["2.0", "2.1"] = "2.0" if artifact_type.endswith("_20") else "2.1"
            data = render_define_xml(
                SdtmDefineModel.model_validate(define_snapshot["payload"]), version
            )
            manifest = {key: value for key, value in payload.items() if not key.startswith("_")}
            return RenderedArtifact(
                data=data,
                filename=f"define-{version.replace('.', '-')}.xml",
                media_type="application/xml",
                manifest=manifest,
                validation_run_id=UUID(str(define_validation["id"])),
                reconciliation_run_id=UUID(str(payload["reconciliation_run_id"])),
            )
        validation_value = payload["validation_run"]
        if not isinstance(validation_value, dict):
            raise RuntimeError("SDTM validation manifest is invalid")
        validation = cast(dict[str, object], validation_value)
        validation_run_id = UUID(str(validation["id"]))
        if artifact_type == "sdtm_specification":
            content = cast(dict[str, object], payload["specification"])["payload"]
            data = render_specification_xlsx(SdtmSpecification.model_validate(content))
            return RenderedArtifact(
                data=data,
                filename="sdtm-specification.xlsx",
                media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                manifest=payload,
                validation_run_id=validation_run_id,
            )
        if artifact_type == "sdtm_specification_json":
            content = cast(dict[str, object], payload["specification"])["payload"]
            return _json_artifact(content, "sdtm-specification.json", payload, validation_run_id)
        if artifact_type == "sdtm_derivation_plan_json":
            content = cast(dict[str, object], payload["source_plan"])["payload"]
            return _json_artifact(content, "sdtm-derivation-plan.json", payload, validation_run_id)
        if artifact_type == "sdtm_derivation_report":
            content = {
                "schema_version": "1.0.0",
                "source_plan": cast(dict[str, object], payload["source_plan"]),
                "ir_fingerprint": payload["ir_fingerprint"],
                "outputs": lineage(DataflowIR.model_validate(payload["normalized_ir"])),
            }
            return _json_artifact(
                content, "sdtm-derivation-report.json", payload, validation_run_id
            )
        if artifact_type in {"sdtm_lineage_report", "sdtm_lineage_report_json"}:
            internal = DataflowIR.model_validate(payload["normalized_ir"])
            content = {
                "schema_version": "1.0.0",
                "ir_fingerprint": payload["ir_fingerprint"],
                "outputs": lineage(internal),
            }
            return _json_artifact(content, "sdtm-lineage.json", payload, validation_run_id)
        if artifact_type in {"sdtm_validation_report", "sdtm_validation_report_json"}:
            return _json_artifact(validation, "sdtm-validation.json", payload, validation_run_id)
        if artifact_type == "sdtm_acrf":
            acrf = cast(dict[str, object], payload["acrf"])
            with storage.open(str(payload["_source_object_key"])) as stream:
                source_pdf = stream.read()
            manifest = {key: value for key, value in payload.items() if not key.startswith("_")}
            return RenderedArtifact(
                data=_render_acrf(source_pdf, cast(list[dict[str, object]], acrf["annotations"])),
                filename="acrf.pdf",
                media_type="application/pdf",
                manifest=manifest,
                validation_run_id=validation_run_id,
            )
        backends = {
            "sdtm_program_python": ("python", "sdtm.py", "text/x-python"),
            "sdtm_program_r": ("r", "sdtm.R", "text/x-r-source"),
            "sdtm_program_sas": ("sas", "sdtm.sas", "text/plain"),
        }
        backend, filename, media_type = backends[artifact_type]
        program = compile_dataflow(DataflowIR.model_validate(payload["normalized_ir"]), backend)
        manifest = {
            **payload,
            "compiler": {
                "backend": backend,
                "version": program.compiler_version,
                "fingerprint": program.ir_fingerprint,
            },
        }
        return RenderedArtifact(
            data=program.source.encode("utf-8"),
            filename=filename,
            media_type=media_type,
            manifest=manifest,
            validation_run_id=validation_run_id,
        )

    def prepare_execution_outputs(
        self,
        program_manifest: dict[str, object],
        files: dict[str, bytes],
        maximum_bytes: int,
    ) -> tuple[ExecutionProduct, ...]:
        """Validate declared SDTM outputs and build read-back-verified XPT v5 products."""

        specification_record = program_manifest.get("specification")
        normalized = program_manifest.get("normalized_ir")
        if not isinstance(specification_record, dict) or not isinstance(normalized, dict):
            raise ProblemException(
                status_code=422,
                code="execution_manifest_invalid",
                title="Execution manifest is invalid",
                detail="SDTM execution requires frozen Specification and normalized IR inputs.",
            )
        specification = SdtmSpecification.model_validate(specification_record.get("payload"))
        nodes = normalized.get("nodes")
        if not isinstance(nodes, list):
            raise ProblemException(
                status_code=422,
                code="execution_manifest_invalid",
                title="Execution manifest is invalid",
                detail="The normalized IR output declarations are missing.",
            )
        writes = {
            str(node["dataset"])
            for node in nodes
            if isinstance(node, dict) and node.get("node_type") == "write"
        }
        domains = {domain.code: domain for domain in specification.domains if domain.code in writes}
        expected_files = {f"{code}.csv" for code in domains}
        if set(files) != expected_files:
            raise ProblemException(
                status_code=422,
                code="execution_outputs_mismatch",
                title="Execution outputs do not match declarations",
                detail="Produced files must exactly match the SDTM plan writes.",
            )
        if sum(len(data) for data in files.values()) > maximum_bytes:
            raise ProblemException(
                status_code=422,
                code="execution_output_limit_exceeded",
                title="Execution output limit exceeded",
                detail="Produced output bytes exceed the accepted execution limit.",
            )
        products: list[ExecutionProduct] = []
        for code, domain in sorted(domains.items()):
            csv_name = f"{code}.csv"
            csv_data = files[csv_name]
            xpt = build_xpt_v5(csv_data, domain)
            products.extend(
                (
                    ExecutionProduct(
                        artifact_type="sdtm_dataset_csv",
                        filename=csv_name,
                        media_type="text/csv",
                        data=csv_data,
                        manifest={"schema_version": "1.0.0", "dataset": code},
                    ),
                    ExecutionProduct(
                        artifact_type="sdtm_dataset_xpt",
                        filename=PurePath(domain.expected_output_name).name,
                        media_type="application/x-sas-xport",
                        data=xpt.data,
                        manifest=xpt.manifest,
                    ),
                )
            )
        return tuple(products)


def lower_plan(specification: SdtmSpecification, plan: SdtmDerivationPlan) -> DataflowIR:
    """Lower one validated SDTM-owned plan into internal Dataflow IR."""

    domains = {domain.code: domain for domain in specification.domains}
    nodes: list[dict[str, object]] = []
    for node in plan.nodes:
        if node.node_type == "raw_read":
            nodes.append({"node_type": "read", "id": node.id, "dataset": node.raw_dataset_code})
        elif node.node_type == "domain_write":
            if node.domain not in domains:
                raise ProblemException(
                    status_code=422,
                    code="sdtm_plan_output_unknown",
                    title="SDTM plan output is unknown",
                    detail=f"Domain '{node.domain}' is absent from the Specification.",
                )
            nodes.append({"node_type": "write", "id": node.id, "dataset": node.domain})
        elif node.node_type == "derive":
            nodes.append(
                {
                    "node_type": "derive",
                    "id": node.id,
                    "assignments": {
                        name: expression.model_dump(mode="json")
                        for name, expression in node.assignments.items()
                    },
                }
            )
        else:
            nodes.append(node.model_dump(mode="json"))
    writes = {node.domain for node in plan.nodes if node.node_type == "domain_write"}
    required = {
        domain.code
        for domain in specification.domains
        if any(variable.derived for variable in domain.variables)
    }
    if not required <= writes:
        missing = ", ".join(sorted(required - writes))
        raise ProblemException(
            status_code=422,
            code="sdtm_plan_output_coverage_missing",
            title="SDTM plan output coverage is incomplete",
            detail=f"Derived targets require writes for: {missing}",
        )
    return DataflowIR.model_validate(
        {
            "nodes": nodes,
            "edges": [
                Edge(source_node=edge.source_node, target_node=edge.target_node).model_dump()
                for edge in plan.edges
            ],
        }
    )


def context_from_record(record: SdtmSpecificationRevision) -> SdtmSpecification:
    return SdtmSpecification.model_validate(record.payload)


def plan_from_record(record: SdtmDerivationPlanRevision) -> SdtmDerivationPlan:
    return SdtmDerivationPlan.model_validate(record.payload)


def _json_artifact(
    content: object,
    filename: str,
    manifest: dict[str, object],
    validation_run_id: UUID,
) -> RenderedArtifact:
    return RenderedArtifact(
        data=json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        ),
        filename=filename,
        media_type="application/json",
        manifest=manifest,
        validation_run_id=validation_run_id,
    )


def _csdrg_document(model: SdtmCsdrgModel) -> RenderDocument:
    """Translate persisted cSDRG content into the shared renderer-neutral model."""

    evidence = DocumentSection(
        section_id="dataset_evidence",
        heading="Dataset Evidence",
        paragraphs=(
            DocumentParagraph(
                text=(
                    "Factual dataset details below are resolved from the exact reconciled "
                    "SDTM XPT artifacts selected by this cSDRG revision."
                )
            ),
        ),
        tables=(
            DocumentTable(
                headers=(
                    "Dataset",
                    "Label",
                    "Structure",
                    "Rows",
                    "Variables",
                    "Artifact ID",
                    "SHA-256",
                ),
                rows=tuple(
                    (
                        item.dataset,
                        item.label,
                        item.structure,
                        str(item.row_count),
                        str(item.variable_count),
                        str(item.xpt_artifact_id),
                        item.checksum,
                    )
                    for item in model.dataset_facts
                ),
            ),
        ),
    )
    authored = tuple(
        DocumentSection(
            section_id=item.section_id,
            heading=item.heading,
            paragraphs=tuple(DocumentParagraph(text=text) for text in item.paragraphs),
        )
        for item in model.narrative_sections
    )
    provenance = DocumentSection(
        section_id="provenance",
        heading="Exact Evidence Selection",
        tables=(
            DocumentTable(
                headers=("Input", "Exact revision or identifier"),
                rows=(
                    ("SDTM Specification revision", str(model.specification_revision)),
                    ("Define metadata revision", str(model.define_revision)),
                    ("Reconciliation run", str(model.reconciliation_run_id)),
                ),
            ),
        ),
    )
    return RenderDocument(
        cover=DocumentCover(title=model.title, document_code="cSDRG", version=model.version),
        sections=(evidence, *authored, provenance),
    )


def _render_acrf(source_pdf: bytes, annotations: list[dict[str, object]]) -> bytes:
    """Overlay persisted normalized annotation rectangles onto exact source PDF bytes."""

    reader = PdfReader(io.BytesIO(source_pdf))
    by_page: dict[int, list[dict[str, object]]] = {}
    for annotation in annotations:
        by_page.setdefault(cast(int, annotation["page_number"]), []).append(annotation)
    writer = PdfWriter()
    for page_number, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        writer.add_page(page)
        output_page = writer.pages[-1]
        page_annotations = by_page.get(page_number, [])
        if page_annotations:
            overlay_stream = io.BytesIO()
            overlay = Canvas(overlay_stream, pagesize=(width, height), invariant=1)
            overlay.setStrokeColor(Color(0.85, 0.1, 0.1, alpha=1))
            overlay.setFillColor(Color(0.85, 0.1, 0.1, alpha=1))
            overlay.setLineWidth(1)
            for index, annotation in enumerate(page_annotations, start=1):
                region = cast(dict[str, object], annotation["region"])
                x = cast(float, region["x"]) * width
                box_width = cast(float, region["width"]) * width
                box_height = cast(float, region["height"]) * height
                y = height - (cast(float, region["y"]) + cast(float, region["height"])) * height
                overlay.rect(x, y, box_width, box_height, stroke=1, fill=0)
                overlay.setFont("Helvetica", 7)
                overlay.drawString(x + 2, min(height - 8, y + box_height + 2), f"A{index}")
            overlay.save()
            overlay_stream.seek(0)
            output_page.merge_page(PdfReader(overlay_stream).pages[0])
    writer.add_metadata({"/Producer": "Aurinara aCRF renderer 1.0.0"})
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()
