"""ADaM-owned AI proposal schemas, frozen context, validation, and acceptance."""

import json
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adam.adrg import _current_inputs as _validate_adrg_inputs
from app.adam.adrg import _latest as _latest_adrg
from app.adam.adrg import _save as _save_adrg
from app.adam.contracts import (
    AdamAdrgModel,
    AdamDefineModel,
    AdamDerivationPlan,
    AdamSpecification,
)
from app.adam.define import _input_selection as _define_input
from app.adam.define import _latest_define
from app.adam.define import _latest_specification as _define_specification
from app.adam.define import _outputs as _define_outputs
from app.adam.define import _save as _save_define
from app.adam.define import _validate_bindings as _validate_define_bindings
from app.adam.models import (
    AdamDependencySelection,
    AdamDerivationPlanRevision,
    AdamWorkbench,
)
from app.adam.service import (
    AdamCapability,
    context_from_record,
    lower_plan,
    validate_origins,
    validate_sdtm_sources,
)
from app.adam.workbench_routes import (
    _require_dataset,
    _save_specification,
    _sdtm_context,
    _selection_command,
)
from app.api.auth import Principal
from app.artifacts.service import ArtifactService
from app.assistance.contracts import ProposalCreate, ProposalGenerationRequest
from app.assistance.models import AiGenerationRun, AuthoringProposal
from app.assistance.service import PreparedProposal, ProposalValidation
from app.common.canonical import fingerprint
from app.common.problems import ProblemException
from app.kernel.context import DocumentContextExporter
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry

ADAM_PROPOSAL_TYPES = (
    "adam_specification",
    "adam_derivation_plan",
    "adam_define",
    "adam_adrg",
)


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assumptions: tuple[str, ...] = ()
    unresolved_items: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = Field(min_length=1)
    model_limitations: tuple[str, ...] = Field(min_length=1)


class SpecificationProposal(_Envelope):
    proposal: AdamSpecification


class PlanProposal(_Envelope):
    proposal: AdamDerivationPlan


class DefineProposal(_Envelope):
    proposal: AdamDefineModel


class AdrgProposal(_Envelope):
    proposal: AdamAdrgModel


_OUTPUT_MODELS: dict[str, type[_Envelope]] = {
    "adam_specification": SpecificationProposal,
    "adam_derivation_plan": PlanProposal,
    "adam_define": DefineProposal,
    "adam_adrg": AdrgProposal,
}

artifacts = ArtifactService()


def _problem(code: str, title: str, detail: str, status_code: int = 422) -> ProblemException:
    return ProblemException(status_code=status_code, code=code, title=title, detail=detail)


