"""Version-neutral ADaM Define metadata authoring and factual initialization."""

from datetime import datetime
from typing import Annotated, Literal, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adam.contracts import (
    AdamDataset,
    AdamDefineInitialize,
    AdamDefineLeaf,
    AdamDefineModel,
    AdamInputSelectionWrite,
    AdamMethod,
    AdamSpecification,
)
from app.adam.define_xml import GENERATOR_VERSION as DEFINE_XML_GENERATOR_VERSION
from app.adam.define_xml import define_schema_fingerprint, render_define_xml
from app.adam.models import (
    AdamDefineRevision,
    AdamInputSelection,
    AdamSpecificationRevision,
    AdamWorkbench,
)
from app.adam.validation_versions import DEFINE_VALIDATOR_NAME, DEFINE_VALIDATOR_VERSION
from app.api.auth import Principal, get_principal
from app.api.dependencies import get_module_registry, get_session
from app.artifacts.builds import ArtifactBuildCreate, ArtifactBuildResponse, create_artifact_build
from app.artifacts.models import Artifact
from app.artifacts.service import ArtifactService
from app.common.canonical import fingerprint
from app.common.etag import etag_for_revision, require_matching_etag
from app.common.problems import ProblemException
from app.common.time import utc_now
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry
from app.reconciliation.routes import (
    ReconciliationCreate,
    ReconciliationInput,
    ReconciliationResponse,
    create_reconciliation,
)
from app.studies.service import StudyService
from app.validation.models import ValidationRun
from app.validation.routes import ValidationRunResponse

router = APIRouter(tags=["adam-define"])
studies = StudyService()
artifacts = ArtifactService()


class SdtmContextExporter(Protocol):
    """Narrow SDTM-owned context boundary required by Define validation."""

    def context_snapshot(
        self, session: Session, sdtm_id: UUID, study_id: UUID
    ) -> dict[str, object]: ...


class DefineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    aggregate_id: UUID
    study_id: UUID
    revision: int
    schema_version: str
    specification_revision: int
    input_selection_revision: int
    output_artifact_ids: list[str]
    payload: dict[str, object]
    fingerprint: str
    created_by: str
    created_at: datetime


class DefineReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    define_revision: int = Field(ge=1)
    expected_define_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class DefineArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    versions: tuple[Literal["2.0", "2.1"], ...] = Field(min_length=1)
    expected_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("versions")
    @classmethod
    def unique_versions(
        cls, value: tuple[Literal["2.0", "2.1"], ...]
    ) -> tuple[Literal["2.0", "2.1"], ...]:
        if len(value) != len(set(value)):
            raise ValueError("Define-XML versions must be unique")
        return value


def _problem(status_code: int, code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=status_code,
        code=code,
        title="ADaM Define metadata is invalid",
        detail=detail,
    )


def _workbench(session: Session, adam_id: UUID, principal: Principal) -> AdamWorkbench:
    record = session.get(AdamWorkbench, adam_id)
    if record is None:
        raise _problem(404, "adam_not_found", "The ADaM workbench does not exist.")
    studies.require_access(session, record.study_id, principal)
    return record


def _latest_define(session: Session, adam_id: UUID) -> AdamDefineRevision | None:
    return session.scalar(
        select(AdamDefineRevision)
        .where(AdamDefineRevision.aggregate_id == adam_id)
        .order_by(AdamDefineRevision.revision.desc())
    )


def _latest_specification(session: Session, adam_id: UUID) -> AdamSpecificationRevision:
    record = session.scalar(
        select(AdamSpecificationRevision)
        .where(AdamSpecificationRevision.aggregate_id == adam_id)
        .order_by(AdamSpecificationRevision.revision.desc())
    )
    if record is None:
        raise _problem(
            409, "adam_specification_required", "Save an ADaM Specification before Define."
        )
    return record


