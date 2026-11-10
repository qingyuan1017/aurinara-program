"""TLF portfolio proposal stages and explicit human acceptance."""

import json
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.assistance.contracts import ProposalCreate, ProposalGenerationRequest
from app.assistance.models import AiGenerationRun, AuthoringProposal
from app.assistance.service import PreparedProposal, ProposalValidation
from app.common.canonical import fingerprint
from app.common.problems import ProblemException
from app.kernel.context import DocumentContextExporter
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry
from app.tlf.contracts import (
    TlfArs,
    TlfAssumptions,
    TlfBindings,
    TlfInputSelectionWrite,
    TlfOutputInventory,
    TlfProgramPlan,
    TlfShell,
)
from app.tlf.models import (
    TlfAuthoringRevision,
    TlfDependencySelection,
    TlfInputSelection,
    TlfWorkbench,
)
from app.tlf.service import TlfCapability, lower_analysis_ir

TLF_PROPOSAL_TYPES = (
    "tlf_output_inventory",
    "tlf_analysis_shells",
    "tlf_programming_plan",
)


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assumptions: tuple[str, ...] = ()
    unresolved_items: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = Field(min_length=1)
    model_limitations: tuple[str, ...] = Field(min_length=1)


class InventoryProposal(_Envelope):
    proposal: TlfOutputInventory


class TlfOutputAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_code: str = Field(pattern=r"^[A-Z][A-Z0-9-]{1,31}$")
    shell: TlfShell
    bindings: TlfBindings
    assumptions: TlfAssumptions
    ars: TlfArs

    @model_validator(mode="after")
    def matching_shell(self) -> "TlfOutputAnalysis":
        if self.shell.output_code != self.output_code:
            raise ValueError("analysis output_code must match shell output_code")
        return self


