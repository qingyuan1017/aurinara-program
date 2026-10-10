"""TLF authoring, Analysis IR lowering, compilation, execution, and rendering."""

import csv
import io
import json
import struct
import zlib
from dataclasses import dataclass
from typing import cast
from uuid import UUID

import pyarrow as pa
import pyarrow.parquet as parquet
from pydantic import BaseModel
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.artifacts.storage import ObjectStorage
from app.common.canonical import fingerprint
from app.common.problems import ProblemException
from app.execution.contracts import ExecutionProduct
from app.execution.models import ExecutionRun
from app.kernel.dependencies import RenderedArtifact, SqlDependencyCapability
from app.packaging.contracts import PackageContribution
from app.templates.models import TemplateVersion
from app.tlf.contracts import (
    TlfArs,
    TlfAssumptions,
    TlfBindings,
    TlfProgramPlan,
    TlfShell,
)
from app.tlf.models import TlfAuthoringRevision, TlfWorkbench
from app.transformation.analysis import (
    analysis_ir_fingerprint,
    canonical_analysis_ir,
    compile_analysis,
)
from app.transformation.contracts import AnalysisIR, AnalysisProcedure
from app.validation.models import ValidationRun

TLF_CONTENT_TYPES = ("shell", "bindings", "assumptions", "ars", "program_plan")
TLF_PROGRAM_ARTIFACT_TYPES = ("tlf_program_python", "tlf_program_r", "tlf_program_sas")
TLF_RENDER_ARTIFACT_TYPES = (
    "tlf_table_rtf",
    "tlf_table_pdf",
    "tlf_listing_rtf",
    "tlf_listing_pdf",
    "tlf_figure_png",
    "tlf_figure_svg",
    "tlf_figure_pdf",
)
TLF_BUILD_ARTIFACT_TYPES = (
    "tlf_dependency_manifest",
    "tlf_shell_json",
    "tlf_bindings_json",
    "tlf_assumptions_json",
    "tlf_ars_json",
    "tlf_program_plan_json",
    "tlf_validation_report",
    "tlf_output_index",
    *TLF_PROGRAM_ARTIFACT_TYPES,
    *TLF_RENDER_ARTIFACT_TYPES,
)
TLF_ARTIFACT_TYPES = (
    *TLF_BUILD_ARTIFACT_TYPES,
    "tlf_result_csv",
    "tlf_result_parquet",
    "tlf_execution_log",
)

_CONTRACTS: dict[str, type[BaseModel]] = {
    "shell": TlfShell,
    "bindings": TlfBindings,
    "assumptions": TlfAssumptions,
    "ars": TlfArs,
    "program_plan": TlfProgramPlan,
}


def _conflict(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=409,
        code=code,
        title="TLF operation is blocked",
        detail=detail,
    )


def content_contract(record: TlfAuthoringRevision) -> object:
    """Parse one persisted revision through its closed content contract."""

    contract = _CONTRACTS.get(record.content_type)
    if contract is None:
        raise RuntimeError(f"unsupported TLF content type: {record.content_type}")
    return contract.model_validate(record.payload)