def _input_selection(session: Session, adam_id: UUID) -> AdamInputSelection:
    record = session.scalar(
        select(AdamInputSelection).where(AdamInputSelection.aggregate_id == adam_id)
    )
    if record is None or record.state != "current":
        raise _problem(
            409,
            "adam_input_selection_required",
            "Select an exact current SDTM context before Define.",
        )
    return record


def _outputs(
    session: Session,
    workbench: AdamWorkbench,
    specification_revision: int,
    input_selection_revision: int,
    identifiers: tuple[UUID, ...],
) -> dict[str, Artifact]:
    outputs: dict[str, Artifact] = {}
    for identifier in identifiers:
        artifact = session.get(Artifact, identifier)
        dataset = artifact.manifest.get("dataset") if artifact is not None else None
        if (
            artifact is None
            or artifact.study_id != workbench.study_id
            or artifact.module_key != "adam"
            or artifact.owner_type != "adam_workbench"
            or artifact.owner_id != workbench.id
            or artifact.artifact_type != "adam_dataset_xpt"
            or artifact.status != "available"
            or artifact.source_specification_revision != specification_revision
            or artifact.input_selection_revision != input_selection_revision
            or not isinstance(dataset, str)
        ):
            raise _problem(
                422,
                "adam_define_output_invalid",
                "Every Define output must be an exact available ADaM XPT for current authoring.",
            )
        if dataset in outputs:
            raise _problem(
                422,
                "adam_define_output_duplicate",
                "Only one exact output may be selected for each ADaM dataset.",
            )
        outputs[dataset] = artifact
    return outputs


def _initialize_model(
    current: AdamDefineModel | None,
    command: AdamDefineInitialize,
    specification_record: AdamSpecificationRevision,
    selection: AdamInputSelection,
    outputs: dict[str, Artifact],
) -> AdamDefineModel:
    specification = AdamSpecification.model_validate(specification_record.payload)
    datasets: dict[str, AdamDataset] = {
        item.code: item for item in (current.datasets if current is not None else ())
    }
    for source in specification.datasets:
        existing = datasets.get(source.code)
        if existing is None:
            datasets[source.code] = source
            continue
        known = {item.id for item in existing.variables}
        additions = tuple(item for item in source.variables if item.id not in known)
        if additions:
            datasets[source.code] = existing.model_copy(
                update={"variables": (*existing.variables, *additions)}
            )
    methods: dict[str, AdamMethod] = {
        item.id: item for item in (current.methods if current is not None else ())
    }
    for method in specification.methods:
        methods.setdefault(method.id, method)
    leaves = tuple(
        AdamDefineLeaf(
            id=f"LF.{code}",
            title=artifact.filename,
            href=artifact.filename,
            artifact_id=artifact.id,
            checksum=artifact.sha256,
        )
        for code, artifact in sorted(outputs.items())
    )
    return AdamDefineModel(
        specification_revision=specification_record.revision,
        input_selection_revision=selection.revision,
        study_oid=current.study_oid if current else command.study_oid,
        metadata_version_oid=(
            current.metadata_version_oid if current else command.metadata_version_oid
        ),
        name=current.name if current else command.name,
        description=current.description if current else command.description,
        standard_name=current.standard_name if current else command.standard_name,
        standard_version=current.standard_version if current else command.standard_version,
        output_artifact_ids=command.output_artifact_ids,
        datasets=tuple(datasets[code] for code in sorted(datasets)),
        methods=tuple(methods[identifier] for identifier in sorted(methods)),
        leaves=leaves,
    )


def _validate_bindings(
    specification: AdamSpecificationRevision,
    selection: AdamInputSelection,
    model: AdamDefineModel,
    outputs: dict[str, Artifact],
) -> None:
    if model.specification_revision != specification.revision:
        raise _problem(
            409,
            "adam_define_specification_misaligned",
            "Define must bind the current ADaM Specification revision.",
        )
    if model.input_selection_revision != selection.revision:
        raise _problem(
            409,
            "adam_define_input_misaligned",
            "Define must bind the current exact SDTM input selection revision.",
        )
    leaves = {item.artifact_id: item for item in model.leaves}
    for artifact in outputs.values():
        leaf = leaves.get(artifact.id)
        if leaf is None or leaf.checksum != artifact.sha256 or leaf.href != artifact.filename:
            raise _problem(
                422,
                "adam_define_leaf_invalid",
                "Every Define leaf must match its exact output filename and checksum.",
            )