class AnalysisPortfolio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0.0"
    outputs: tuple[TlfOutputAnalysis, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_outputs(self) -> "AnalysisPortfolio":
        codes = [item.output_code for item in self.outputs]
        if len(codes) != len(set(codes)):
            raise ValueError("analysis output codes must be unique")
        return self


class AnalysisProposal(_Envelope):
    proposal: AnalysisPortfolio


class TlfOutputProgramming(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output_code: str = Field(pattern=r"^[A-Z][A-Z0-9-]{1,31}$")
    program_plan: TlfProgramPlan


class ProgrammingPortfolio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0.0"
    outputs: tuple[TlfOutputProgramming, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_outputs(self) -> "ProgrammingPortfolio":
        codes = [item.output_code for item in self.outputs]
        if len(codes) != len(set(codes)):
            raise ValueError("programming output codes must be unique")
        return self


class ProgrammingProposal(_Envelope):
    proposal: ProgrammingPortfolio


_OUTPUT_MODELS: dict[str, type[_Envelope]] = {
    "tlf_output_inventory": InventoryProposal,
    "tlf_analysis_shells": AnalysisProposal,
    "tlf_programming_plan": ProgrammingProposal,
}


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


class TlfProposalCapability:
    instruction_version = "tlf-portfolio-authoring-1.0.0"

    def __init__(self, capability: TlfCapability) -> None:
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
                "tlf_proposal_type_unsupported",
                "Unsupported TLF proposal type",
                f"Supported proposal types are: {', '.join(TLF_PROPOSAL_TYPES)}.",
            )
        workbench = session.get(TlfWorkbench, aggregate_id)
        if workbench is None:
            raise _problem(
                "tlf_not_found",
                "TLF workbench not found",
                "The workbench is missing.",
                404,
            )
        dependency = session.scalar(
            select(TlfDependencySelection).where(
                TlfDependencySelection.aggregate_id == aggregate_id
            )
        )
        input_record = session.scalar(
            select(TlfInputSelection).where(TlfInputSelection.aggregate_id == aggregate_id)
        )
        if dependency is None or dependency.state != "current":
            raise _problem(
                "tlf_dependencies_required",
                "TLF dependencies are required",
                "Select exact compatible dependencies first.",
                409,
            )
        if input_record is None or input_record.state != "current":
            raise _problem(
                "tlf_input_selection_required",
                "TLF input selection is required",
                "Select exact SAP and ADaM evidence first.",
                409,
            )
        selected = TlfInputSelectionWrite.model_validate(input_record.payload)
        document_exporter = cast(
            DocumentContextExporter,
            registry.require_handler("documents", ModuleCapability.CONTEXT_EXPORT),
        )
        documents: list[dict[str, object]] = []
        for document_selection in selected.documents:
            document = document_exporter.content_context(
                session,
                workbench.study_id,
                document_selection.content_id,
                expected_document_type=document_selection.document_type,
                expected_fingerprint=document_selection.fingerprint,
            )
            if document is None:
                raise _problem(
                    "tlf_source_document_stale",
                    "TLF source document is stale",
                    "A selected source document is no longer resolvable.",
                    409,
                )
            documents.append(document.model_dump(mode="json"))
        adam_context: list[dict[str, object]] = []
        for dataset_selection in selected.datasets:
            artifact = session.get(Artifact, dataset_selection.artifact_id)
            if artifact is None or artifact.sha256 != dataset_selection.checksum:
                raise _problem(
                    "tlf_adam_context_stale",
                    "TLF ADaM context is stale",
                    "A selected ADaM artifact no longer matches its checksum.",
                    409,
                )
            specification = artifact.manifest.get("source_specification")
            if not isinstance(specification, dict):
                specification = artifact.manifest.get("specification")
            adam_context.append(
                {
                    "binding": dataset_selection.model_dump(mode="json"),
                    "specification": specification,
                    "artifact_manifest": {
                        key: value
                        for key, value in artifact.manifest.items()
                        if key not in {"object_key", "platform_object_id"}
                    },
                }
            )
        inventory_record = self.capability.latest_content(session, aggregate_id, "inventory")
        context: dict[str, object] = {
            "aggregate": {
                "id": str(workbench.id),
                "revision": workbench.revision,
                "code": workbench.code,
                "name": workbench.name,
            },
            "dependency_selection": dependency.payload,
            "dependency_fingerprint": dependency.fingerprint,
            "input_selection": input_record.payload,
            "input_selection_revision": input_record.revision,
            "input_selection_fingerprint": input_record.fingerprint,
            "source_documents": documents,
            "adam_context": adam_context,
            "current_content": None,
        }
        if command.proposal_type == "tlf_output_inventory":
            context["current_content"] = inventory_record.payload if inventory_record else None
        else:
            if inventory_record is None or inventory_record.state != "current":
                raise _problem(
                    "tlf_inventory_required",
                    "Accepted TLF inventory is required",
                    "Accept the output inventory before generating later stages.",
                    409,
                )
            inventory = TlfOutputInventory.model_validate(inventory_record.payload)
            context["inventory"] = inventory.model_dump(mode="json")
            context["inventory_revision"] = inventory_record.revision
            current: dict[str, object] = {}
            for output in inventory.outputs:
                records = {
                    key: self.capability.latest_content(
                        session, aggregate_id, f"{key}:{output.output_code}"
                    )
                    for key in ("shell", "bindings", "assumptions", "ars", "program_plan")
                }
                current[output.output_code] = {
                    key: value.payload if value is not None else None
                    for key, value in records.items()
                }
            context["current_content"] = current
            if command.proposal_type == "tlf_programming_plan":
                missing = [
                    output.output_code
                    for output in inventory.outputs
                    if any(
                        (
                            record := self.capability.latest_content(
                                session, aggregate_id, f"{key}:{output.output_code}"
                            )
                        )
                        is None
                        or record.state != "current"
                        for key in ("shell", "bindings", "assumptions", "ars")
                    )
                ]
                if missing:
                    raise _problem(
                        "tlf_analysis_shells_required",
                        "Accepted TLF analysis shells are required",
                        f"Missing accepted analysis content for: {', '.join(missing)}.",
                        409,
                    )
        return PreparedProposal(
            study_id=workbench.study_id,
            aggregate_type="tlf_workbench",
            base_revision=workbench.revision,
            schema_version="1.0.0",
            instruction_version=self.instruction_version,
            context=context,
        )

    def generation_request(self, run: AiGenerationRun) -> ProposalGenerationRequest:
        model = _OUTPUT_MODELS[run.proposal_type]
        stage_instruction = {
            "tlf_output_inventory": (
                "Create a source-grounded output inventory. Label conventional proposals and "
                "retain explicit blockers; do not design detailed shells or programs."
            ),
            "tlf_analysis_shells": (
                "Preserve every accepted inventory identity exactly. Add analysis and display "
                "shells using only selected ADaM metadata. Do not write backend code."
            ),
            "tlf_programming_plan": (
                "Preserve accepted shells and propose typed ARS-linked ProgramPlans. Ordinary "
                "steps must be language-neutral; raw code is allowed only in typed custom "
                "functions."
            ),
        }[run.proposal_type]
        system = (
            "You are a TLF clinical artifact assistant. Produce typed proposals for explicit "
            "human review using only exact immutable evidence. Never invent analysis decisions, "
            "ADaM variables, or source support. Use unresolved items and blockers for gaps. "
            "Never claim approval, validation, or regulatory certification. Return only JSON."
        )
        user = (
            f"Stage: {stage_instruction} Every evidence reference must be a JSON pointer into "
            "the exact context.\nSchema:\n"
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
            raise ValueError("AI output does not match the registered TLF schema") from error
        for reference in envelope.evidence_references:
            _resolve_pointer(run.context, reference)
        normalized = envelope.model_dump(mode="json")
        proposed = cast(dict[str, Any], normalized["proposal"])
        return ProposalValidation(
            payload=normalized,
            diff=(
                {
                    "op": "add" if run.context.get("current_content") is None else "replace",
                    "path": "/",
                    "before": run.context.get("current_content"),
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
        workbench = session.get(TlfWorkbench, proposal.aggregate_id)
        if workbench is None:
            raise _problem(
                "tlf_not_found",
                "TLF workbench not found",
                "The workbench is missing.",
                404,
            )
        if workbench.revision != proposal.base_revision:
            raise _problem(
                "proposal_base_revision_stale",
                "Proposal base revision is stale",
                "The TLF portfolio changed after generation. Request a new proposal.",
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
                "Exact source or ADaM evidence changed. Request a new proposal.",
                409,
            )
        payload = cast(dict[str, Any], proposal.payload["proposal"])
        created: list[str] = []
        if proposal.proposal_type == "tlf_output_inventory":
            inventory = TlfOutputInventory.model_validate(payload)
            created.append(
                str(
                    self._save(
                        session,
                        workbench,
                        "inventory",
                        inventory,
                        reviewer,
                        proposal.id,
                        decision_id,
                    ).id
                )
            )
            self._misalign(session, workbench.id, exclude={"inventory"})
        elif proposal.proposal_type == "tlf_analysis_shells":
            analysis_portfolio = AnalysisPortfolio.model_validate(payload)
            created.extend(
                self._apply_analysis(
                    session,
                    workbench,
                    analysis_portfolio,
                    reviewer,
                    proposal.id,
                    decision_id,
                )
            )
        else:
            programming_portfolio = ProgrammingPortfolio.model_validate(payload)
            created.extend(
                self._apply_programming(
                    session,
                    workbench,
                    programming_portfolio,
                    reviewer,
                    proposal.id,
                    decision_id,
                )
            )
        workbench.revision += 1
        session.flush()
        return tuple(created)

    def _apply_analysis(
        self,
        session: Session,
        workbench: TlfWorkbench,
        portfolio: AnalysisPortfolio,
        reviewer: str,
        proposal_id: UUID,
        decision_id: UUID,
    ) -> list[str]:
        inventory_record = self.capability.latest_content(session, workbench.id, "inventory")
        input_record = session.scalar(
            select(TlfInputSelection).where(TlfInputSelection.aggregate_id == workbench.id)
        )
        if inventory_record is None or input_record is None:
            raise _problem(
                "tlf_analysis_prerequisites_missing",
                "TLF analysis prerequisites are missing",
                "Accepted inventory and exact inputs are required.",
                409,
            )
        inventory = TlfOutputInventory.model_validate(inventory_record.payload)
        expected = {item.output_code: item for item in inventory.outputs}
        if {item.output_code for item in portfolio.outputs} != set(expected):
            raise _problem(
                "tlf_inventory_identity_changed",
                "TLF inventory identity changed",
                "Analysis shells must cover exactly the accepted inventory outputs.",
            )
        selected = TlfInputSelectionWrite.model_validate(input_record.payload)
        selected_datasets = [item.model_dump(mode="json") for item in selected.datasets]
        created: list[str] = []
        for output in portfolio.outputs:
            inventory_output = expected[output.output_code]
            if (
                output.shell.title != inventory_output.title
                or output.shell.output_type != inventory_output.output_type
                or [item.model_dump(mode="json") for item in output.bindings.datasets]
                != selected_datasets
            ):
                raise _problem(
                    "tlf_analysis_evidence_mismatch",
                    "TLF analysis content does not match accepted evidence",
                    "Output identity and exact ADaM selections cannot change in stage two.",
                )
            self.capability.validate_bindings(session, workbench.study_id, output.bindings)
            leaves = {item.id for item in output.shell.rows if item.leaf}
            if {item.leaf_row_id for item in output.ars.analyses} != leaves:
                raise _problem(
                    "tlf_leaf_coverage_invalid",
                    "TLF shell leaf coverage is invalid",
                    "ARS must cover every shell leaf exactly once.",
                )
            for key, model in (
                ("shell", output.shell),
                ("bindings", output.bindings),
                ("assumptions", output.assumptions),
                ("ars", output.ars),
            ):
                record = self._save(
                    session,
                    workbench,
                    f"{key}:{output.output_code}",
                    model,
                    reviewer,
                    proposal_id,
                    decision_id,
                )
                created.append(str(record.id))
            plan = self.capability.latest_content(
                session, workbench.id, f"program_plan:{output.output_code}"
            )
            if plan is not None:
                plan.state = "misaligned"
        return created

    def _apply_programming(
        self,
        session: Session,
        workbench: TlfWorkbench,
        portfolio: ProgrammingPortfolio,
        reviewer: str,
        proposal_id: UUID,
        decision_id: UUID,
    ) -> list[str]:
        inventory_record = self.capability.latest_content(session, workbench.id, "inventory")
        if inventory_record is None:
            raise _problem(
                "tlf_inventory_required",
                "TLF inventory is required",
                "Accept inventory first.",
                409,
            )
        inventory = TlfOutputInventory.model_validate(inventory_record.payload)
        if {item.output_code for item in portfolio.outputs} != {
            item.output_code for item in inventory.outputs
        }:
            raise _problem(
                "tlf_inventory_identity_changed",
                "TLF inventory identity changed",
                "Programming must cover exactly the accepted inventory outputs.",
            )
        created: list[str] = []
        for output in portfolio.outputs:
            records = self.capability.current_authoring_without_plan(
                session, workbench.id, output.output_code
            )
            plan = output.program_plan
            if (
                plan.shell_revision != records["shell"].revision
                or plan.bindings_revision != records["bindings"].revision
                or plan.assumptions_revision != records["assumptions"].revision
                or plan.ars_revision != records["ars"].revision
            ):
                raise _problem(
                    "tlf_program_plan_misaligned",
                    "TLF ProgramPlan is misaligned",
                    "Every ProgramPlan must pin the current accepted analysis revisions.",
                    409,
                )
            lower_analysis_ir(
                TlfShell.model_validate(records["shell"].payload),
                TlfBindings.model_validate(records["bindings"].payload),
                TlfArs.model_validate(records["ars"].payload),
                plan,
            )
            record = self._save(
                session,
                workbench,
                f"program_plan:{output.output_code}",
                plan,
                reviewer,
                proposal_id,
                decision_id,
            )
            created.append(str(record.id))
        return created

    def _save(
        self,
        session: Session,
        workbench: TlfWorkbench,
        content_type: str,
        model: BaseModel,
        reviewer: str,
        proposal_id: UUID,
        decision_id: UUID,
    ) -> TlfAuthoringRevision:
        return self.capability.save_content(
            session,
            workbench,
            content_type,
            model,
            created_by=reviewer,
            originating_proposal_id=proposal_id,
            originating_decision_id=decision_id,
        )

    @staticmethod
    def _misalign(session: Session, aggregate_id: UUID, *, exclude: set[str]) -> None:
        records = session.scalars(
            select(TlfAuthoringRevision).where(TlfAuthoringRevision.aggregate_id == aggregate_id)
        )
        for record in records:
            if record.content_type not in exclude and record.state == "current":
                record.state = "misaligned"
