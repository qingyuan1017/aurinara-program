"""ADaM authoring services and lowering to the internal Dataflow IR."""

import json
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adam.contracts import (
    AdamAdrgModel,
    AdamDefineModel,
    AdamDerivationPlan,
    AdamSpecification,
)
from app.adam.define_xml import GENERATOR_VERSION as DEFINE_XML_GENERATOR_VERSION
from app.adam.define_xml import define_schema_fingerprint, render_define_xml
from app.adam.models import (
    AdamAdrgRevision,
    AdamDefineRevision,
    AdamDerivationPlanRevision,
    AdamInputSelection,
    AdamSpecificationRevision,
    AdamWorkbench,
)
from app.adam.specification_workbook import render_specification_xlsx
from app.adam.validation_versions import DEFINE_VALIDATOR_NAME, DEFINE_VALIDATOR_VERSION
from app.adam.xpt import build_adam_xpt_v5
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
from app.execution.contracts import ExecutionProduct
from app.execution.models import ExecutionRun
from app.kernel.dependencies import (
    DependencySelectionResponse,
    RenderedArtifact,
    SqlDependencyCapability,
)
from app.reconciliation.models import ReconciliationRun
from app.reconciliation.service import ReconciliationEvaluation
from app.templates.models import TemplateVersion
from app.transformation.contracts import DataflowIR, Edge
from app.transformation.service import compile_dataflow, ir_fingerprint, lineage
from app.validation.models import ValidationRun

ADAM_BUILD_ARTIFACT_TYPES = (
    "adam_dependency_manifest",
    "adam_specification",
    "adam_specification_json",
    "adam_derivation_plan_json",
    "adam_derivation_report",
    "adam_traceability_report",
    "adam_program_python",
    "adam_program_r",
    "adam_program_sas",
    "adam_validation_report",
    "adam_define_xml_20",
    "adam_define_xml_21",
    "adam_adrg_docx",
    "adam_adrg_pdf",
)
ADAM_ARTIFACT_TYPES = (
    *ADAM_BUILD_ARTIFACT_TYPES,
    "adam_dataset_csv",
    "adam_dataset_xpt",
    "adam_execution_log",
)


def _reconciliation_issue(
    code: str, dataset: str | None = None, variable: str | None = None
) -> dict[str, object]:
    return {
        "id": f"{code}:{dataset or ''}:{variable or ''}",
        "code": code,
        "severity": "error",
        "message": "ADaM Define metadata does not match its exact XPT evidence.",
        "suggestion": "Correct maintained Define metadata or select matching exact outputs.",
        "module": "adam",
        "entity_type": "adam_define",
        "entity_id": None,
        "field_path": None,
        "dataset": dataset,
        "variable": variable,
        "artifact_id": None,
    }


def _find_reconciliation(
    session: Session,
    study_id: UUID,
    define_id: UUID,
    define_revision: int,
    checksums: dict[str, str],
) -> ReconciliationRun | None:
    runs = session.scalars(
        select(ReconciliationRun)
        .where(
            ReconciliationRun.study_id == study_id,
            ReconciliationRun.reconciliation_type == "adam_define_outputs",
            ReconciliationRun.status == "succeeded",
            ReconciliationRun.error_count == 0,
        )
        .order_by(ReconciliationRun.completed_at.desc(), ReconciliationRun.created_at.desc())
    )
    for run in runs:
        entity_inputs = [
            item
            for item in run.inputs
            if item.get("entity_type") == "adam_define"
            and item.get("entity_id") == str(define_id)
            and item.get("revision") == define_revision
        ]
        artifact_inputs = {
            str(item["artifact_id"]): str(item["checksum"])
            for item in run.inputs
            if item.get("artifact_id") is not None
        }
        if len(entity_inputs) == 1 and artifact_inputs == checksums:
            return run
    return None


def _build_conflict(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=409, code=code, title="ADaM artifact build is blocked", detail=detail
    )