def _resolve_pointer(document: object, pointer: str) -> object:
    if not pointer.startswith("/"):
        raise ValueError("evidence references must be JSON pointers")
    current = document
    for raw in pointer.removeprefix("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError(f"evidence reference does not resolve: {pointer}")
    return current


def _document_context(
    session: Session,
    registry: ModuleRegistry,
    study_id: UUID,
    target: dict[str, str],
) -> list[dict[str, object]]:
    exporter = cast(
        DocumentContextExporter,
        registry.require_handler("documents", ModuleCapability.CONTEXT_EXPORT),
    )
    result: list[dict[str, object]] = []
    for key, expected_type in (
        ("sap_content_id", "statistical_analysis_plan"),
        ("protocol_content_id", "protocol"),
    ):
        raw = target.get(key)
        if not raw:
            continue
        try:
            content_id = UUID(raw)
        except ValueError as error:
            raise _problem(
                "adam_document_context_invalid",
                "ADaM document context is invalid",
                f"{key} must be a UUID.",
            ) from error
        context = exporter.content_context(
            session,
            study_id,
            content_id,
            expected_document_type=expected_type,
        )
        if context is None:
            raise _problem(
                "adam_document_context_invalid",
                "ADaM document context is invalid",
                f"{key} must identify exact same-study {expected_type} content.",
            )
        result.append(context.model_dump(mode="json"))
    return result


class AdamProposalCapability:
    """Keep ADaM clinical semantics inside the owning module."""

    instruction_version = "adam-authoring-1.0.0"

    def __init__(self, capability: AdamCapability) -> None:
        self.capability = capability

    def prepare_proposal(
        self,
        session: Session,
        registry: ModuleRegistry,
        aggregate_id: UUID,
        command: ProposalCreate,
    ) -> PreparedProposal:
        if command.proposal_type not in _OUTPUT_MODELS:
            raise _problem(
                "adam_proposal_type_unsupported",
                "Unsupported ADaM proposal type",
                f"Supported proposal types are: {', '.join(ADAM_PROPOSAL_TYPES)}.",
            )
        workbench = session.get(AdamWorkbench, aggregate_id)
        if workbench is None:
            raise _problem(
                "adam_not_found",
                "ADaM workbench not found",
                "The workbench is missing.",
                404,
            )
        selection = self.capability.current_input(session, aggregate_id)
        if selection.state != "current":
            raise _problem(
                "adam_input_selection_stale",
                "ADaM input selection is stale",
                "Select exact current SDTM inputs before requesting a proposal.",
                409,
            )
        dependency = session.scalar(
            select(AdamDependencySelection).where(
                AdamDependencySelection.aggregate_id == aggregate_id
            )
        )
        if dependency is None or dependency.state != "current":
            raise _problem(
                "adam_dependencies_required",
                "ADaM dependencies are required",
                "Select exact compatible dependencies before requesting a proposal.",
                409,
            )
        sdtm_context = _sdtm_context(
            session,
            registry,
            _selection_command(selection),
            workbench.study_id,
            workbench.id,
        )
        specification = self.capability.latest_specification(session, aggregate_id)
        context: dict[str, object] = {
            "aggregate": {
                "id": str(workbench.id),
                "revision": workbench.revision,
                "code": workbench.code,
                "name": workbench.name,
            },
            "dependency_selection": dependency.payload,
            "dependency_fingerprint": dependency.fingerprint,
            "input_selection": selection.payload,
            "input_selection_revision": selection.revision,
            "sdtm_context": sdtm_context,
            "source_documents": _document_context(
                session, registry, workbench.study_id, command.target
            ),
        }
        proposal_type = command.proposal_type
        if proposal_type == "adam_specification":
            context["current_content"] = specification.payload if specification else None
        else:
            if specification is None:
                raise _problem(
                    "adam_specification_required",
                    "ADaM Specification is required",
                    "Accept an ADaM Specification proposal first.",
                    409,
                )
            context["specification"] = specification.payload
            context["specification_revision"] = specification.revision
        if proposal_type == "adam_derivation_plan":
            dataset = command.target.get("dataset", "").upper()
            if not dataset:
                raise _problem(
                    "adam_proposal_target_required",
                    "ADaM dataset target is required",
                    "Set target.dataset for a Derivation Plan proposal.",
                )
            _require_dataset(self.capability, session, aggregate_id, dataset)
            current = self.capability.latest_plan(session, aggregate_id, dataset)
            context["target_dataset"] = dataset
            context["current_content"] = current.payload if current else None
            context["sibling_plan_heads"] = [
                {
                    "dataset": item.dataset_code,
                    "revision": item.revision,
                    "state": item.state,
                    "fingerprint": item.fingerprint,
                    "plan": item.payload,
                }
                for item in self.capability.list_plan_heads(session, aggregate_id)
                if item.dataset_code != dataset
            ]
        elif proposal_type == "adam_define":
            current_define = _latest_define(session, aggregate_id)
            context["current_content"] = current_define.payload if current_define else None
            context["plan_heads"] = [
                {
                    "dataset": item.dataset_code,
                    "revision": item.revision,
                    "state": item.state,
                    "fingerprint": item.fingerprint,
                }
                for item in self.capability.list_plan_heads(session, aggregate_id)
            ]
        elif proposal_type == "adam_adrg":
            define = _latest_define(session, aggregate_id)
            if define is None:
                raise _problem(
                    "adam_define_required",
                    "ADaM Define is required",
                    "Initialize and accept current Define content before ADRG generation.",
                    409,
                )
            current_adrg = _latest_adrg(session, aggregate_id)
            context["define"] = define.payload
            context["define_revision"] = define.revision
            context["current_content"] = current_adrg.payload if current_adrg else None
        return PreparedProposal(
            study_id=workbench.study_id,
            aggregate_type="adam_workbench",
            base_revision=workbench.revision,
            schema_version="1.0.0",
            instruction_version=self.instruction_version,
            context=context,
        )

    def generation_request(self, run: AiGenerationRun) -> ProposalGenerationRequest:
        model = _OUTPUT_MODELS[run.proposal_type]
        target = run.target.get("dataset", "").upper()
        system = (
            "You are an ADaM authoring assistant. Produce a typed proposal for explicit human "
            "review. Use only the exact immutable context. Do not invent datasets, variables, "
            "origins, methods, terminology, trace targets, analysis decisions, or executable "
            "semantics. Preserve uncertainty as unresolved items. Never claim approval, "
            "regulatory certification, or unsupported certainty. Return only schema-valid JSON."
        )
        user = (
            f"Create {run.proposal_type}{' for dataset ' + target if target else ''}. "
            "Every evidence_references value must be a JSON pointer into the exact context. "
            "Raw backend-specific code is forbidden except typed custom-function bodies.\n"
            "Schema:\n"
            f"{json.dumps(model.model_json_schema(), sort_keys=True, separators=(',', ':'))}\n"
            f"Exact context:\n{json.dumps(run.context, sort_keys=True, separators=(',', ':'))}"
        )
        return ProposalGenerationRequest(
            system_instruction=system,
            user_instruction=user,
            output_schema=model.model_json_schema(),
        )

    def validate_proposal(
        self, session: Session, run: AiGenerationRun, payload: dict[str, Any]
    ) -> ProposalValidation:
        del session
        try:
            envelope = _OUTPUT_MODELS[run.proposal_type].model_validate(payload)
        except (KeyError, ValidationError) as error:
            raise ValueError("AI output does not match the registered ADaM schema") from error
        for reference in envelope.evidence_references:
            _resolve_pointer(run.context, reference)
        normalized = envelope.model_dump(mode="json")
        proposed = cast(dict[str, Any], normalized["proposal"])
        current = cast(dict[str, Any] | None, run.context.get("current_content"))
        return ProposalValidation(
            payload=normalized,
            diff=(
                {
                    "op": "add" if current is None else "replace",
                    "path": "/",
                    "before": current,
                    "after": proposed,
                },
            ),
            assumptions=envelope.assumptions,
            unresolved_items=envelope.unresolved_items,
            evidence_references=envelope.evidence_references,
            model_limitations=envelope.model_limitations,
        )

    def apply_proposal(
        self,
        session: Session,
        registry: ModuleRegistry,
        proposal: AuthoringProposal,
        reviewer: str,
        decision_id: UUID,
    ) -> tuple[str, ...]:
        workbench = session.get(AdamWorkbench, proposal.aggregate_id)
        if workbench is None:
            raise _problem(
                "adam_not_found",
                "ADaM workbench not found",
                "The workbench is missing.",
                404,
            )
        if workbench.revision != proposal.base_revision:
            raise _problem(
                "proposal_base_revision_stale",
                "Proposal base revision is stale",
                "The ADaM workbench changed after generation. Request a new proposal.",
                409,
            )
        run = session.get(AiGenerationRun, proposal.generation_run_id)
        if run is None or proposal.payload is None:
            raise _problem(
                "proposal_payload_missing",
                "Proposal payload is missing",
                "A validated proposal is required for acceptance.",
                409,
            )
        prepared = self.prepare_proposal(
            session,
            registry,
            proposal.aggregate_id,
            ProposalCreate(
                agent_id=UUID(str(run.generation_parameters["platform_agent_id"])),
                proposal_type=proposal.proposal_type,
                target=run.target,
                guidance=run.guidance,
            ),
        )
        if fingerprint(prepared.context) != proposal.context_fingerprint:
            raise _problem(
                "proposal_context_stale",
                "Proposal context is stale",
                "The exact evidence changed after generation. Request a new proposal.",
                409,
            )
        content = cast(dict[str, Any], proposal.payload["proposal"])
        principal = Principal(subject=reviewer, scopes=frozenset())
        record: Any
        if proposal.proposal_type == "adam_specification":
            record = _save_specification(
                session,
                registry,
                workbench,
                AdamSpecification.model_validate(content),
                principal,
            )
        elif proposal.proposal_type == "adam_derivation_plan":
            record = self._save_plan(
                session,
                registry,
                workbench,
                AdamDerivationPlan.model_validate(content),
                run.target.get("dataset", "").upper(),
                reviewer,
            )
        elif proposal.proposal_type == "adam_define":
            define_command = AdamDefineModel.model_validate(content)
            specification = _define_specification(session, workbench.id)
            selection = _define_input(session, workbench.id)
            outputs = _define_outputs(
                session,
                workbench,
                specification.revision,
                selection.revision,
                define_command.output_artifact_ids,
            )
            _validate_define_bindings(specification, selection, define_command, outputs)
            record = _save_define(session, workbench, define_command, principal)
        else:
            adrg_command = AdamAdrgModel.model_validate(content)
            _validate_adrg_inputs(session, workbench, adrg_command)
            record = _save_adrg(session, workbench, adrg_command, principal)
        record.originating_proposal_id = proposal.id
        record.originating_decision_id = decision_id
        session.flush()
        return (str(record.id),)

    def _save_plan(
        self,
        session: Session,
        registry: ModuleRegistry,
        workbench: AdamWorkbench,
        command: AdamDerivationPlan,
        dataset: str,
        reviewer: str,
    ) -> AdamDerivationPlanRevision:
        specification = _require_dataset(self.capability, session, workbench.id, dataset)
        if command.dataset != dataset:
            raise _problem(
                "adam_plan_dataset_mismatch",
                "ADaM plan dataset mismatch",
                "The proposed plan dataset must equal the proposal target.",
            )
        selection = self.capability.current_input(session, workbench.id)
        if (
            selection.state != "current"
            or command.specification_revision != specification.revision
            or command.input_selection_revision != selection.revision
        ):
            raise _problem(
                "adam_plan_misaligned",
                "ADaM plan is misaligned",
                "The proposal does not pin the current Specification and input selection.",
                409,
            )
        sdtm_context = _sdtm_context(
            session,
            registry,
            _selection_command(selection),
            workbench.study_id,
            workbench.id,
        )
        validate_sdtm_sources(command, sdtm_context)
        specification_contract = context_from_record(specification)
        validate_origins(specification_contract, sdtm_context)
        lower_plan(specification_contract, command)
        self.capability.check_cross_plan_cycle(session, workbench.id, command)
        pins = self.capability.resolve_upstream_plan_pins(
            session, workbench.id, command, specification
        )
        current = self.capability.latest_plan(session, workbench.id, dataset)
        record = AdamDerivationPlanRevision(
            aggregate_id=workbench.id,
            study_id=workbench.study_id,
            dataset_code=dataset,
            revision=1 if current is None else current.revision + 1,
            schema_version=command.schema_version,
            specification_revision=command.specification_revision,
            input_selection_revision=command.input_selection_revision,
            state="aligned",
            upstream_plan_pins=pins,
            alignment_reasons=[],
            payload=command.model_dump(mode="json"),
            fingerprint=fingerprint(command.model_dump(mode="json")),
            created_by=reviewer,
        )
        session.add(record)
        self.capability.mark_sibling_plan_change(
            session, workbench.id, dataset, "upstream_plan_changed"
        )
        workbench.revision += 1
        artifacts.mark_owner_stale(session, owner_type="adam_workbench", owner_id=workbench.id)
        return record
