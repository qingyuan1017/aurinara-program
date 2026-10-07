"""Raw application capability, immutable context export, and artifact rendering."""

import hashlib
import io
import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.models import SourceFile
from app.artifacts.storage import ObjectStorage
from app.common.problems import ProblemException
from app.kernel.dependencies import RenderedArtifact, SqlDependencyCapability
from app.raw.files import inspect_file, read_rows
from app.raw.models import (
    RawDataset,
    RawDatasetFileBinding,
    RawVariable,
    RawWorkbench,
)
from app.reconciliation.service import ReconciliationEvaluation
from app.validation.models import ValidationRun

RAW_ARTIFACT_TYPES = (
    "raw_dependency_manifest",
    "raw_metadata_json",
    "raw_data_dictionary_xlsx",
    "raw_validation_report_json",
)


def _reconciliation_issue(
    code: str,
    *,
    dataset_id: str,
    dataset: str,
    variable: str | None = None,
    field_path: str | None = None,
) -> dict[str, object]:
    return {
        "id": f"{code}:{dataset}:{variable or ''}:{field_path or ''}",
        "code": code,
        "severity": "error",
        "message": "Maintained Raw metadata does not reconcile with the exact source file.",
        "suggestion": "Correct the maintained physical metadata or bind the intended file.",
        "module": "raw",
        "entity_type": "raw_dataset",
        "entity_id": dataset_id,
        "field_path": field_path,
        "dataset": dataset,
        "variable": variable,
        "artifact_id": None,
    }