@dataclass(frozen=True, slots=True)
class AdamCapability(SqlDependencyCapability):
    """ADaM module boundary over exact inputs and immutable authoring revisions."""

    def current_input(self, session: Session, aggregate_id: UUID) -> AdamInputSelection:
        record = session.scalar(
            select(AdamInputSelection).where(AdamInputSelection.aggregate_id == aggregate_id)
        )
        if record is None:
            raise ProblemException(
                status_code=409,
                code="adam_input_selection_required",
                title="ADaM input selection is required",
                detail="Select one exact validated SDTM context first.",
            )
        return record

    def latest_specification(
        self, session: Session, aggregate_id: UUID
    ) -> AdamSpecificationRevision | None:
        return session.scalar(
            select(AdamSpecificationRevision)
            .where(AdamSpecificationRevision.aggregate_id == aggregate_id)
            .order_by(AdamSpecificationRevision.revision.desc())
        )

    def latest_plan(
        self, session: Session, aggregate_id: UUID
    ) -> AdamDerivationPlanRevision | None:
        return session.scalar(
            select(AdamDerivationPlanRevision)
            .where(AdamDerivationPlanRevision.aggregate_id == aggregate_id)
            .order_by(AdamDerivationPlanRevision.revision.desc())
        )

    def require_aligned(
        self, session: Session, aggregate_id: UUID
    ) -> tuple[AdamSpecificationRevision, AdamInputSelection, AdamDerivationPlanRevision]:
        specification = self.latest_specification(session, aggregate_id)
        selection = self.current_input(session, aggregate_id)
        plan = self.latest_plan(session, aggregate_id)
        if specification is None or plan is None:
            raise ProblemException(
                status_code=409,
                code="adam_authoring_incomplete",
                title="ADaM authoring is incomplete",
                detail="An ADaM Specification and Derivation Plan are required.",
            )
        if (
            selection.state != "current"
            or plan.state != "aligned"
            or plan.specification_revision != specification.revision
            or plan.input_selection_revision != selection.revision
        ):
            raise ProblemException(
                status_code=409,
                code="adam_plan_misaligned",
                title="ADaM Derivation Plan is misaligned",
                detail=(
                    "Save a validated plan revision against the current Specification "
                    "and input selection."
                ),
            )
        return specification, selection, plan

    def mark_sdtm_refresh(self, session: Session, sdtm_id: UUID) -> tuple[UUID, ...]:
        """Mark every exact ADaM consumer of an updated SDTM aggregate as stale."""

        affected: list[UUID] = []
        for selection in session.scalars(select(AdamInputSelection)):
            if selection.payload.get("sdtm_id") != str(sdtm_id):
                continue
            selection.state = "input_refresh_required"
            plan = self.latest_plan(session, selection.aggregate_id)
            if plan is not None:
                plan.state = "misaligned"
            evidence_owner_ids = {
                selection.aggregate_id,
                *session.scalars(
                    select(AdamDefineRevision.id).where(
                        AdamDefineRevision.aggregate_id == selection.aggregate_id
                    )
                ),
                *session.scalars(
                    select(AdamAdrgRevision.id).where(
                        AdamAdrgRevision.aggregate_id == selection.aggregate_id
                    )
                ),
            }
            for run in session.scalars(
                select(ValidationRun).where(
                    ValidationRun.module_key == "adam",
                    ValidationRun.owner_id.in_(evidence_owner_ids),
                    ValidationRun.status == "succeeded",
                )
            ):
                run.status = "stale"
            for execution in session.scalars(
                select(ExecutionRun).where(
                    ExecutionRun.module_key == "adam",
                    ExecutionRun.owner_id == selection.aggregate_id,
                    ExecutionRun.status == "succeeded",
                )
            ):
                execution.status = "stale"
            affected.append(selection.aggregate_id)
        return tuple(affected)

    def resolve_reconciliation_input(
        self, session: Session, entity_type: str, entity_id: UUID, revision: int
    ) -> UUID | None:
        if entity_type == "adam_define":
            record = session.get(AdamDefineRevision, entity_id)
            return record.study_id if record is not None and record.revision == revision else None
        return SqlDependencyCapability.resolve_reconciliation_input(
            self, session, entity_type, entity_id, revision
        )

    def resolve_reconciliation(
        self,
        session: Session,
        study_id: UUID,
        reconciliation_type: str,
        inputs: list[dict[str, object]],
        options: dict[str, object],
    ) -> dict[str, object]:
        if reconciliation_type != "adam_define_outputs":
            raise ValueError("unsupported ADaM reconciliation type")
        del options
        define_inputs = [item for item in inputs if item.get("entity_type") == "adam_define"]
        if len(define_inputs) != 1:
            raise ValueError("ADaM reconciliation requires one exact Define revision")
        define = session.get(AdamDefineRevision, UUID(str(define_inputs[0]["entity_id"])))
        if (
            define is None
            or define.study_id != study_id
            or define.revision != int(str(define_inputs[0]["revision"]))
        ):
            raise ValueError("ADaM Define reconciliation input is stale")
        rows: list[dict[str, object]] = []
        for item in inputs:
            if item.get("artifact_id") is None:
                continue
            artifact = session.get(Artifact, UUID(str(item["artifact_id"])))
            if (
                artifact is None
                or artifact.study_id != study_id
                or artifact.artifact_type != "adam_dataset_xpt"
                or artifact.status != "available"
                or artifact.sha256 != str(item["checksum"])
            ):
                raise ValueError("ADaM XPT reconciliation input is invalid")
            rows.append(
                {
                    "id": str(artifact.id),
                    "checksum": artifact.sha256,
                    "filename": artifact.filename,
                    "manifest": artifact.manifest,
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
            "artifacts": sorted(rows, key=lambda item: str(item["id"])),
        }

    def evaluate_reconciliation(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> ReconciliationEvaluation:
        del storage
        define = cast(dict[str, object], payload["define"])
        model = AdamDefineModel.model_validate(define["payload"])
        rows = cast(list[dict[str, object]], payload["artifacts"])
        by_dataset = {str(cast(dict[str, object], row["manifest"])["dataset"]): row for row in rows}
        issues: list[dict[str, object]] = []
        leaves = {str(item.artifact_id): item for item in model.leaves}
        for dataset in model.datasets:
            row = by_dataset.get(dataset.code)
            if row is None:
                issues.append(_reconciliation_issue("ADAM_DEFINE_XPT_MISSING", dataset.code))
                continue
            manifest = cast(dict[str, object], row["manifest"])
            if row.get("filename") != dataset.expected_output_name:
                issues.append(
                    _reconciliation_issue("ADAM_DEFINE_DATASET_FILENAME_MISMATCH", dataset.code)
                )
            if manifest.get("label") != dataset.label:
                issues.append(
                    _reconciliation_issue("ADAM_DEFINE_DATASET_LABEL_MISMATCH", dataset.code)
                )
            manifest_variables = cast(list[dict[str, object]], manifest.get("variables", []))
            expected_order = [variable.name for variable in dataset.variables]
            observed_order = [str(item["name"]) for item in manifest_variables]
            if observed_order != expected_order:
                issues.append(
                    _reconciliation_issue("ADAM_DEFINE_VARIABLE_ORDER_MISMATCH", dataset.code)
                )
            variables = {
                str(item["name"]): item
                for item in manifest_variables
            }
            for variable in dataset.variables:
                observed = variables.get(variable.name)
                if observed is None:
                    issues.append(
                        _reconciliation_issue(
                            "ADAM_DEFINE_VARIABLE_MISSING", dataset.code, variable.name
                        )
                    )
                    continue
                if observed.get("data_type") != variable.data_type:
                    issues.append(
                        _reconciliation_issue(
                            "ADAM_DEFINE_VARIABLE_TYPE_MISMATCH", dataset.code, variable.name
                        )
                    )
                if observed.get("length") != variable.length:
                    issues.append(
                        _reconciliation_issue(
                            "ADAM_DEFINE_VARIABLE_LENGTH_MISMATCH", dataset.code, variable.name
                        )
                    )
                if observed.get("label") != variable.label:
                    issues.append(
                        _reconciliation_issue(
                            "ADAM_DEFINE_VARIABLE_LABEL_MISMATCH", dataset.code, variable.name
                        )
                    )
                if observed.get("origin") != variable.origin.model_dump(mode="json"):
                    issues.append(
                        _reconciliation_issue(
                            "ADAM_DEFINE_VARIABLE_ORIGIN_MISMATCH", dataset.code, variable.name
                        )
                    )
                if observed.get("method_id") != variable.method_id:
                    issues.append(
                        _reconciliation_issue(
                            "ADAM_DEFINE_VARIABLE_METHOD_MISMATCH", dataset.code, variable.name
                        )
                    )
            for extra_variable in sorted(set(variables) - set(expected_order)):
                issues.append(
                    _reconciliation_issue(
                        "ADAM_XPT_VARIABLE_UNDEFINED", dataset.code, extra_variable
                    )
                )
            leaf = leaves.get(str(row["id"]))
            if leaf is None or leaf.checksum != row["checksum"] or leaf.href != row["filename"]:
                issues.append(_reconciliation_issue("ADAM_DEFINE_LEAF_MISMATCH", dataset.code))
        for extra in sorted(set(by_dataset) - {item.code for item in model.datasets}):
            issues.append(_reconciliation_issue("ADAM_XPT_DATASET_UNDEFINED", extra))
        return ReconciliationEvaluation(
            issues=tuple(issues),
            evidence={
                "define_id": define["id"],
                "define_revision": define["revision"],
                "xpt_artifact_ids": [item["id"] for item in rows],
            },
        )

    def build_artifact_payload(
        self, session: Session, aggregate_id: UUID, study_id: UUID, artifact_type: str
    ) -> dict[str, object]:
        if artifact_type == "adam_dependency_manifest":
            return SqlDependencyCapability.build_artifact_payload(
                self, session, aggregate_id, study_id, artifact_type
            )
        if artifact_type not in ADAM_BUILD_ARTIFACT_TYPES:
            raise ProblemException(
                status_code=422,
                code="artifact_type_unsupported",
                title="Artifact type is unsupported",
                detail=f"ADaM does not build '{artifact_type}'.",
            )
        if artifact_type in {"adam_define_xml_20", "adam_define_xml_21"}:
            return self._build_define_xml_payload(session, aggregate_id, study_id, artifact_type)
        if artifact_type in {"adam_adrg_docx", "adam_adrg_pdf"}:
            return self._build_adrg_payload(session, aggregate_id, study_id, artifact_type)
        specification, selection, plan = self.require_aligned(session, aggregate_id)
        workbench = session.get(AdamWorkbench, aggregate_id)
        if workbench is None or workbench.study_id != study_id:
            raise RuntimeError("ADaM workbench is missing")
        validation = session.scalar(
            select(ValidationRun)
            .where(
                ValidationRun.module_key == "adam",
                ValidationRun.owner_type == "adam_workbench",
                ValidationRun.owner_id == aggregate_id,
                ValidationRun.status == "succeeded",
                ValidationRun.error_count == 0,
            )
            .order_by(ValidationRun.completed_at.desc())
        )
        if validation is None or (
            validation.input_manifest.get("adam_revision") != workbench.revision
            or validation.input_manifest.get("specification_revision") != specification.revision
            or validation.input_manifest.get("plan_revision") != plan.revision
            or validation.input_manifest.get("input_selection_revision") != selection.revision
        ):
            raise ProblemException(
                status_code=409,
                code="successful_validation_required",
                title="Current ADaM validation is required",
                detail="Validate the aligned current authoring revisions before building.",
            )
        base = SqlDependencyCapability.build_artifact_payload(
            self, session, aggregate_id, study_id, "adam_dependency_manifest"
        )
        specification_contract = context_from_record(specification)
        plan_contract = plan_from_record(plan)
        internal = lower_plan(specification_contract, plan_contract)
        return {
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
                "type": "adam_derivation_plan",
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

    def _build_define_xml_payload(
        self, session: Session, aggregate_id: UUID, study_id: UUID, artifact_type: str
    ) -> dict[str, object]:
        base = SqlDependencyCapability.build_artifact_payload(
            self, session, aggregate_id, study_id, "adam_dependency_manifest"
        )
        record = session.scalar(
            select(AdamDefineRevision)
            .where(AdamDefineRevision.aggregate_id == aggregate_id)
            .order_by(AdamDefineRevision.revision.desc())
        )
        if record is None or record.study_id != study_id:
            raise _build_conflict("adam_define_required", "Initialize ADaM Define first.")
        selection = self.current_input(session, aggregate_id)
        specification = self.latest_specification(session, aggregate_id)
        if (
            selection.state != "current"
            or specification is None
            or record.input_selection_revision != selection.revision
            or record.specification_revision != specification.revision
        ):
            raise _build_conflict(
                "adam_define_inputs_stale",
                "ADaM Define does not bind the current Specification and exact SDTM selection.",
            )
        schemas = {
            "2.0": define_schema_fingerprint("2.0"),
            "2.1": define_schema_fingerprint("2.1"),
        }
        validation_candidates = session.scalars(
            select(ValidationRun)
            .where(
                ValidationRun.module_key == "adam",
                ValidationRun.owner_type == "adam_define",
                ValidationRun.owner_id == record.id,
                ValidationRun.status == "succeeded",
                ValidationRun.error_count == 0,
            )
            .order_by(ValidationRun.created_at.desc())
        )
        validation = next(
            (
                candidate
                for candidate in validation_candidates
                if candidate.validator_name == DEFINE_VALIDATOR_NAME
                and candidate.validator_version == DEFINE_VALIDATOR_VERSION
                and candidate.input_manifest.get("define_revision") == record.revision
                and candidate.input_manifest.get("define_fingerprint") == record.fingerprint
                and candidate.input_manifest.get("specification_revision")
                == specification.revision
                and candidate.input_manifest.get("input_selection_revision")
                == selection.revision
                and candidate.input_manifest.get("define_xml_generator_version")
                == DEFINE_XML_GENERATOR_VERSION
                and candidate.input_manifest.get("define_xml_schema_fingerprints") == schemas
            ),
            None,
        )
        if validation is None:
            raise _build_conflict(
                "successful_validation_required", "Validate current ADaM Define first."
            )
        checksums: dict[str, str] = {}
        for value in record.output_artifact_ids:
            artifact = session.get(Artifact, UUID(value))
            if artifact is None or artifact.status != "available":
                raise _build_conflict(
                    "adam_define_output_unavailable", "A selected ADaM XPT is unavailable."
                )
            checksums[str(artifact.id)] = artifact.sha256
        reconciliation = _find_reconciliation(
            session, study_id, record.id, record.revision, checksums
        )
        if reconciliation is None:
            raise _build_conflict(
                "successful_reconciliation_required",
                "Reconcile current ADaM Define and exact XPTs first.",
            )
        version: Literal["2.0", "2.1"] = "2.0" if artifact_type.endswith("_20") else "2.1"
        return {
            **base,
            "artifact_type": artifact_type,
            "define_xml_version": version,
            "define_xml_generator_version": DEFINE_XML_GENERATOR_VERSION,
            "define_xml_schema_fingerprint": schemas[version],
            "define": {
                "id": str(record.id),
                "revision": record.revision,
                "fingerprint": record.fingerprint,
                "payload": record.payload,
            },
            "output_artifacts": [
                {"id": key, "checksum": value} for key, value in sorted(checksums.items())
            ],
            "validation_run": {"id": str(validation.id)},
            "reconciliation_run_id": str(reconciliation.id),
        }

    def _build_adrg_payload(
        self, session: Session, aggregate_id: UUID, study_id: UUID, artifact_type: str
    ) -> dict[str, object]:
        specification, input_selection, plan = self.require_aligned(session, aggregate_id)
        base = SqlDependencyCapability.build_artifact_payload(
            self, session, aggregate_id, study_id, "adam_dependency_manifest"
        )
        selection = self.get_selection(session, aggregate_id, study_id)
        selected = [item for item in selection.templates if item.artifact_type == artifact_type]
        if len(selected) != 1:
            raise _build_conflict(
                "artifact_template_selection_required",
                "Select one exact compatible Template version for this ADRG format.",
            )
        template = session.get(TemplateVersion, selected[0].template_version_id)
        if template is None:
            raise RuntimeError("validated ADRG Template version is missing")
        record = session.scalar(
            select(AdamAdrgRevision)
            .where(AdamAdrgRevision.aggregate_id == aggregate_id)
            .order_by(AdamAdrgRevision.revision.desc())
        )
        if record is None:
            raise _build_conflict("adam_adrg_required", "Initialize and author ADRG first.")
        model = AdamAdrgModel.model_validate(record.payload)
        current_define = session.scalar(
            select(AdamDefineRevision)
            .where(AdamDefineRevision.aggregate_id == aggregate_id)
            .order_by(AdamDefineRevision.revision.desc())
        )
        reconciliation = session.get(ReconciliationRun, model.reconciliation_run_id)
        revisions_are_current = (
            model.specification_revision == specification.revision
            and model.input_selection_revision == input_selection.revision
            and model.plan_revision == plan.revision
            and current_define is not None
            and model.define_revision == current_define.revision
        )
        evidence_is_current = reconciliation is not None and (
            reconciliation.study_id == study_id
            and reconciliation.reconciliation_type == "adam_define_outputs"
            and reconciliation.status == "succeeded"
            and reconciliation.error_count == 0
        )
        for dataset_fact in model.dataset_facts:
            output = session.get(Artifact, dataset_fact.xpt_artifact_id)
            evidence_is_current = (
                evidence_is_current
                and output is not None
                and (
                    output.status == "available"
                    and output.artifact_type == "adam_dataset_xpt"
                    and output.sha256 == dataset_fact.checksum
                )
            )
        for execution_fact in model.execution_facts:
            execution = session.get(ExecutionRun, execution_fact.execution_run_id)
            program = session.get(Artifact, execution_fact.program_artifact_id)
            evidence_is_current = (
                evidence_is_current
                and execution is not None
                and (
                    execution.status == "succeeded"
                    and execution.program_artifact_id == execution_fact.program_artifact_id
                    and tuple(UUID(value) for value in execution.output_artifact_ids)
                    == execution_fact.output_artifact_ids
                )
            )
            evidence_is_current = (
                evidence_is_current
                and program is not None
                and (
                    program.status == "available"
                    and program.sha256 == execution_fact.program_checksum
                )
            )
        if not revisions_are_current or not evidence_is_current:
            raise _build_conflict(
                "adam_adrg_evidence_stale",
                "Refresh ADRG factual evidence and validate the new revision before building.",
            )
        expected = {
            "adrg_revision": record.revision,
            "adrg_fingerprint": record.fingerprint,
            "specification_revision": model.specification_revision,
            "input_selection_revision": model.input_selection_revision,
            "plan_revision": model.plan_revision,
            "define_revision": model.define_revision,
            "reconciliation_run_id": str(model.reconciliation_run_id),
            "output_artifact_ids": [str(item) for item in model.output_artifact_ids],
        }
        validation = session.scalar(
            select(ValidationRun)
            .where(
                ValidationRun.module_key == "adam",
                ValidationRun.owner_type == "adam_adrg",
                ValidationRun.owner_id == record.id,
                ValidationRun.status == "succeeded",
                ValidationRun.error_count == 0,
            )
            .order_by(ValidationRun.created_at.desc())
        )
        if validation is None or validation.input_fingerprint != fingerprint(expected):
            raise _build_conflict(
                "successful_validation_required", "Validate current ADRG without errors first."
            )
        return {
            **base,
            "artifact_type": artifact_type,
            "adrg": {
                "id": str(record.id),
                "revision": record.revision,
                "fingerprint": record.fingerprint,
                "payload": record.payload,
            },
            "template": {
                "id": str(template.id),
                "version": template.version,
                "checksum": template.checksum,
                "blank_structure": template.blank_structure,
            },
            "validation_run": {"id": str(validation.id)},
            "reconciliation_run_id": str(model.reconciliation_run_id),
        }

    def render_artifact(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> RenderedArtifact:
        artifact_type = str(payload.get("artifact_type", "adam_dependency_manifest"))
        if artifact_type == "adam_dependency_manifest":
            return SqlDependencyCapability.render_artifact(self, payload, storage)
        del storage
        if artifact_type in {"adam_define_xml_20", "adam_define_xml_21"}:
            snapshot = cast(dict[str, object], payload["define"])
            validation = cast(dict[str, object], payload["validation_run"])
            version: Literal["2.0", "2.1"] = "2.0" if artifact_type.endswith("_20") else "2.1"
            return RenderedArtifact(
                data=render_define_xml(
                    AdamDefineModel.model_validate(snapshot["payload"]), version
                ),
                filename=f"adam-define-{version.replace('.', '-')}.xml",
                media_type="application/xml",
                manifest=payload,
                validation_run_id=UUID(str(validation["id"])),
                reconciliation_run_id=UUID(str(payload["reconciliation_run_id"])),
            )
        if artifact_type in {"adam_adrg_docx", "adam_adrg_pdf"}:
            snapshot = cast(dict[str, object], payload["adrg"])
            template = cast(dict[str, object], payload["template"])
            validation = cast(dict[str, object], payload["validation_run"])
            model = AdamAdrgModel.model_validate(snapshot["payload"])
            data = (
                render_docx(_adrg_document(model), template)
                if artifact_type.endswith("_docx")
                else render_pdf(_adrg_document(model), template)
            )
            return RenderedArtifact(
                data=data,
                filename="adrg.docx" if artifact_type.endswith("_docx") else "adrg.pdf",
                media_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    if artifact_type.endswith("_docx")
                    else "application/pdf"
                ),
                manifest=payload,
                validation_run_id=UUID(str(validation["id"])),
                reconciliation_run_id=UUID(str(payload["reconciliation_run_id"])),
            )
        validation = cast(dict[str, object], payload["validation_run"])
        validation_run_id = UUID(str(validation["id"]))
        if artifact_type == "adam_specification":
            content = cast(dict[str, object], payload["specification"])["payload"]
            return RenderedArtifact(
                data=render_specification_xlsx(AdamSpecification.model_validate(content)),
                filename="adam-specification.xlsx",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                manifest=payload,
                validation_run_id=validation_run_id,
            )
        json_outputs: dict[str, tuple[object, str]] = {
            "adam_specification_json": (
                cast(dict[str, object], payload["specification"])["payload"],
                "adam-specification.json",
            ),
            "adam_derivation_plan_json": (
                cast(dict[str, object], payload["source_plan"])["payload"],
                "adam-derivation-plan.json",
            ),
            "adam_validation_report": (validation, "adam-validation.json"),
        }
        if artifact_type in json_outputs:
            content, filename = json_outputs[artifact_type]
            return _json_artifact(content, filename, payload, validation_run_id)
        internal = DataflowIR.model_validate(payload["normalized_ir"])
        if artifact_type == "adam_derivation_report":
            content = {
                "schema_version": "1.0.0",
                "source_plan": payload["source_plan"],
                "ir_fingerprint": payload["ir_fingerprint"],
                "outputs": lineage(internal),
            }
            return _json_artifact(
                content, "adam-derivation-report.json", payload, validation_run_id
            )
        if artifact_type == "adam_traceability_report":
            specification = AdamSpecification.model_validate(
                cast(dict[str, object], payload["specification"])["payload"]
            )
            content = {
                "schema_version": "1.0.0",
                "ir_fingerprint": payload["ir_fingerprint"],
                "outputs": lineage(internal),
                "origins": [
                    {
                        "dataset": dataset.code,
                        "variable": variable.name,
                        "origin": variable.origin.model_dump(mode="json"),
                        "method_id": variable.method_id,
                        "output_node_id": variable.output_node_id,
                    }
                    for dataset in specification.datasets
                    for variable in dataset.variables
                ],
                "trace_targets": [
                    item.model_dump(mode="json") for item in specification.trace_targets
                ],
            }
            return _json_artifact(content, "adam-traceability.json", payload, validation_run_id)
        backends = {
            "adam_program_python": ("python", "adam.py", "text/x-python"),
            "adam_program_r": ("r", "adam.R", "text/x-r-source"),
            "adam_program_sas": ("sas", "adam.sas", "text/plain"),
        }
        backend, filename, media_type = backends[artifact_type]
        program = compile_dataflow(internal, backend)
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
        """Validate ADaM outputs and create deterministic read-back-verified XPTs."""

        specification_record = program_manifest.get("specification")
        normalized = program_manifest.get("normalized_ir")
        if not isinstance(specification_record, dict) or not isinstance(normalized, dict):
            raise ProblemException(
                status_code=422,
                code="execution_manifest_invalid",
                title="Execution manifest is invalid",
                detail="ADaM execution requires frozen Specification and normalized IR inputs.",
            )
        specification = AdamSpecification.model_validate(specification_record.get("payload"))
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
        datasets = {
            dataset.code: dataset for dataset in specification.datasets if dataset.code in writes
        }
        expected_files = {f"{code}.csv" for code in datasets}
        if set(files) != expected_files:
            raise ProblemException(
                status_code=422,
                code="execution_outputs_mismatch",
                title="Execution outputs do not match declarations",
                detail="Produced files must exactly match the ADaM plan writes.",
            )
        if sum(len(data) for data in files.values()) > maximum_bytes:
            raise ProblemException(
                status_code=422,
                code="execution_output_limit_exceeded",
                title="Execution output limit exceeded",
                detail="Produced output bytes exceed the accepted execution limit.",
            )
        products: list[ExecutionProduct] = []
        for code, dataset in sorted(datasets.items()):
            csv_name = f"{code}.csv"
            csv_data = files[csv_name]
            xpt = build_adam_xpt_v5(csv_data, dataset)
            products.extend(
                (
                    ExecutionProduct(
                        artifact_type="adam_dataset_csv",
                        filename=csv_name,
                        media_type="text/csv",
                        data=csv_data,
                        manifest={"schema_version": "1.0.0", "dataset": code},
                    ),
                    ExecutionProduct(
                        artifact_type="adam_dataset_xpt",
                        filename=PurePath(dataset.expected_output_name).name,
                        media_type="application/x-sas-xport",
                        data=xpt.data,
                        manifest=xpt.manifest,
                    ),
                )
            )
        return tuple(products)

    def resolve_entity(self, session: Session, entity_type: str, entity_id: UUID) -> UUID | None:
        if entity_type == "adam_workbench":
            return SqlDependencyCapability.resolve_entity(self, session, entity_type, entity_id)
        if entity_type == "adam_define":
            define_record = session.get(AdamDefineRevision, entity_id)
            return define_record.study_id if define_record is not None else None
        if entity_type == "adam_adrg":
            adrg_record = session.get(AdamAdrgRevision, entity_id)
            return adrg_record.study_id if adrg_record is not None else None
        if entity_type not in {
            "adam_dataset",
            "adam_variable",
            "adam_parameter",
            "adam_value_level",
        }:
            return None
        records = session.scalars(
            select(AdamSpecificationRevision).order_by(
                AdamSpecificationRevision.aggregate_id,
                AdamSpecificationRevision.revision.desc(),
            )
        )
        seen: set[UUID] = set()
        for record in records:
            if record.aggregate_id in seen:
                continue
            seen.add(record.aggregate_id)
            specification = context_from_record(record)
            for dataset in specification.datasets:
                if entity_type == "adam_dataset" and dataset.id == entity_id:
                    return record.study_id
                if entity_type == "adam_variable" and any(
                    variable.id == entity_id for variable in dataset.variables
                ):
                    return record.study_id
                if entity_type == "adam_parameter" and any(
                    parameter.id == entity_id for parameter in dataset.parameters
                ):
                    return record.study_id
                if entity_type == "adam_value_level" and any(
                    item.id == entity_id for item in dataset.value_level_metadata
                ):
                    return record.study_id
        return None


def context_from_record(record: AdamSpecificationRevision) -> AdamSpecification:
    """Restore the strict contract for an immutable Specification revision."""

    return AdamSpecification.model_validate(record.payload)


def plan_from_record(record: AdamDerivationPlanRevision) -> AdamDerivationPlan:
    """Restore the strict contract for an immutable Derivation Plan revision."""

    return AdamDerivationPlan.model_validate(record.payload)


def _json_artifact(
    content: object,
    filename: str,
    manifest: dict[str, object],
    validation_run_id: UUID,
) -> RenderedArtifact:
    """Render a deterministic ADaM JSON artifact."""

    return RenderedArtifact(
        data=json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        ),
        filename=filename,
        media_type="application/json",
        manifest=manifest,
        validation_run_id=validation_run_id,
    )


def _adrg_document(model: AdamAdrgModel) -> RenderDocument:
    """Translate exact ADRG facts and manual narrative to the shared Document model."""

    dataset_evidence = DocumentSection(
        section_id="dataset_evidence",
        heading="Analysis Dataset Evidence",
        tables=(
            DocumentTable(
                headers=(
                    "Dataset",
                    "Label",
                    "Structure",
                    "Rows",
                    "Variables",
                    "Artifact",
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
    execution_evidence = DocumentSection(
        section_id="execution_evidence",
        heading="Program and Execution Evidence",
        tables=(
            DocumentTable(
                headers=("Execution", "Language", "Program", "Program SHA-256", "Outputs"),
                rows=tuple(
                    (
                        str(item.execution_run_id),
                        item.language,
                        str(item.program_artifact_id),
                        item.program_checksum,
                        ", ".join(str(value) for value in item.output_artifact_ids),
                    )
                    for item in model.execution_facts
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
                    ("ADaM Specification revision", str(model.specification_revision)),
                    ("SDTM input-selection revision", str(model.input_selection_revision)),
                    ("ADaM Derivation Plan revision", str(model.plan_revision)),
                    ("ADaM Define revision", str(model.define_revision)),
                    ("Reconciliation run", str(model.reconciliation_run_id)),
                ),
            ),
        ),
    )
    return RenderDocument(
        cover=DocumentCover(title=model.title, document_code="ADRG", version=model.version),
        sections=(dataset_evidence, execution_evidence, *authored, provenance),
    )


def validate_sdtm_sources(plan: AdamDerivationPlan, sdtm_context: dict[str, object]) -> None:
    """Require every SDTM read to resolve in the exact selected SDTM context."""

    available = {
        str(item["dataset_code"])
        for item in cast(list[dict[str, object]], sdtm_context["xpt_artifacts"])
    }
    requested = {node.dataset for node in plan.nodes if node.node_type == "sdtm_read"}
    missing = sorted(requested - available)
    if missing:
        raise ProblemException(
            status_code=422,
            code="adam_sdtm_input_missing",
            title="ADaM SDTM input is missing",
            detail=f"The exact SDTM selection does not contain: {', '.join(missing)}.",
        )


def validate_origins(specification: AdamSpecification, sdtm_context: dict[str, object]) -> None:
    """Resolve every predecessor origin against selected SDTM or declared ADaM metadata."""

    selected_sdtm = {
        str(item["dataset_code"])
        for item in cast(list[dict[str, object]], sdtm_context["xpt_artifacts"])
    }
    sdtm_variables = {
        str(dataset["code"]): {
            str(variable["name"])
            for variable in cast(list[dict[str, object]], dataset["variables"])
        }
        for dataset in cast(list[dict[str, object]], sdtm_context["datasets"])
        if str(dataset["code"]) in selected_sdtm
    }
    adam_variables = {
        dataset.code: {variable.name for variable in dataset.variables}
        for dataset in specification.datasets
    }
    for dataset in specification.datasets:
        origins = [
            *(variable.origin for variable in dataset.variables),
            *(item.origin for item in dataset.value_level_metadata),
        ]
        for origin in origins:
            if origin.origin_type != "Predecessor":
                continue
            source_dataset = cast(str, origin.source_dataset)
            source_variable = cast(str, origin.source_variable)
            available = sdtm_variables if origin.source_kind == "sdtm" else adam_variables
            if source_variable not in available.get(source_dataset, set()):
                raise _invalid_plan(
                    "adam_origin_unresolved",
                    (
                        f"Predecessor origin '{source_dataset}.{source_variable}' "
                        "does not resolve in the exact selected context."
                    ),
                )


def validate_dependency_compatibility(
    adam_selection: DependencySelectionResponse, sdtm_context: dict[str, object]
) -> None:
    """Reject conflicting exact shared Standards or Terminology selections."""

    sdtm_selection = DependencySelectionResponse.model_validate(
        sdtm_context["dependency_selection"]
    )
    adam_standards = {item.purpose: item.standard_version_id for item in adam_selection.standards}
    sdtm_standards = {item.purpose: item.standard_version_id for item in sdtm_selection.standards}
    conflicting_standards = sorted(
        purpose
        for purpose in adam_standards.keys() & sdtm_standards.keys()
        if adam_standards[purpose] != sdtm_standards[purpose]
    )
    adam_terminology = {
        item.scope: (
            item.terminology_release_id,
            item.terminology_extension_revision_ids,
        )
        for item in adam_selection.terminology
    }
    sdtm_terminology = {
        item.scope: (
            item.terminology_release_id,
            item.terminology_extension_revision_ids,
        )
        for item in sdtm_selection.terminology
    }
    conflicting_terminology = sorted(
        scope
        for scope in adam_terminology.keys() & sdtm_terminology.keys()
        if adam_terminology[scope] != sdtm_terminology[scope]
    )
    if conflicting_standards or conflicting_terminology:
        details = [
            *(f"standard purpose '{item}'" for item in conflicting_standards),
            *(f"terminology scope '{item}'" for item in conflicting_terminology),
        ]
        raise ProblemException(
            status_code=409,
            code="adam_sdtm_dependencies_incompatible",
            title="ADaM and SDTM dependencies are incompatible",
            detail=f"Exact shared selections differ for {', '.join(details)}.",
        )


def lower_plan(specification: AdamSpecification, plan: AdamDerivationPlan) -> DataflowIR:
    """Validate ADaM semantics and lower the module-owned plan to Dataflow IR."""

    datasets = {dataset.code: dataset for dataset in specification.datasets}
    methods = {method.id: method for method in specification.methods}
    node_ids = {node.id for node in plan.nodes}
    write_nodes: dict[str, list[str]] = {}
    for node in plan.nodes:
        if node.node_type == "dataset_write":
            write_nodes.setdefault(node.dataset, []).append(node.id)
    duplicate_writes = sorted(
        dataset for dataset, identifiers in write_nodes.items() if len(identifiers) > 1
    )
    if duplicate_writes:
        raise _invalid_plan(
            "adam_plan_output_duplicate",
            f"Datasets may have only one declared write: {', '.join(duplicate_writes)}.",
        )
    internal_nodes: list[dict[str, object]] = []
    writes: set[str] = set()
    for node in plan.nodes:
        if node.node_type == "sdtm_read":
            internal_nodes.append({"node_type": "read", "id": node.id, "dataset": node.dataset})
        elif node.node_type == "adam_read":
            dataset = datasets.get(node.dataset)
            if dataset is None:
                raise _invalid_plan(
                    "adam_plan_predecessor_unknown",
                    f"ADaM predecessor '{node.dataset}' is absent from the Specification.",
                )
            internal_nodes.append(
                {
                    "node_type": "select",
                    "id": node.id,
                    "columns": [variable.name for variable in dataset.variables],
                }
            )
        elif node.node_type == "dataset_write":
            if node.dataset not in datasets:
                raise _invalid_plan(
                    "adam_plan_output_unknown",
                    f"Dataset '{node.dataset}' is absent from the Specification.",
                )
            writes.add(node.dataset)
            internal_nodes.append({"node_type": "write", "id": node.id, "dataset": node.dataset})
        elif node.node_type == "derive":
            dataset = datasets.get(node.target_dataset)
            if dataset is None:
                raise _invalid_plan(
                    "adam_plan_target_unknown",
                    f"Derivation target '{node.target_dataset}' is absent from the Specification.",
                )
            variables = {variable.name for variable in dataset.variables}
            unknown_assignments = sorted(set(node.assignments) - variables)
            if unknown_assignments:
                raise _invalid_plan(
                    "adam_plan_variable_unknown",
                    f"Derivations target unknown variables: {', '.join(unknown_assignments)}.",
                )
            if node.method_id is not None and node.method_id not in methods:
                raise _invalid_plan(
                    "adam_plan_method_unknown", "Derivation method does not resolve."
                )
            parameters = {parameter.code for parameter in dataset.parameters}
            if node.parameter_code is not None and node.parameter_code not in parameters:
                raise _invalid_plan(
                    "adam_plan_parameter_unknown", "Derivation parameter does not resolve."
                )
            internal_nodes.append(
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
            internal_nodes.append(node.model_dump(mode="json"))

    for method in specification.methods:
        if not set(method.plan_node_ids) <= node_ids:
            raise _invalid_plan(
                "adam_plan_method_nodes_unknown", f"Method '{method.id}' references unknown nodes."
            )
    for dataset in specification.datasets:
        for variable in dataset.variables:
            if variable.output_node_id not in node_ids:
                raise _invalid_plan(
                    "adam_plan_variable_lineage_missing",
                    f"Variable '{dataset.code}.{variable.name}' has no resolved output node.",
                )
    required_writes = {
        dataset.code
        for dataset in specification.datasets
        if any(variable.origin.origin_type == "Derived" for variable in dataset.variables)
    }
    if not required_writes <= writes:
        missing = ", ".join(sorted(required_writes - writes))
        raise _invalid_plan(
            "adam_plan_output_coverage_missing",
            f"Derived targets require dataset writes for: {missing}.",
        )
    _validate_dataset_dependencies(plan, writes)
    return DataflowIR.model_validate(
        {
            "nodes": internal_nodes,
            "edges": [
                Edge(source_node=edge.source_node, target_node=edge.target_node).model_dump()
                for edge in plan.edges
            ],
        }
    )


def _validate_dataset_dependencies(plan: AdamDerivationPlan, writes: set[str]) -> None:
    node_outgoing: dict[str, list[str]] = {node.id: [] for node in plan.nodes}
    write_by_node = {
        node.id: node.dataset for node in plan.nodes if node.node_type == "dataset_write"
    }
    write_node_by_dataset = {dataset: node_id for node_id, dataset in write_by_node.items()}
    edge_pairs = {(edge.source_node, edge.target_node) for edge in plan.edges}
    for edge in plan.edges:
        node_outgoing[edge.source_node].append(edge.target_node)
    dependencies: dict[str, set[str]] = {dataset: set() for dataset in writes}
    for node in plan.nodes:
        if node.node_type != "adam_read":
            continue
        if node.dataset not in writes:
            raise _invalid_plan(
                "adam_plan_predecessor_output_missing",
                f"ADaM read '{node.dataset}' has no declared dataset output.",
            )
        if (write_node_by_dataset[node.dataset], node.id) not in edge_pairs:
            raise _invalid_plan(
                "adam_plan_predecessor_edge_missing",
                (
                    f"ADaM read '{node.id}' must consume the declared "
                    f"'{node.dataset}' dataset write."
                ),
            )
        pending = list(node_outgoing[node.id])
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            if current in write_by_node:
                dependencies[node.dataset].add(write_by_node[current])
            pending.extend(node_outgoing[current])

    visiting: set[str] = set()
    complete: set[str] = set()

    def visit(dataset: str) -> None:
        if dataset in visiting:
            raise _invalid_plan(
                "adam_plan_dataset_cycle",
                "ADaM dataset predecessor dependencies must be acyclic.",
            )
        if dataset in complete:
            return
        visiting.add(dataset)
        for target in dependencies.get(dataset, set()):
            visit(target)
        visiting.remove(dataset)
        complete.add(dataset)

    for dataset in dependencies:
        visit(dataset)


def _invalid_plan(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=422,
        code=code,
        title="ADaM Derivation Plan is invalid",
        detail=detail,
    )