def _selected_sdtm_context(
    session: Session,
    registry: ModuleRegistry,
    workbench: AdamWorkbench,
    selection: AdamInputSelection,
) -> dict[str, object]:
    """Resolve the exact current SDTM metadata selected by the ADaM aggregate."""

    command = AdamInputSelectionWrite.model_validate(
        {
            key: value
            for key, value in selection.payload.items()
            if key != "sdtm_context_fingerprint"
        }
    )
    provider = cast(
        SdtmContextExporter,
        registry.require_handler("sdtm", ModuleCapability.CONTEXT_EXPORT),
    )
    context = provider.context_snapshot(session, command.sdtm_id, workbench.study_id)
    if (
        context.get("sdtm_revision") != command.sdtm_revision
        or context.get("dependency_fingerprint") != command.sdtm_dependency_fingerprint
    ):
        raise _problem(
            409,
            "adam_define_sdtm_context_stale",
            "The exact SDTM context selected by ADaM is no longer current.",
        )
    eligible = {
        (str(item["artifact_id"]), str(item["dataset_code"]), str(item["checksum"]))
        for item in cast(list[dict[str, object]], context["xpt_artifacts"])
    }
    selected = {
        (str(item.artifact_id), item.dataset_code, item.checksum)
        for item in command.xpt_artifacts
    }
    if not selected <= eligible:
        raise _problem(
            409,
            "adam_define_sdtm_context_stale",
            "A selected SDTM XPT is no longer eligible in the current SDTM context.",
        )
    return {
        **context,
        "datasets": [
            item
            for item in cast(list[dict[str, object]], context["datasets"])
            if str(item["code"]) in {row.dataset_code for row in command.xpt_artifacts}
        ],
        "xpt_artifacts": [
            item
            for item in cast(list[dict[str, object]], context["xpt_artifacts"])
            if (
                str(item["artifact_id"]),
                str(item["dataset_code"]),
                str(item["checksum"]),
            )
            in selected
        ],
    }


def _compare_component(
    issues: list[dict[str, object]],
    *,
    expected: object,
    observed: object,
    code: str,
    dataset: str | None,
    subject: str | None,
    field_path: str,
) -> None:
    if expected != observed:
        issues.append(
            _issue(
                code,
                dataset,
                subject,
                field_path=field_path,
                message="ADaM Define metadata differs from the current Specification.",
            )
        )