@dataclass(frozen=True, slots=True)
class TlfCapability(SqlDependencyCapability):
    """TLF module boundary over manually authored revisions and immutable evidence."""

    def package_contributions(
        self,
        session: Session,
        study_id: UUID,
        artifacts: tuple[Artifact, ...],
        options: dict[str, object],
    ) -> tuple[PackageContribution, ...]:
        """Require TLF results and rendered outputs to come from one exact run."""

        contributions = SqlDependencyCapability.package_contributions(
            self, session, study_id, artifacts, options
        )
        run_ids: set[UUID] = set()
        for artifact in artifacts:
            run_id = artifact.execution_run_id
            execution_snapshot = artifact.manifest.get("execution_run")
            if run_id is None and isinstance(execution_snapshot, dict):
                try:
                    run_id = UUID(str(execution_snapshot["id"]))
                except (KeyError, ValueError) as error:
                    raise ProblemException(
                        status_code=422,
                        code="tlf_package_lineage_invalid",
                        title="TLF package lineage is invalid",
                        detail="A rendered TLF artifact has malformed execution lineage.",
                    ) from error
            if run_id is not None:
                run = session.get(ExecutionRun, run_id)
                if run is None or run.study_id != study_id or run.status != "succeeded":
                    raise ProblemException(
                        status_code=422,
                        code="tlf_package_run_invalid",
                        title="TLF package execution run is invalid",
                        detail="Every TLF result and output must bind one successful run.",
                    )
                run_ids.add(run_id)
        if len(run_ids) > 1:
            raise ProblemException(
                status_code=409,
                code="tlf_package_mixed_run",
                title="TLF package selection mixes execution runs",
                detail="Select the result and rendered outputs from one successful execution run.",
            )
        return contributions

    def latest_content(
        self, session: Session, aggregate_id: UUID, content_type: str
    ) -> TlfAuthoringRevision | None:
        return session.scalar(
            select(TlfAuthoringRevision)
            .where(
                TlfAuthoringRevision.aggregate_id == aggregate_id,
                TlfAuthoringRevision.content_type == content_type,
            )
            .order_by(TlfAuthoringRevision.revision.desc())
        )

    def current_authoring(
        self, session: Session, aggregate_id: UUID
    ) -> dict[str, TlfAuthoringRevision]:
        records = {
            content_type: self.latest_content(session, aggregate_id, content_type)
            for content_type in TLF_CONTENT_TYPES
        }
        missing = [key for key, value in records.items() if value is None]
        if missing:
            raise _conflict(
                "tlf_authoring_incomplete",
                f"Author the following TLF resources first: {', '.join(missing)}.",
            )
        return {key: cast(TlfAuthoringRevision, value) for key, value in records.items()}

    def validate_bindings(self, session: Session, study_id: UUID, bindings: TlfBindings) -> None:
        """Resolve every exact ADaM binding without accessing ADaM repositories."""

        issues: list[dict[str, object]] = []
        for selected in bindings.datasets:
            artifact = session.get(Artifact, selected.artifact_id)
            validation = session.get(ValidationRun, selected.validation_run_id)
            valid_artifact = (
                artifact is not None
                and artifact.study_id == study_id
                and artifact.module_key == "adam"
                and artifact.artifact_type in {"adam_dataset_csv", "adam_dataset_xpt"}
                and artifact.owner_id == selected.adam_id
                and artifact.status == "available"
                and artifact.sha256 == selected.checksum
                and artifact.dependency_fingerprint == selected.dependency_fingerprint
                and artifact.manifest.get("dataset") == selected.dataset_code
            )
            valid_validation = (
                validation is not None
                and validation.study_id == study_id
                and validation.module_key == "adam"
                and validation.owner_id == selected.adam_id
                and validation.status == "succeeded"
                and validation.error_count == 0
                and validation.input_manifest.get("adam_revision") == selected.adam_revision
                and artifact is not None
                and artifact.validation_run_id == validation.id
            )
            execution = (
                session.get(ExecutionRun, artifact.execution_run_id)
                if artifact is not None and artifact.execution_run_id is not None
                else None
            )
            valid_execution = (
                execution is not None
                and execution.study_id == study_id
                and execution.owner_id == selected.adam_id
                and execution.status == "succeeded"
            )
            if not (valid_artifact and valid_validation and valid_execution):
                issues.append(
                    {
                        "code": "tlf_adam_binding_invalid",
                        "binding_id": selected.id,
                        "artifact_id": str(selected.artifact_id),
                    }
                )
        if issues:
            raise ProblemException(
                status_code=422,
                code="tlf_bindings_invalid",
                title="TLF ADaM bindings are invalid",
                detail="Every binding must resolve to exact validated ADaM evidence.",
                issues=issues,
            )

    def validate_authoring(
        self, session: Session, aggregate_id: UUID, study_id: UUID
    ) -> tuple[dict[str, TlfAuthoringRevision], AnalysisIR]:
        records = self.current_authoring(session, aggregate_id)
        shell = cast(TlfShell, content_contract(records["shell"]))
        bindings = cast(TlfBindings, content_contract(records["bindings"]))
        ars = cast(TlfArs, content_contract(records["ars"]))
        plan = cast(TlfProgramPlan, content_contract(records["program_plan"]))
        self.validate_bindings(session, study_id, bindings)
        available_columns = _adam_columns(session, bindings)

        pinned = {
            "shell": plan.shell_revision,
            "bindings": plan.bindings_revision,
            "assumptions": plan.assumptions_revision,
            "ars": plan.ars_revision,
        }
        mismatched = [key for key, revision in pinned.items() if records[key].revision != revision]
        if mismatched:
            raise _conflict(
                "tlf_program_plan_misaligned",
                "Save a ProgramPlan revision pinned to the current "
                f"{', '.join(mismatched)} revision(s).",
            )
        leaf_ids = {row.id for row in shell.rows if row.leaf}
        analysis_leaf_ids = {item.leaf_row_id for item in ars.analyses}
        if leaf_ids != analysis_leaf_ids:
            raise ProblemException(
                status_code=422,
                code="tlf_leaf_coverage_invalid",
                title="TLF shell leaf coverage is invalid",
                detail="ARS must contain exactly one analysis for every leaf shell row.",
                issues=[
                    {
                        "missing_leaf_rows": sorted(leaf_ids - analysis_leaf_ids),
                        "extra_leaf_rows": sorted(analysis_leaf_ids - leaf_ids),
                    }
                ],
            )
        analyses = {item.id: item for item in ars.analyses}
        named = {item.id: item for item in bindings.named}
        for step in plan.steps:
            analysis = analyses.get(step.analysis_id)
            if analysis is None:
                continue
            columns = available_columns[analysis.dataset_binding_id]
            referenced = {step.variable, *step.group_by}
            population = named.get(analysis.population_binding_id)
            parameter = (
                named.get(analysis.parameter_binding_id)
                if analysis.parameter_binding_id is not None
                else None
            )
            if population is not None:
                referenced.add(population.variable)
            if parameter is not None:
                referenced.add(parameter.variable)
            missing_columns = sorted(referenced - columns)
            if missing_columns:
                raise ProblemException(
                    status_code=422,
                    code="tlf_adam_variable_unknown",
                    title="TLF ADaM variable reference is unknown",
                    detail="Every filter, analysis, and grouping variable must resolve.",
                    issues=[
                        {
                            "analysis_id": step.analysis_id,
                            "missing_variables": missing_columns,
                        }
                    ],
                )
        return records, lower_analysis_ir(shell, bindings, ars, plan)

    def _current_validation(
        self,
        session: Session,
        aggregate_id: UUID,
        records: dict[str, TlfAuthoringRevision],
        internal: AnalysisIR,
    ) -> ValidationRun:
        expected = authoring_manifest(self, session, aggregate_id, records, internal)
        runs = session.scalars(
            select(ValidationRun)
            .where(
                ValidationRun.module_key == "tlf",
                ValidationRun.owner_type == "tlf_workbench",
                ValidationRun.owner_id == aggregate_id,
                ValidationRun.status == "succeeded",
                ValidationRun.error_count == 0,
            )
            .order_by(ValidationRun.created_at.desc())
        )
        validation = next(
            (run for run in runs if run.input_fingerprint == fingerprint(expected)), None
        )
        if validation is None:
            raise _conflict(
                "successful_validation_required",
                "Validate the current aligned TLF authoring before building artifacts.",
            )
        return validation

    def build_artifact_payload(
        self,
        session: Session,
        aggregate_id: UUID,
        study_id: UUID,
        artifact_type: str,
        *,
        domain_code: str | None = None,
    ) -> dict[str, object]:
        del domain_code
        if artifact_type == "tlf_dependency_manifest":
            return SqlDependencyCapability.build_artifact_payload(
                self, session, aggregate_id, study_id, artifact_type
            )
        if artifact_type not in TLF_BUILD_ARTIFACT_TYPES:
            raise ProblemException(
                status_code=422,
                code="artifact_type_unsupported",
                title="Artifact type is unsupported",
                detail=f"TLF does not build '{artifact_type}'.",
            )
        workbench = session.get(TlfWorkbench, aggregate_id)
        if workbench is None or workbench.study_id != study_id:
            raise RuntimeError("TLF workbench is missing")
        records, internal = self.validate_authoring(session, aggregate_id, study_id)
        validation = self._current_validation(session, aggregate_id, records, internal)
        base = SqlDependencyCapability.build_artifact_payload(
            self, session, aggregate_id, study_id, "tlf_dependency_manifest"
        )
        bindings = cast(TlfBindings, content_contract(records["bindings"]))
        plan = cast(TlfProgramPlan, content_contract(records["program_plan"]))
        payload: dict[str, object] = {
            **base,
            "artifact_type": artifact_type,
            "input_selection": {
                "revision": records["bindings"].revision,
                "fingerprint": records["bindings"].fingerprint,
                "payload": {
                    "xpt_artifacts": [
                        {
                            "artifact_id": str(item.artifact_id),
                            "dataset_code": item.dataset_code,
                            "checksum": item.checksum,
                        }
                        for item in bindings.datasets
                    ]
                },
            },
            "specification": {
                "revision": records["shell"].revision,
                "fingerprint": records["shell"].fingerprint,
                "payload": records["shell"].payload,
            },
            "source_plan": {
                "type": "tlf_program_plan",
                "revision": records["program_plan"].revision,
                "fingerprint": records["program_plan"].fingerprint,
                "payload": records["program_plan"].payload,
            },
            "authoring": {
                key: {
                    "revision": record.revision,
                    "fingerprint": record.fingerprint,
                    "payload": record.payload,
                }
                for key, record in records.items()
            },
            "normalized_ir": canonical_analysis_ir(internal),
            "ir_fingerprint": analysis_ir_fingerprint(internal),
            "result_filename": plan.output_filename,
            "validation_run": {
                "id": str(validation.id),
                "input_fingerprint": validation.input_fingerprint,
                "warning_count": validation.warning_count,
                "issues": validation.issues,
            },
        }
        if artifact_type in TLF_RENDER_ARTIFACT_TYPES:
            dependency_selection = self.get_selection(session, aggregate_id, study_id)
            template_selections = [
                item
                for item in dependency_selection.templates
                if item.artifact_type == artifact_type
            ]
            if len(template_selections) != 1:
                raise _conflict(
                    "artifact_template_selection_required",
                    "Select one exact compatible Template version for this TLF output format.",
                )
            template = session.get(TemplateVersion, template_selections[0].template_version_id)
            if template is None:
                raise RuntimeError("validated TLF Template version is missing")
            payload["template"] = {
                "id": str(template.id),
                "version": template.version,
                "checksum": template.checksum,
                "renderer_versions": template.renderer_versions,
                "blank_structure": template.blank_structure,
            }
        if artifact_type in TLF_RENDER_ARTIFACT_TYPES or artifact_type == "tlf_output_index":
            result, run = self._current_result(session, aggregate_id, records, internal)
            payload["execution_run"] = {
                "id": str(run.id),
                "language": run.language,
                "program_artifact_id": str(run.program_artifact_id),
            }
            payload["result"] = {
                "id": str(result.id),
                "sha256": result.sha256,
                "filename": result.filename,
                "object_key": result.object_key,
            }
        return payload

    def _current_result(
        self,
        session: Session,
        aggregate_id: UUID,
        records: dict[str, TlfAuthoringRevision],
        internal: AnalysisIR,
    ) -> tuple[Artifact, ExecutionRun]:
        runs = session.scalars(
            select(ExecutionRun)
            .where(
                ExecutionRun.module_key == "tlf",
                ExecutionRun.owner_id == aggregate_id,
                ExecutionRun.status == "succeeded",
                ExecutionRun.source_specification_revision == records["shell"].revision,
                ExecutionRun.source_plan_revision == records["program_plan"].revision,
                ExecutionRun.input_selection_revision == records["bindings"].revision,
                ExecutionRun.compiler_fingerprint == analysis_ir_fingerprint(internal),
            )
            .order_by(ExecutionRun.completed_at.desc())
        )
        for run in runs:
            outputs = [session.get(Artifact, UUID(value)) for value in run.output_artifact_ids]
            results = [
                item
                for item in outputs
                if item is not None
                and item.status == "available"
                and item.artifact_type == "tlf_result_csv"
                and item.execution_run_id == run.id
            ]
            if len(results) == 1:
                return results[0], run
        raise _conflict(
            "tlf_current_result_required",
            "Execute the current validated ProgramPlan before rendering output.",
        )

    def render_artifact(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> RenderedArtifact:
        artifact_type = str(payload.get("artifact_type", "tlf_dependency_manifest"))
        if artifact_type == "tlf_dependency_manifest":
            return SqlDependencyCapability.render_artifact(self, payload, storage)
        validation = cast(dict[str, object], payload["validation_run"])
        validation_id = UUID(str(validation["id"]))
        json_types = {
            "tlf_shell_json": "shell",
            "tlf_bindings_json": "bindings",
            "tlf_assumptions_json": "assumptions",
            "tlf_ars_json": "ars",
            "tlf_program_plan_json": "program_plan",
        }
        if artifact_type in json_types:
            name = json_types[artifact_type]
            authoring = cast(dict[str, dict[str, object]], payload["authoring"])
            return _json_product(
                authoring[name]["payload"],
                f"tlf-{name.replace('_', '-')}.json",
                payload,
                validation_id,
            )
        if artifact_type == "tlf_validation_report":
            return _json_product(validation, "tlf-validation.json", payload, validation_id)
        if artifact_type in TLF_PROGRAM_ARTIFACT_TYPES:
            internal = AnalysisIR.model_validate(payload["normalized_ir"])
            backend = artifact_type.removeprefix("tlf_program_")
            program = compile_analysis(internal, backend, str(payload["result_filename"]))
            suffix = {"python": "py", "r": "R", "sas": "sas"}[backend]
            media_type = {"python": "text/x-python", "r": "text/x-r-source", "sas": "text/plain"}[
                backend
            ]
            return RenderedArtifact(
                data=program.source.encode("utf-8"),
                filename=f"tlf.{suffix}",
                media_type=media_type,
                manifest={
                    **payload,
                    "compiler": {
                        "backend": backend,
                        "version": program.compiler_version,
                        "fingerprint": program.ir_fingerprint,
                    },
                },
                validation_run_id=validation_id,
            )
        result = cast(dict[str, object], payload["result"])
        with storage.open(str(result["object_key"])) as body:
            result_bytes = body.read()
        public_manifest = {key: value for key, value in payload.items() if key != "result"}
        public_manifest["result"] = {
            key: value for key, value in result.items() if key != "object_key"
        }
        if artifact_type == "tlf_output_index":
            index = {
                "schema_version": "1.0.0",
                "output": cast(dict[str, dict[str, object]], payload["authoring"])["shell"],
                "execution_run": payload["execution_run"],
                "result": public_manifest["result"],
                "program_plan": payload["source_plan"],
                "ir_fingerprint": payload["ir_fingerprint"],
            }
            return _json_product(index, "tlf-output-index.json", public_manifest, validation_id)
        shell_payload = cast(dict[str, dict[str, object]], payload["authoring"])["shell"]["payload"]
        shell = TlfShell.model_validate(shell_payload)
        rows = _read_result(result_bytes)
        data, filename, media_type = _render_output(artifact_type, shell, rows)
        return RenderedArtifact(
            data=data,
            filename=filename,
            media_type=media_type,
            manifest=public_manifest,
            validation_run_id=validation_id,
        )

    def prepare_execution_outputs(
        self,
        program_manifest: dict[str, object],
        files: dict[str, bytes],
        maximum_bytes: int,
    ) -> tuple[ExecutionProduct, ...]:
        expected = str(program_manifest.get("result_filename", ""))
        if set(files) != {expected}:
            raise ProblemException(
                status_code=422,
                code="execution_outputs_mismatch",
                title="Execution outputs do not match declarations",
                detail="TLF execution must produce exactly the declared normalized result file.",
            )
        data = files[expected]
        if len(data) > maximum_bytes:
            raise ProblemException(
                status_code=422,
                code="execution_output_limit_exceeded",
                title="Execution output limit exceeded",
                detail="The normalized TLF result exceeds the accepted limit.",
            )
        rows = _read_result(data)
        normalized = program_manifest.get("normalized_ir")
        if not isinstance(normalized, dict) or not isinstance(normalized.get("procedures"), list):
            raise ProblemException(
                status_code=422,
                code="execution_manifest_invalid",
                title="Execution manifest is invalid",
                detail="The frozen normalized Analysis IR is missing.",
            )
        procedures = cast(list[dict[str, object]], normalized["procedures"])
        analyses: set[str] = set()
        for procedure in procedures:
            parameters = procedure.get("parameters")
            if not isinstance(parameters, dict) or "analysis_id" not in parameters:
                raise ProblemException(
                    status_code=422,
                    code="execution_manifest_invalid",
                    title="Execution manifest is invalid",
                    detail="An Analysis IR procedure has no analysis identity.",
                )
            analyses.add(str(parameters["analysis_id"]))
        observed = {row["analysis_id"] for row in rows}
        if not observed.issubset(analyses):
            raise ProblemException(
                status_code=422,
                code="tlf_result_analysis_unknown",
                title="TLF result contains an unknown analysis",
                detail="Every result row must resolve to the frozen Analysis IR.",
            )
        table = pa.Table.from_pylist(
            rows, schema=pa.schema([(name, pa.string()) for name in _RESULT_HEADERS])
        )
        parquet_buffer = io.BytesIO()
        parquet.write_table(
            table,
            parquet_buffer,
            compression="snappy",
            use_dictionary=False,
            write_statistics=True,
        )
        if len(data) + parquet_buffer.tell() > maximum_bytes:
            raise ProblemException(
                status_code=422,
                code="execution_output_limit_exceeded",
                title="Execution output limit exceeded",
                detail="The normalized CSV and Parquet TLF results exceed the accepted limit.",
            )
        common_manifest = {
            "schema_version": "1.0.0",
            "analysis_ids": sorted(observed),
            "row_count": len(rows),
            "ir_fingerprint": program_manifest["ir_fingerprint"],
        }
        return (
            ExecutionProduct(
                artifact_type="tlf_result_csv",
                filename=expected,
                media_type="text/csv",
                data=data,
                manifest={**common_manifest, "format": "csv"},
            ),
            ExecutionProduct(
                artifact_type="tlf_result_parquet",
                filename=f"{expected.removesuffix('.csv')}.parquet",
                media_type="application/vnd.apache.parquet",
                data=parquet_buffer.getvalue(),
                manifest={**common_manifest, "format": "parquet"},
            ),
        )


def lower_analysis_ir(
    shell: TlfShell, bindings: TlfBindings, ars: TlfArs, plan: TlfProgramPlan
) -> AnalysisIR:
    """Lower TLF semantics while deliberately excluding all presentation fields."""

    del shell
    datasets = {item.id: item for item in bindings.datasets}
    named = {item.id: item for item in bindings.named}
    analyses = {item.id: item for item in ars.analyses}
    step_ids = {item.analysis_id for item in plan.steps}
    if step_ids != set(analyses):
        raise ProblemException(
            status_code=422,
            code="tlf_analysis_step_coverage_invalid",
            title="TLF analysis step coverage is invalid",
            detail="ProgramPlan must contain exactly one step for every ARS analysis.",
        )
    procedures: list[AnalysisProcedure] = []
    for step in sorted(plan.steps, key=lambda item: item.order):
        analysis = analyses[step.analysis_id]
        dataset = datasets.get(analysis.dataset_binding_id)
        population = named.get(analysis.population_binding_id)
        parameter = (
            named.get(analysis.parameter_binding_id) if analysis.parameter_binding_id else None
        )
        statistic = named.get(analysis.statistic_binding_id)
        if dataset is None or population is None or statistic is None:
            raise ProblemException(
                status_code=422,
                code="tlf_reference_invalid",
                title="TLF reference is invalid",
                detail="ARS dataset, population, parameter, and statistic references must resolve.",
            )
        expected = {
            "population": population,
            "statistic": statistic,
            "parameter": parameter,
        }
        invalid = [
            kind
            for kind, binding in expected.items()
            if binding is not None
            and (binding.kind != kind or binding.dataset_binding_id != dataset.id)
        ]
        if invalid or statistic.value != step.method:
            raise ProblemException(
                status_code=422,
                code="tlf_binding_kind_invalid",
                title="TLF binding kind is invalid",
                detail="Bindings must match the referenced dataset and declared analysis method.",
            )
        parameters: dict[str, str | int | float | bool | None] = {
            "analysis_id": analysis.id,
            "row_id": analysis.leaf_row_id,
            "variable": step.variable,
            "population_variable": population.variable,
            "population_value": population.value,
        }
        if parameter is not None:
            parameters["parameter_variable"] = parameter.variable
            parameters["parameter_value"] = parameter.value
        procedures.append(
            AnalysisProcedure(
                id=step.id,
                method=step.method,
                input_dataset=dataset.dataset_code,
                grouping=step.group_by,
                parameters=parameters,
                result_schema={
                    "analysis_id": "string",
                    "row_id": "string",
                    "group": "string",
                    "statistic": "string",
                    "value": "string",
                    "text": "string",
                },
                tolerance=step.tolerance,
            )
        )
    return AnalysisIR(procedures=tuple(procedures))


def _adam_columns(session: Session, bindings: TlfBindings) -> dict[str, set[str]]:
    """Read frozen ADaM metadata DTOs carried by exact immutable artifacts."""

    result: dict[str, set[str]] = {}
    for binding in bindings.datasets:
        artifact = session.get(Artifact, binding.artifact_id)
        if artifact is None:
            raise RuntimeError("validated ADaM artifact is missing")
        snapshot = artifact.manifest.get("source_specification")
        if not isinstance(snapshot, dict):
            snapshot = artifact.manifest.get("specification")
        payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
        datasets = payload.get("datasets") if isinstance(payload, dict) else None
        selected = (
            next(
                (
                    item
                    for item in datasets
                    if isinstance(item, dict) and item.get("code") == binding.dataset_code
                ),
                None,
            )
            if isinstance(datasets, list)
            else None
        )
        variables = selected.get("variables") if isinstance(selected, dict) else None
        if not isinstance(variables, list):
            raise ProblemException(
                status_code=422,
                code="tlf_adam_context_missing",
                title="TLF ADaM context is missing",
                detail=("The exact ADaM artifact must carry its frozen Specification metadata."),
                issues=[{"binding_id": binding.id, "dataset": binding.dataset_code}],
            )
        result[binding.id] = {
            str(item["name"]) for item in variables if isinstance(item, dict) and "name" in item
        }
    return result


def authoring_manifest(
    capability: TlfCapability,
    session: Session,
    aggregate_id: UUID,
    records: dict[str, TlfAuthoringRevision],
    internal: AnalysisIR,
) -> dict[str, object]:
    workbench = session.get(TlfWorkbench, aggregate_id)
    if workbench is None:
        raise RuntimeError("TLF workbench is missing")
    selection = capability.get_selection(session, aggregate_id, workbench.study_id)
    return {
        "tlf_revision": workbench.revision,
        "dependency_selection_revision": selection.revision,
        "dependency_fingerprint": selection.fingerprint,
        "authoring_revisions": {key: value.revision for key, value in records.items()},
        "authoring_fingerprints": {key: value.fingerprint for key, value in records.items()},
        "normalized_ir": canonical_analysis_ir(internal),
        "ir_fingerprint": analysis_ir_fingerprint(internal),
    }


def _json_product(
    content: object,
    filename: str,
    manifest: dict[str, object],
    validation_id: UUID,
) -> RenderedArtifact:
    return RenderedArtifact(
        data=json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        ),
        filename=filename,
        media_type="application/json",
        manifest=manifest,
        validation_run_id=validation_id,
    )