@dataclass(frozen=True, slots=True)
class RawCapability(SqlDependencyCapability):
    """Raw module boundary used by artifacts, review, reconciliation, and SDTM."""

    def resolve_entity(self, session: Session, entity_type: str, entity_id: UUID) -> UUID | None:
        if entity_type == "raw_workbench":
            return SqlDependencyCapability.resolve_entity(self, session, entity_type, entity_id)
        if entity_type == "raw_dataset":
            dataset = session.get(RawDataset, entity_id)
            return dataset.study_id if dataset is not None else None
        if entity_type == "raw_variable":
            variable = session.get(RawVariable, entity_id)
            return variable.study_id if variable is not None else None
        return None

    def resolve_reconciliation(
        self,
        session: Session,
        study_id: UUID,
        reconciliation_type: str,
        inputs: list[dict[str, object]],
        options: dict[str, object],
    ) -> dict[str, object]:
        """Resolve one exact Raw revision and every bound source artifact."""

        if reconciliation_type != "raw_source_schema":
            raise ValueError("unsupported Raw reconciliation type")
        if options:
            raise ValueError("Raw source/schema reconciliation does not accept options")
        raw_inputs = [item for item in inputs if item.get("entity_type") == "raw_workbench"]
        if len(raw_inputs) != 1:
            raise ValueError("Raw reconciliation requires one exact workbench revision")
        raw_id = UUID(str(raw_inputs[0]["entity_id"]))
        raw_revision = int(str(raw_inputs[0]["revision"]))
        raw = session.get(RawWorkbench, raw_id)
        if raw is None or raw.study_id != study_id or raw.revision != raw_revision:
            raise ValueError("Raw reconciliation workbench input is stale")
        context = self.context_snapshot(session, raw.id, study_id)
        datasets = cast(list[dict[str, object]], context["datasets"])
        expected_artifacts: dict[str, str] = {}
        resolved_datasets: list[dict[str, object]] = []
        for dataset in datasets:
            source_snapshot = cast(dict[str, object], dataset["source_file"])
            source = session.get(SourceFile, UUID(str(source_snapshot["id"])))
            if source is None or source.study_id != study_id:
                raise ValueError("Raw reconciliation source file is unavailable")
            expected_artifacts[str(source.artifact_id)] = source.sha256
            resolved_datasets.append(
                {
                    "id": dataset["id"],
                    "code": dataset["code"],
                    "revision": dataset["revision"],
                    "variables": dataset["variables"],
                    "source_file": {
                        "id": str(source.id),
                        "artifact_id": str(source.artifact_id),
                        "filename": source.filename,
                        "checksum": source.sha256,
                        "_object_key": source.object_key,
                    },
                }
            )
        supplied_artifacts = {
            str(item["artifact_id"]): str(item["checksum"])
            for item in inputs
            if item.get("artifact_id") is not None
        }
        if supplied_artifacts != expected_artifacts:
            raise ValueError("Raw reconciliation artifact inputs do not match current bindings")
        return {
            "study_id": str(study_id),
            "reconciliation_type": reconciliation_type,
            "raw_id": str(raw.id),
            "raw_revision": raw.revision,
            "dependency_selection_revision": context["dependency_selection_revision"],
            "dependency_fingerprint": context["dependency_fingerprint"],
            "datasets": resolved_datasets,
        }

    def evaluate_reconciliation(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> ReconciliationEvaluation:
        """Compare maintained physical metadata with exact immutable source bytes."""

        issues: list[dict[str, object]] = []
        evidence_datasets: list[dict[str, object]] = []
        datasets = cast(list[dict[str, object]], payload["datasets"])
        if not datasets:
            issues.append(
                {
                    "id": f"raw_dataset_required:{payload['raw_id']}",
                    "code": "raw_dataset_required",
                    "severity": "error",
                    "message": "Raw source/schema reconciliation requires an active dataset.",
                    "suggestion": "Register and initialize at least one Raw dataset.",
                    "module": "raw",
                    "entity_type": "raw_workbench",
                    "entity_id": payload["raw_id"],
                    "field_path": "datasets",
                    "dataset": None,
                    "variable": None,
                    "artifact_id": None,
                }
            )
        for dataset in datasets:
            dataset_id = str(dataset["id"])
            dataset_code = str(dataset["code"])
            source = cast(dict[str, object], dataset["source_file"])
            try:
                with storage.open(str(source["_object_key"])) as stream:
                    digest = hashlib.sha256()
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                if digest.hexdigest() != source["checksum"]:
                    issues.append(
                        _reconciliation_issue(
                            "raw_source_checksum_mismatch",
                            dataset_id=dataset_id,
                            dataset=dataset_code,
                        )
                    )
                    continue
                with storage.open(str(source["_object_key"])) as stream:
                    physical = inspect_file(stream, str(source["filename"]))
            except ProblemException as error:
                issues.append(
                    _reconciliation_issue(
                        error.code,
                        dataset_id=dataset_id,
                        dataset=dataset_code,
                    )
                )
                continue
            maintained = {
                str(item["name"]): item
                for item in cast(list[dict[str, object]], dataset["variables"])
            }
            observed = {item.name: item for item in physical.columns}
            for name in sorted(observed.keys() - maintained.keys()):
                issues.append(
                    _reconciliation_issue(
                        "raw_variable_missing",
                        dataset_id=dataset_id,
                        dataset=dataset_code,
                        variable=name,
                    )
                )
            for name in sorted(maintained.keys() - observed.keys()):
                issues.append(
                    _reconciliation_issue(
                        "raw_variable_not_in_source",
                        dataset_id=dataset_id,
                        dataset=dataset_code,
                        variable=name,
                    )
                )
            for name in sorted(maintained.keys() & observed.keys()):
                variable = maintained[name]
                column = observed[name]
                comparisons = (
                    ("physical_type", variable.get("physical_type"), column.physical_type),
                    ("ordinal", variable.get("ordinal"), column.ordinal),
                )
                for field_path, expected, actual in comparisons:
                    if expected != actual:
                        issues.append(
                            _reconciliation_issue(
                                f"raw_variable_{field_path}_mismatch",
                                dataset_id=dataset_id,
                                dataset=dataset_code,
                                variable=name,
                                field_path=field_path,
                            )
                        )
                for field_path, observed_value in (
                    ("length", column.length),
                    ("precision", column.precision),
                ):
                    maintained_value = variable.get(field_path)
                    if (
                        observed_value is not None
                        and maintained_value is not None
                        and int(str(observed_value)) > int(str(maintained_value))
                    ):
                        issues.append(
                            _reconciliation_issue(
                                f"raw_variable_{field_path}_exceeded",
                                dataset_id=dataset_id,
                                dataset=dataset_code,
                                variable=name,
                                field_path=field_path,
                            )
                        )
            evidence_datasets.append(
                {
                    "dataset_id": dataset_id,
                    "dataset": dataset_code,
                    "dataset_revision": dataset["revision"],
                    "source_artifact_id": source["artifact_id"],
                    "source_checksum": source["checksum"],
                    "row_count": physical.row_count,
                    "physical_schema": physical.model_dump(mode="json"),
                }
            )
        return ReconciliationEvaluation(
            issues=tuple(issues),
            evidence={
                "raw_id": payload["raw_id"],
                "raw_revision": payload["raw_revision"],
                "dependency_selection_revision": payload["dependency_selection_revision"],
                "dependency_fingerprint": payload["dependency_fingerprint"],
                "datasets": evidence_datasets,
            },
        )

    def context_snapshot(self, session: Session, raw_id: UUID, study_id: UUID) -> dict[str, object]:
        raw = cast(RawWorkbench, self.require(session, raw_id, study_id))
        datasets = tuple(
            session.scalars(
                select(RawDataset)
                .where(RawDataset.raw_id == raw.id, RawDataset.status == "active")
                .order_by(RawDataset.code)
            )
        )
        dataset_payloads: list[dict[str, object]] = []
        for dataset in datasets:
            source = session.get(SourceFile, dataset.current_source_file_id)
            if source is None:
                raise RuntimeError("Raw dataset source file is missing")
            variables = tuple(
                session.scalars(
                    select(RawVariable)
                    .where(RawVariable.dataset_id == dataset.id)
                    .order_by(RawVariable.ordinal)
                )
            )
            dataset_payloads.append(
                {
                    "id": str(dataset.id),
                    "code": dataset.code,
                    "label": dataset.label,
                    "description": dataset.description,
                    "revision": dataset.revision,
                    "source_file": {
                        "id": str(source.id),
                        "artifact_id": str(source.artifact_id),
                        "filename": source.filename,
                        "media_type": source.media_type,
                        "sha256": source.sha256,
                        "size": source.size,
                    },
                    "variables": [
                        {
                            "id": str(variable.id),
                            "name": variable.name,
                            "label": variable.label,
                            "physical_type": variable.physical_type,
                            "length": variable.length,
                            "precision": variable.precision,
                            "ordinal": variable.ordinal,
                            "role": variable.role,
                            "description": variable.description,
                            "terminology_binding": variable.terminology_binding,
                            "revision": variable.revision,
                        }
                        for variable in variables
                    ],
                }
            )
        selection = self.get_selection(session, raw.id, study_id)
        return {
            "schema_version": "1.0.0",
            "raw_id": str(raw.id),
            "raw_revision": raw.revision,
            "dependency_selection_revision": selection.revision,
            "dependency_fingerprint": selection.fingerprint,
            "datasets": dataset_payloads,
        }

    def read_context_dataset(
        self,
        session: Session,
        storage: ObjectStorage,
        *,
        raw_id: UUID,
        study_id: UUID,
        dataset_code: str,
        artifact_id: UUID,
        expected_checksum: str,
        maximum_rows: int = 10_000,
    ) -> tuple[dict[str, object | None], ...]:
        """Read an exact active Raw input through the owning module boundary."""

        self.require(session, raw_id, study_id)
        dataset = session.scalar(
            select(RawDataset).where(
                RawDataset.raw_id == raw_id,
                RawDataset.study_id == study_id,
                RawDataset.code == dataset_code,
                RawDataset.status == "active",
            )
        )
        if dataset is None:
            raise ProblemException(
                status_code=422,
                code="raw_context_dataset_missing",
                title="Raw context dataset is unavailable",
                detail=f"Active Raw dataset '{dataset_code}' does not exist.",
            )
        source = session.get(SourceFile, dataset.current_source_file_id)
        if (
            source is None
            or source.study_id != study_id
            or source.artifact_id != artifact_id
            or source.sha256 != expected_checksum
        ):
            raise ProblemException(
                status_code=409,
                code="raw_context_dataset_stale",
                title="Raw context dataset is stale",
                detail=f"Raw dataset '{dataset_code}' no longer matches the selected artifact.",
            )
        with storage.open(source.object_key) as stream:
            headers, values = read_rows(stream, source.filename)
        if len(values) > maximum_rows:
            raise ProblemException(
                status_code=422,
                code="raw_preview_input_too_large",
                title="Raw preview input is too large",
                detail=f"Raw preview inputs are limited to {maximum_rows} rows per dataset.",
            )
        return tuple(
            {name: row[index] if index < len(row) else None for index, name in enumerate(headers)}
            for row in values
        )

    def build_artifact_payload(
        self, session: Session, aggregate_id: UUID, study_id: UUID, artifact_type: str
    ) -> dict[str, object]:
        if artifact_type == "raw_dependency_manifest":
            return SqlDependencyCapability.build_artifact_payload(
                self, session, aggregate_id, study_id, artifact_type
            )
        if artifact_type not in RAW_ARTIFACT_TYPES:
            raise ProblemException(
                status_code=422,
                code="artifact_type_unsupported",
                title="Artifact type is unsupported",
                detail=f"Raw does not build '{artifact_type}'.",
            )
        base = SqlDependencyCapability.build_artifact_payload(
            self, session, aggregate_id, study_id, "raw_dependency_manifest"
        )
        context = self.context_snapshot(session, aggregate_id, study_id)
        run = session.scalar(
            select(ValidationRun)
            .where(
                ValidationRun.module_key == "raw",
                ValidationRun.owner_type == "raw_workbench",
                ValidationRun.owner_id == aggregate_id,
                ValidationRun.status == "succeeded",
            )
            .order_by(ValidationRun.completed_at.desc())
        )
        if run is None:
            raise ProblemException(
                status_code=409,
                code="successful_validation_required",
                title="Successful validation is required",
                detail="Validate the current Raw revision before building artifacts.",
            )
        if run.input_manifest.get("raw_revision") != context["raw_revision"]:
            raise ProblemException(
                status_code=409,
                code="stale_validation_run",
                title="Validation evidence is stale",
                detail="Revalidate the current Raw revision before building artifacts.",
            )
        return {
            **base,
            "artifact_type": artifact_type,
            "raw_context": context,
            "validation_run": {
                "id": str(run.id),
                "input_fingerprint": run.input_fingerprint,
                "warning_count": run.warning_count,
            },
        }

    def render_artifact(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> RenderedArtifact:
        artifact_type = str(payload.get("artifact_type", "raw_dependency_manifest"))
        if artifact_type == "raw_dependency_manifest":
            return SqlDependencyCapability.render_artifact(self, payload, storage)
        del storage
        context = cast(dict[str, object], payload["raw_context"])
        validation = cast(dict[str, object], payload["validation_run"])
        validation_run_id = UUID(str(validation["id"]))
        if artifact_type == "raw_metadata_json":
            data = json.dumps(
                context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            return RenderedArtifact(
                data=data,
                filename="raw-metadata.json",
                media_type="application/json",
                manifest=payload,
                validation_run_id=validation_run_id,
            )
        if artifact_type == "raw_validation_report_json":
            data = json.dumps(
                validation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            return RenderedArtifact(
                data=data,
                filename="raw-validation-report.json",
                media_type="application/json",
                manifest=payload,
                validation_run_id=validation_run_id,
            )
        if artifact_type == "raw_data_dictionary_xlsx":
            workbook = Workbook()
            sheet = workbook.active
            if sheet is None:
                raise RuntimeError("new workbook has no active worksheet")
            sheet.title = "Variables"
            sheet.append(
                [
                    "dataset",
                    "variable",
                    "label",
                    "physical_type",
                    "length",
                    "precision",
                    "ordinal",
                    "role",
                    "description",
                ]
            )
            for dataset in cast(list[dict[str, object]], context["datasets"]):
                for variable in cast(list[dict[str, object]], dataset["variables"]):
                    sheet.append(
                        [
                            dataset["code"],
                            variable["name"],
                            variable["label"],
                            variable["physical_type"],
                            variable["length"],
                            variable["precision"],
                            variable["ordinal"],
                            variable["role"],
                            variable["description"],
                        ]
                    )
            stream = io.BytesIO()
            workbook.save(stream)
            return RenderedArtifact(
                data=stream.getvalue(),
                filename="raw-data-dictionary.xlsx",
                media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                manifest=payload,
                validation_run_id=validation_run_id,
            )
        raise RuntimeError(f"unsupported Raw artifact type: {artifact_type}")


def binding_for(
    dataset: RawDataset, source: SourceFile, *, created_by: str
) -> RawDatasetFileBinding:
    """Create an immutable binding row from checked study-owned inputs."""

    return RawDatasetFileBinding(
        dataset_id=dataset.id,
        study_id=dataset.study_id,
        dataset_revision=dataset.revision,
        source_file_id=source.id,
        source_artifact_id=source.artifact_id,
        source_sha256=source.sha256,
        created_by=created_by,
    )