def validate_define_metadata(
    specification: AdamSpecification,
    model: AdamDefineModel,
    sdtm_context: dict[str, object],
) -> list[dict[str, object]]:
    """Compare all factual Define metadata with Specification and exact SDTM context."""

    issues: list[dict[str, object]] = []
    expected_datasets = {item.code: item for item in specification.datasets}
    observed_datasets = {item.code: item for item in model.datasets}
    for code in sorted(expected_datasets.keys() - observed_datasets.keys()):
        issues.append(_issue("adam_define_dataset_missing", code, None))
    for code in sorted(observed_datasets.keys() - expected_datasets.keys()):
        issues.append(_issue("adam_define_dataset_extra", code, None))
    for code in sorted(expected_datasets.keys() & observed_datasets.keys()):
        expected_dataset = expected_datasets[code]
        observed_dataset = observed_datasets[code]
        _compare_component(
            issues,
            expected=expected_dataset.model_dump(
                mode="json", exclude={"variables", "parameters", "value_level_metadata"}
            ),
            observed=observed_dataset.model_dump(
                mode="json", exclude={"variables", "parameters", "value_level_metadata"}
            ),
            code="adam_define_dataset_metadata_mismatch",
            dataset=code,
            subject=None,
            field_path=f"datasets[{code}]",
        )
        expected_variables = {item.id: item for item in expected_dataset.variables}
        observed_variables = {item.id: item for item in observed_dataset.variables}
        for identifier in sorted(expected_variables.keys() - observed_variables.keys(), key=str):
            variable = expected_variables[identifier]
            issues.append(
                _issue(
                    "adam_define_variable_missing",
                    code,
                    variable.name,
                    field_path=f"datasets[{code}].variables[{identifier}]",
                )
            )
        for identifier in sorted(observed_variables.keys() - expected_variables.keys(), key=str):
            variable = observed_variables[identifier]
            issues.append(
                _issue(
                    "adam_define_variable_extra",
                    code,
                    variable.name,
                    field_path=f"datasets[{code}].variables[{identifier}]",
                )
            )
        for identifier in sorted(expected_variables.keys() & observed_variables.keys(), key=str):
            expected_variable = expected_variables[identifier]
            observed_variable = observed_variables[identifier]
            path = f"datasets[{code}].variables[{identifier}]"
            _compare_component(
                issues,
                expected=expected_variable.model_dump(
                    mode="json", exclude={"origin", "method_id", "terminology_binding"}
                ),
                observed=observed_variable.model_dump(
                    mode="json", exclude={"origin", "method_id", "terminology_binding"}
                ),
                code="adam_define_variable_metadata_mismatch",
                dataset=code,
                subject=expected_variable.name,
                field_path=path,
            )
            _compare_component(
                issues,
                expected=expected_variable.origin,
                observed=observed_variable.origin,
                code="adam_define_origin_mismatch",
                dataset=code,
                subject=expected_variable.name,
                field_path=f"{path}.origin",
            )
            _compare_component(
                issues,
                expected=expected_variable.method_id,
                observed=observed_variable.method_id,
                code="adam_define_method_binding_mismatch",
                dataset=code,
                subject=expected_variable.name,
                field_path=f"{path}.method_id",
            )
            _compare_component(
                issues,
                expected=expected_variable.terminology_binding,
                observed=observed_variable.terminology_binding,
                code="adam_define_terminology_binding_mismatch",
                dataset=code,
                subject=expected_variable.name,
                field_path=f"{path}.terminology_binding",
            )
        expected_parameters = {item.id: item for item in expected_dataset.parameters}
        observed_parameters = {item.id: item for item in observed_dataset.parameters}
        for identifier in sorted(expected_parameters.keys() - observed_parameters.keys(), key=str):
            parameter = expected_parameters[identifier]
            issues.append(
                _issue(
                    "adam_define_parameter_missing",
                    code,
                    parameter.code,
                    field_path=f"datasets[{code}].parameters[{identifier}]",
                )
            )
        for identifier in sorted(observed_parameters.keys() - expected_parameters.keys(), key=str):
            parameter = observed_parameters[identifier]
            issues.append(
                _issue(
                    "adam_define_parameter_extra",
                    code,
                    parameter.code,
                    field_path=f"datasets[{code}].parameters[{identifier}]",
                )
            )
        for identifier in sorted(expected_parameters.keys() & observed_parameters.keys(), key=str):
            expected_parameter = expected_parameters[identifier]
            observed_parameter = observed_parameters[identifier]
            path = f"datasets[{code}].parameters[{identifier}]"
            _compare_component(
                issues,
                expected=expected_parameter.model_dump(
                    mode="json", exclude={"terminology_binding"}
                ),
                observed=observed_parameter.model_dump(
                    mode="json", exclude={"terminology_binding"}
                ),
                code="adam_define_parameter_metadata_mismatch",
                dataset=code,
                subject=expected_parameter.code,
                field_path=path,
            )
            _compare_component(
                issues,
                expected=expected_parameter.terminology_binding,
                observed=observed_parameter.terminology_binding,
                code="adam_define_terminology_binding_mismatch",
                dataset=code,
                subject=expected_parameter.code,
                field_path=f"{path}.terminology_binding",
            )
        expected_value_levels = {
            item.id: item for item in expected_dataset.value_level_metadata
        }
        observed_value_levels = {
            item.id: item for item in observed_dataset.value_level_metadata
        }
        for identifier in sorted(
            expected_value_levels.keys() - observed_value_levels.keys(), key=str
        ):
            issues.append(
                _issue(
                    "adam_define_value_level_missing",
                    code,
                    str(identifier),
                    field_path=f"datasets[{code}].value_level_metadata[{identifier}]",
                )
            )
        for identifier in sorted(
            observed_value_levels.keys() - expected_value_levels.keys(), key=str
        ):
            issues.append(
                _issue(
                    "adam_define_value_level_extra",
                    code,
                    str(identifier),
                    field_path=f"datasets[{code}].value_level_metadata[{identifier}]",
                )
            )
        for identifier in sorted(
            expected_value_levels.keys() & observed_value_levels.keys(), key=str
        ):
            expected_value = expected_value_levels[identifier]
            observed_value = observed_value_levels[identifier]
            path = f"datasets[{code}].value_level_metadata[{identifier}]"
            _compare_component(
                issues,
                expected=expected_value.model_dump(
                    mode="json", exclude={"origin", "method_id", "terminology_binding"}
                ),
                observed=observed_value.model_dump(
                    mode="json", exclude={"origin", "method_id", "terminology_binding"}
                ),
                code="adam_define_value_level_metadata_mismatch",
                dataset=code,
                subject=str(identifier),
                field_path=path,
            )
            _compare_component(
                issues,
                expected=expected_value.origin,
                observed=observed_value.origin,
                code="adam_define_origin_mismatch",
                dataset=code,
                subject=str(identifier),
                field_path=f"{path}.origin",
            )
            _compare_component(
                issues,
                expected=expected_value.method_id,
                observed=observed_value.method_id,
                code="adam_define_method_binding_mismatch",
                dataset=code,
                subject=str(identifier),
                field_path=f"{path}.method_id",
            )
            _compare_component(
                issues,
                expected=expected_value.terminology_binding,
                observed=observed_value.terminology_binding,
                code="adam_define_terminology_binding_mismatch",
                dataset=code,
                subject=str(identifier),
                field_path=f"{path}.terminology_binding",
            )

    expected_methods = {item.id: item for item in specification.methods}
    observed_methods = {item.id: item for item in model.methods}
    for method_identifier in sorted(expected_methods.keys() - observed_methods.keys()):
        issues.append(
            _issue(
                "adam_define_method_missing",
                None,
                method_identifier,
                field_path=f"methods[{method_identifier}]",
            )
        )
    for method_identifier in sorted(observed_methods.keys() - expected_methods.keys()):
        issues.append(
            _issue(
                "adam_define_method_extra",
                None,
                method_identifier,
                field_path=f"methods[{method_identifier}]",
            )
        )
    for method_identifier in sorted(expected_methods.keys() & observed_methods.keys()):
        _compare_component(
            issues,
            expected=expected_methods[method_identifier],
            observed=observed_methods[method_identifier],
            code="adam_define_method_metadata_mismatch",
            dataset=None,
            subject=method_identifier,
            field_path=f"methods[{method_identifier}]",
        )

    sdtm_variables = {
        str(dataset["code"]): {
            str(variable["name"])
            for variable in cast(list[dict[str, object]], dataset["variables"])
        }
        for dataset in cast(list[dict[str, object]], sdtm_context["datasets"])
    }
    adam_variables = {
        dataset.code: {variable.name for variable in dataset.variables}
        for dataset in model.datasets
    }
    for dataset in model.datasets:
        origins = [
            *(
                (variable.name, variable.origin, f"variables[{variable.id}].origin")
                for variable in dataset.variables
            ),
            *(
                (str(value.id), value.origin, f"value_level_metadata[{value.id}].origin")
                for value in dataset.value_level_metadata
            ),
        ]
        for subject, origin, suffix in origins:
            if origin.origin_type != "Predecessor":
                continue
            available = sdtm_variables if origin.source_kind == "sdtm" else adam_variables
            if origin.source_variable not in available.get(str(origin.source_dataset), set()):
                issues.append(
                    _issue(
                        "adam_define_predecessor_unresolved",
                        dataset.code,
                        subject,
                        field_path=f"datasets[{dataset.code}].{suffix}",
                        message=(
                            "The predecessor does not resolve in the exact selected SDTM "
                            "context or maintained ADaM metadata."
                        ),
                    )
                )
    return issues