_RESULT_HEADERS = ("analysis_id", "row_id", "group", "statistic", "value", "text")


def _read_result(data: bytes) -> list[dict[str, str]]:
    try:
        text = data.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        if tuple(reader.fieldnames or ()) != _RESULT_HEADERS:
            raise ValueError("unexpected result columns")
        rows = [{key: str(row.get(key, "")) for key in _RESULT_HEADERS} for row in reader]
    except (UnicodeDecodeError, csv.Error, ValueError) as error:
        raise ProblemException(
            status_code=422,
            code="tlf_result_invalid",
            title="TLF normalized result is invalid",
            detail="The result must be UTF-8 CSV with the declared normalized columns.",
        ) from error
    return rows


def _render_output(
    artifact_type: str, shell: TlfShell, rows: list[dict[str, str]]
) -> tuple[bytes, str, str]:
    extension = artifact_type.rsplit("_", 1)[-1]
    filename = f"{shell.output_code.lower()}.{extension}"
    if extension == "rtf":
        lines = [shell.title, shell.subtitle or ""] + [
            " | ".join(row[key] for key in ("row_id", "group", "statistic", "text")) for row in rows
        ]
        escaped = [
            line.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}") for line in lines
        ]
        return (
            ("{\\rtf1\\ansi\n" + "\\par\n".join(escaped) + "\n}").encode("utf-8"),
            filename,
            "application/rtf",
        )
    if extension == "svg":
        labels = "".join(
            f'<text x="20" y="{80 + index * 24}" font-size="14">{_xml(row["text"])}</text>'
            for index, row in enumerate(rows[:15])
        )
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">'
            '<rect width="100%" height="100%" fill="white"/>'
            f'<text x="20" y="35" font-size="22">{_xml(shell.title)}</text>{labels}</svg>'
        )
        return svg.encode("utf-8"), filename, "image/svg+xml"
    if extension == "png":
        return _figure_png(rows, 800, 600), filename, "image/png"
    buffer = io.BytesIO()
    pagesize = landscape(A4) if shell.orientation == "landscape" else A4
    page = canvas.Canvas(buffer, pagesize=pagesize, invariant=1)
    page.setTitle(shell.title)
    page.drawString(40, pagesize[1] - 40, shell.title)
    y = pagesize[1] - 70
    for row in rows:
        page.drawString(
            40, y, " | ".join(row[key] for key in ("row_id", "group", "statistic", "text"))[:130]
        )
        y -= 16
        if y < 40:
            page.showPage()
            y = pagesize[1] - 40
    page.save()
    return buffer.getvalue(), filename, "application/pdf"


def _xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _figure_png(rows: list[dict[str, str]], width: int, height: int) -> bytes:
    """Create a deterministic bar figure from normalized numeric result values."""

    pixels = bytearray(b"\xff\xff\xff" * width * height)
    values: list[float] = []
    for row in rows[:15]:
        try:
            values.append(max(0.0, float(row["value"])))
        except ValueError:
            values.append(0.0)
    maximum = max(values, default=0.0) or 1.0
    for index, value in enumerate(values):
        top = 50 + index * 32
        bottom = min(top + 18, height - 1)
        right = min(40 + int((width - 80) * value / maximum), width - 40)
        for y in range(top, bottom):
            for x in range(40, right):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = b"\x28\x63\xa5"
    raw = b"".join(
        b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3]) for y in range(height)
    )

    def chunk(name: bytes, value: bytes) -> bytes:
        return (
            struct.pack(">I", len(value))
            + name
            + value
            + struct.pack(">I", zlib.crc32(name + value))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