def _save(
    session: Session,
    workbench: AdamWorkbench,
    model: AdamDefineModel,
    principal: Principal,
) -> AdamDefineRevision:
    current = _latest_define(session, workbench.id)
    payload = model.model_dump(mode="json")
    record = AdamDefineRevision(
        aggregate_id=workbench.id,
        study_id=workbench.study_id,
        revision=1 if current is None else current.revision + 1,
        schema_version=model.schema_version,
        specification_revision=model.specification_revision,
        input_selection_revision=model.input_selection_revision,
        output_artifact_ids=[str(item) for item in model.output_artifact_ids],
        payload=payload,
        fingerprint=fingerprint(payload),
        created_by=principal.subject,
    )
    session.add(record)
    workbench.revision += 1
    artifacts.mark_owner_stale(
        session,
        owner_type="adam_workbench",
        owner_id=workbench.id,
        artifact_types=(
            "adam_define_xml_20",
            "adam_define_xml_21",
            "adam_adrg_docx",
            "adam_adrg_pdf",
        ),
    )
    return record


def _current_validation(session: Session, record: AdamDefineRevision) -> ValidationRun | None:
    schemas = {
        "2.0": define_schema_fingerprint("2.0"),
        "2.1": define_schema_fingerprint("2.1"),
    }
    candidates = session.scalars(
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
    return next(
        (
            item
            for item in candidates
            if item.input_manifest.get("define_revision") == record.revision
            and item.input_manifest.get("define_fingerprint") == record.fingerprint
            and item.input_manifest.get("define_xml_schema_fingerprints") == schemas
            and item.input_manifest.get("define_xml_generator_version")
            == DEFINE_XML_GENERATOR_VERSION
            and item.validator_name == DEFINE_VALIDATOR_NAME
            and item.validator_version == DEFINE_VALIDATOR_VERSION
        ),
        None,
    )


@router.get("/adams/{adam_id}/define", response_model=DefineResponse)
def get_define(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> DefineResponse:
    workbench = _workbench(session, adam_id, principal)
    record = _latest_define(session, workbench.id)
    if record is None:
        raise _problem(404, "adam_define_not_found", "ADaM Define metadata is not saved.")
    return DefineResponse.model_validate(record)


@router.put("/adams/{adam_id}/define", response_model=DefineResponse)
def put_define(
    adam_id: UUID,
    command: AdamDefineModel,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DefineResponse:
    workbench = _workbench(session, adam_id, principal)
    require_matching_etag(if_match, workbench.revision)
    specification = _latest_specification(session, workbench.id)
    selection = _input_selection(session, workbench.id)
    outputs = _outputs(
        session,
        workbench,
        specification.revision,
        selection.revision,
        command.output_artifact_ids,
    )
    _validate_bindings(specification, selection, command, outputs)
    record = _save(session, workbench, command, principal)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return DefineResponse.model_validate(record)


@router.post("/adams/{adam_id}/define/initialize", response_model=DefineResponse)
def initialize_define(
    adam_id: UUID,
    command: AdamDefineInitialize,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DefineResponse:
    workbench = _workbench(session, adam_id, principal)
    require_matching_etag(if_match, workbench.revision)
    current_record = _latest_define(session, workbench.id)
    current_revision = current_record.revision if current_record else None
    if command.expected_define_revision != current_revision:
        raise _problem(
            409,
            "adam_define_revision_mismatch",
            "The expected Define revision does not match the current saved revision.",
        )
    current = AdamDefineModel.model_validate(current_record.payload) if current_record else None
    if current is not None and current.output_artifact_ids != command.output_artifact_ids:
        raise _problem(
            409,
            "adam_define_output_selection_conflict",
            "Initialization cannot replace an existing exact output selection; use PUT.",
        )
    specification = _latest_specification(session, workbench.id)
    selection = _input_selection(session, workbench.id)
    outputs = _outputs(
        session,
        workbench,
        specification.revision,
        selection.revision,
        command.output_artifact_ids,
    )
    model = _initialize_model(current, command, specification, selection, outputs)
    _validate_bindings(specification, selection, model, outputs)
    record = _save(session, workbench, model, principal)
    session.commit()
    response.headers["ETag"] = etag_for_revision(workbench.revision)
    return DefineResponse.model_validate(record)


@router.post("/adams/{adam_id}/define/validate", response_model=ValidationRunResponse)
def validate_define(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ValidationRunResponse:
    workbench = _workbench(session, adam_id, principal)
    record = _latest_define(session, workbench.id)
    if record is None:
        raise _problem(404, "adam_define_not_found", "ADaM Define metadata is not saved.")
    specification_record = _latest_specification(session, workbench.id)
    selection = _input_selection(session, workbench.id)
    model = AdamDefineModel.model_validate(record.payload)
    outputs = _outputs(
        session,
        workbench,
        specification_record.revision,
        selection.revision,
        model.output_artifact_ids,
    )
    _validate_bindings(specification_record, selection, model, outputs)
    specification = AdamSpecification.model_validate(specification_record.payload)
    sdtm_context = _selected_sdtm_context(session, registry, workbench, selection)
    issues = validate_define_metadata(specification, model, sdtm_context)
    required_datasets = {item.code for item in specification.datasets}
    if set(outputs) != required_datasets:
        issues.append(_issue("adam_define_output_coverage_mismatch", None, None))
    schema_fingerprints = {
        "2.0": define_schema_fingerprint("2.0"),
        "2.1": define_schema_fingerprint("2.1"),
    }
    for version in ("2.0", "2.1"):
        try:
            render_define_xml(model, version)
        except ProblemException:
            issues.append(_issue(f"adam_define_xml_{version.replace('.', '')}_invalid", None, None))
    manifest = {
        "adam_revision": workbench.revision,
        "define_revision": record.revision,
        "define_fingerprint": record.fingerprint,
        "specification_revision": specification_record.revision,
        "input_selection_revision": selection.revision,
        "sdtm_context_fingerprint": fingerprint(sdtm_context),
        "output_artifacts": [
            {"id": str(item.id), "sha256": item.sha256, "dataset": code}
            for code, item in sorted(outputs.items())
        ],
        "define_xml_generator_version": DEFINE_XML_GENERATOR_VERSION,
        "define_xml_schema_fingerprints": schema_fingerprints,
    }
    now = utc_now()
    run = ValidationRun(
        study_id=workbench.study_id,
        module_key="adam",
        owner_type="adam_define",
        owner_id=record.id,
        status="succeeded",
        validator_name=DEFINE_VALIDATOR_NAME,
        validator_version=DEFINE_VALIDATOR_VERSION,
        input_fingerprint=fingerprint(manifest),
        input_manifest=manifest,
        started_at=now,
        completed_at=now,
        error_count=len(issues),
        warning_count=0,
        info_count=0,
        issues=issues,
        report_artifact_ids=[],
        created_by=principal.subject,
    )
    session.add(run)
    session.commit()
    return ValidationRunResponse.model_validate(run)


@router.get("/adams/{adam_id}/define/render", operation_id="render_adam_define")
def render_define(
    adam_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    version: Literal["2.0", "2.1"] = "2.1",
) -> Response:
    """Render a validated revision without persisting a new artifact."""

    workbench = _workbench(session, adam_id, principal)
    record = _latest_define(session, workbench.id)
    if record is None:
        raise _problem(404, "adam_define_not_found", "ADaM Define metadata is not saved.")
    if _current_validation(session, record) is None:
        raise _problem(
            409,
            "successful_validation_required",
            "Validate the current Define revision against both pinned XSD versions first.",
        )
    data = render_define_xml(AdamDefineModel.model_validate(record.payload), version)
    return Response(
        content=data,
        media_type="application/xml",
        headers={"Content-Disposition": f'inline; filename="adam-define-{version}.xml"'},
    )


@router.post(
    "/adams/{adam_id}/define/reconcile",
    response_model=ReconciliationResponse,
    status_code=202,
)
def reconcile_define(
    adam_id: UUID,
    command: DefineReconcileRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReconciliationResponse:
    workbench = _workbench(session, adam_id, principal)
    define = session.scalar(
        select(AdamDefineRevision).where(
            AdamDefineRevision.aggregate_id == workbench.id,
            AdamDefineRevision.revision == command.define_revision,
        )
    )
    if define is None or define.fingerprint != command.expected_define_fingerprint:
        raise _problem(
            409,
            "stale_adam_define_reconciliation_input",
            "The exact Define revision or fingerprint does not match.",
        )
    inputs = [
        ReconciliationInput(
            entity_type="adam_define", entity_id=define.id, revision=define.revision
        )
    ]
    for artifact_id in define.output_artifact_ids:
        artifact = session.get(Artifact, UUID(artifact_id))
        if artifact is None:
            raise _problem(422, "adam_define_output_invalid", "A selected ADaM XPT is missing.")
        inputs.append(ReconciliationInput(artifact_id=artifact.id, checksum=artifact.sha256))
    request = ReconciliationCreate(
        study_id=workbench.study_id,
        reconciliation_type="adam_define_outputs",
        reconciliation_version="1.0.0",
        inputs=tuple(inputs),
        expected_input_fingerprint="0" * 64,
    )
    request.expected_input_fingerprint = fingerprint(
        request.model_dump(mode="json", exclude={"expected_input_fingerprint"})
    )
    return create_reconciliation(request, response, session, registry, principal, idempotency_key)


@router.post(
    "/adams/{adam_id}/define/artifacts",
    response_model=ArtifactBuildResponse,
    status_code=202,
)
def create_define_artifacts(
    adam_id: UUID,
    command: DefineArtifactRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ArtifactBuildResponse:
    workbench = _workbench(session, adam_id, principal)
    artifact_types = tuple(
        "adam_define_xml_20" if version == "2.0" else "adam_define_xml_21"
        for version in command.versions
    )
    return create_artifact_build(
        ArtifactBuildCreate(
            study_id=workbench.study_id,
            owner_type="adam_workbench",
            owner_id=workbench.id,
            artifact_types=artifact_types,
            expected_input_fingerprint=command.expected_input_fingerprint,
            options={},
        ),
        response,
        session,
        registry,
        principal,
        idempotency_key,
    )


def _issue(
    code: str,
    dataset: str | None,
    variable: str | None,
    *,
    field_path: str = "datasets",
    message: str = "ADaM Define metadata does not match its exact authored evidence.",
) -> dict[str, object]:
    return {
        "id": f"{code}:{dataset or '*'}:{variable or '*'}:{field_path}",
        "code": code,
        "severity": "error",
        "message": message,
        "suggestion": (
            "Correct the maintained metadata, reinitialize missing factual structures, "
            "or select matching exact inputs."
        ),
        "module": "adam",
        "entity_type": "adam_define",
        "entity_id": None,
        "field_path": field_path,
        "dataset": dataset,
        "variable": variable,
        "artifact_id": None,
    }
