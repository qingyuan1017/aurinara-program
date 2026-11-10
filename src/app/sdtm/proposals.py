"""SDTM-owned AI proposal schemas, context assembly, validation, and acceptance."""

import json
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal
from app.assistance.contracts import ProposalCreate, ProposalGenerationRequest
from app.assistance.models import AiGenerationRun, AuthoringProposal
from app.assistance.service import PreparedProposal, ProposalValidation
from app.common.canonical import fingerprint
from app.common.problems import ProblemException
from app.config import get_settings
from app.integration.cdisc_library import (
    CdiscLibraryReaderFactory,
    create_cdisc_library_reader_factory,
)
from app.kernel.contracts import ModuleCapability
from app.kernel.registry import ModuleRegistry
from app.sdtm.authoring import (
    _domain,
    _head,
    _input,
    _mapping_pins,
    _mark_output_stale,
    _raw_context,
    _specification,
    _validate_cycle,
)
from app.sdtm.contracts import (
    SdtmCodeWorkareaCreate,
    SdtmCsdrgModel,
    SdtmDefineModel,
    SdtmDomainMappingWrite,
    SdtmSpecification,
    SdtmVariableMappingWrite,
)
from app.sdtm.csdrg import _latest_csdrg
from app.sdtm.csdrg import _require_current_inputs as _require_current_csdrg_inputs
from app.sdtm.csdrg import _save as _save_csdrg
from app.sdtm.define import (
    _latest_define,
    _output_artifacts,
    _validate_external_references,
)
from app.sdtm.define import _latest_specification as _latest_define_specification
from app.sdtm.define import _save as _save_define
from app.sdtm.models import (
    SdtmCodeRevision,
    SdtmCodeWorkarea,
    SdtmDependencySelection,
    SdtmDomainMappingRevision,
    SdtmDomainSourceSelection,
    SdtmOutputSelection,
    SdtmSpecificationRevision,
    SdtmVariableMappingRevision,
    SdtmWorkbench,
)
from app.sdtm.service import SdtmCapability
from app.sdtm.standard_specification import initialize_specification_from_standard
from app.sdtm.workbench_routes import (
    _live_standard_source,
    _save_specification,
    _selected_sdtmig_metadata,
)

SDTM_PROPOSAL_TYPES = (
    "sdtm_specification",
    "sdtm_domain_mapping",
    "sdtm_variable_mapping",
    "sdtm_program",
    "sdtm_define",
    "sdtm_csdrg",
)


class _ProposalEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assumptions: tuple[str, ...] = ()
    unresolved_items: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = Field(min_length=1)
    model_limitations: tuple[str, ...] = Field(min_length=1)


class DomainMappingProposal(_ProposalEnvelope):
    proposal: SdtmDomainMappingWrite


class SpecificationProposal(_ProposalEnvelope):
    proposal: SdtmSpecification


class VariableMappingProposal(_ProposalEnvelope):
    proposal: SdtmVariableMappingWrite


class ProgramProposal(_ProposalEnvelope):
    proposal: SdtmCodeWorkareaCreate


class DefineProposal(_ProposalEnvelope):
    proposal: SdtmDefineModel


class CsdrgProposal(_ProposalEnvelope):
    proposal: SdtmCsdrgModel


_OUTPUT_MODELS: dict[str, type[_ProposalEnvelope]] = {
    "sdtm_specification": SpecificationProposal,
    "sdtm_domain_mapping": DomainMappingProposal,
    "sdtm_variable_mapping": VariableMappingProposal,
    "sdtm_program": ProgramProposal,
    "sdtm_define": DefineProposal,
    "sdtm_csdrg": CsdrgProposal,
}


def _problem(code: str, title: str, detail: str, status_code: int = 422) -> ProblemException:
    return ProblemException(status_code=status_code, code=code, title=title, detail=detail)


def _resolve_json_pointer(document: object, pointer: str) -> object:
    if not pointer.startswith("/"):
        raise ValueError("evidence references must be JSON pointers")
    current = document
    for raw_token in pointer.removeprefix("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError(f"evidence reference does not resolve: {pointer}")
    return current


def _current_payload(
    session: Session, proposal_type: str, aggregate_id: UUID, domain: str
) -> dict[str, object] | None:
    if proposal_type == "sdtm_specification":
        specification_record = session.scalar(
            select(SdtmSpecificationRevision)
            .where(SdtmSpecificationRevision.aggregate_id == aggregate_id)
            .order_by(SdtmSpecificationRevision.revision.desc())
            .limit(1)
        )
        return specification_record.payload if specification_record is not None else None
    if proposal_type == "sdtm_define":
        define_record = _latest_define(session, aggregate_id)
        return define_record.payload if define_record is not None else None
    if proposal_type == "sdtm_csdrg":
        csdrg_record = _latest_csdrg(session, aggregate_id)
        return csdrg_record.payload if csdrg_record is not None else None
    model = (
        SdtmDomainMappingRevision
        if proposal_type == "sdtm_domain_mapping"
        else SdtmVariableMappingRevision
    )
    if proposal_type == "sdtm_program":
        return None
    current = _head(session, model, aggregate_id, domain)
    return cast(dict[str, object] | None, current.payload if current is not None else None)


class SdtmProposalCapability:
    """Own SDTM prompt semantics and apply accepted content through SDTM invariants."""

    instruction_version = "sdtm-authoring-1.0.0"

    def __init__(self, reader_factory: CdiscLibraryReaderFactory | None = None) -> None:
        self._reader_factory = reader_factory

    def _live_specification_standard(
        self,
        session: Session,
        registry: ModuleRegistry,
        workbench: SdtmWorkbench,
    ) -> dict[str, object]:
        reader_factory = self._reader_factory or create_cdisc_library_reader_factory(
            get_settings()
        )
        dependency_handler = cast(
            SdtmCapability,
            registry.require_handler("sdtm", ModuleCapability.DEPENDENCIES),
        )
        metadata = _selected_sdtmig_metadata(
            session,
            dependency_handler,
            workbench,
            reader_factory,
        )
        normalized_standard = initialize_specification_from_standard(metadata)
        return {
            **_live_standard_source(metadata),
            "product_code": metadata.product_code,
            "product_name": metadata.product_name,
            "version": metadata.version,
            "specification": normalized_standard.model_dump(mode="json"),
        }

    def prepare_proposal(
        self,
        session: Session,
        registry: ModuleRegistry,
        aggregate_id: UUID,
        command: ProposalCreate,
    ) -> PreparedProposal:
        if command.proposal_type not in _OUTPUT_MODELS:
            raise _problem(
                "sdtm_proposal_type_unsupported",
                "Unsupported SDTM proposal type",
                f"Supported proposal types are: {', '.join(SDTM_PROPOSAL_TYPES)}.",
            )
        workbench = session.get(SdtmWorkbench, aggregate_id)
        if workbench is None:
            raise _problem(
                "sdtm_not_found",
                "SDTM workbench not found",
                "The workbench is missing.",
                404,
            )
        domain = command.target.get("domain", "").upper()
        untargeted = {"sdtm_specification", "sdtm_define", "sdtm_csdrg"}
        if command.proposal_type not in untargeted and not domain:
            raise _problem(
                "sdtm_proposal_target_required",
                "SDTM proposal target is required",
                "Supply target.domain for this proposal.",
            )
        dependency_selection = session.scalar(
            select(SdtmDependencySelection).where(
                SdtmDependencySelection.aggregate_id == workbench.id
            )
        )
        if dependency_selection is None or dependency_selection.state != "current":
            raise _problem(
                "sdtm_dependency_selection_required",
                "Current dependency selection required",
                "Select exact SDTM dependencies before requesting an AI proposal.",
                409,
            )
        context: dict[str, object] = {
            "workbench": {
                "id": str(workbench.id),
                "revision": workbench.revision,
                "code": workbench.code,
            },
            "dependency_selection": {
                "revision": dependency_selection.revision,
                "fingerprint": dependency_selection.fingerprint,
                "payload": dependency_selection.payload,
            },
            "current_content": _current_payload(
                session, command.proposal_type, workbench.id, domain
            ),
            "guidance": command.guidance,
        }
        if command.proposal_type not in {"sdtm_define", "sdtm_csdrg"}:
            input_selection = _input(session, workbench)
            raw_context = _raw_context(session, registry, workbench, input_selection)
            # Metadata and exact checksums only; Raw subject rows are never included.
            context["input_selection_revision"] = input_selection.revision
            context["selected_raw_metadata"] = raw_context
        if command.proposal_type == "sdtm_specification":
            current = _current_payload(session, command.proposal_type, workbench.id, domain)
            context["current_content"] = current
            context["industry_standard"] = self._live_specification_standard(
                session, registry, workbench
            )
            context["specification_revision"] = (
                session.scalar(
                    select(SdtmSpecificationRevision.revision)
                    .where(SdtmSpecificationRevision.aggregate_id == workbench.id)
                    .order_by(SdtmSpecificationRevision.revision.desc())
                    .limit(1)
                )
                or 0
            )
        elif command.proposal_type == "sdtm_define":
            define_specification = _latest_define_specification(session, workbench.id)
            output_selection = session.scalar(
                select(SdtmOutputSelection).where(
                    SdtmOutputSelection.aggregate_id == workbench.id,
                    SdtmOutputSelection.state == "current",
                )
            )
            if output_selection is None:
                raise _problem(
                    "sdtm_output_selection_required",
                    "Current output selection required",
                    "Generate and select the exact SDTM output artifacts before requesting Define.",
                    409,
                )
            context["specification_revision"] = define_specification.revision
            context["specification"] = define_specification.payload
            context["output_selection"] = output_selection.payload
        elif command.proposal_type == "sdtm_csdrg":
            define = _latest_define(session, workbench.id)
            current_csdrg = _latest_csdrg(session, workbench.id)
            if define is None or current_csdrg is None:
                raise _problem(
                    "csdrg_initialization_required",
                    "Initialized cSDRG evidence required",
                    "Initialize factual cSDRG structures from the current Define and a successful "
                    "reconciliation before requesting AI narrative.",
                    409,
                )
            context["specification_revision"] = define.specification_revision
            context["define"] = define.payload
            context["current_content"] = current_csdrg.payload
        else:
            spec_record, parsed_specification = _specification(session, workbench)
            target_domain = _domain(parsed_specification, domain)
            context["target_domain"] = target_domain.model_dump(mode="json")
            context["specification_revision"] = spec_record.revision
        if command.proposal_type in {"sdtm_variable_mapping", "sdtm_program"}:
            domain_mapping = _head(
                session, SdtmDomainMappingRevision, workbench.id, domain
            )
            if domain_mapping is None or domain_mapping.state != "aligned":
                raise _problem(
                    "sdtm_domain_mapping_alignment_required",
                    "Aligned Domain Mapping required",
                    "Accept an aligned Domain Mapping proposal before requesting this proposal.",
                    409,
                )
            context["domain_mapping"] = domain_mapping.payload
        if command.proposal_type == "sdtm_program":
            variable_mapping = _head(
                session, SdtmVariableMappingRevision, workbench.id, domain
            )
            if variable_mapping is None or variable_mapping.state != "aligned":
                raise _problem(
                    "sdtm_variable_mapping_alignment_required",
                    "Aligned Variable Mapping required",
                    "Accept an aligned Variable Mapping proposal before requesting a program.",
                    409,
                )
            language = command.target.get("language", "").lower()
            if language not in {"python", "r", "sas"}:
                raise _problem(
                    "sdtm_program_language_required",
                    "Program language is required",
                    "Supply target.language as python, r, or sas.",
                )
            context["variable_mapping"] = variable_mapping.payload
            context["language"] = language

        return PreparedProposal(
            study_id=workbench.study_id,
            aggregate_type="sdtm_workbench",
            base_revision=workbench.revision,
            schema_version="1.0.0",
            instruction_version=self.instruction_version,
            context=context,
        )

    def generation_request(self, run: AiGenerationRun) -> ProposalGenerationRequest:
        """Assemble versioned prompt content only inside the assistance worker."""

        output_model = _OUTPUT_MODELS[run.proposal_type]
        domain = run.target.get("domain", "").upper()
        system_instruction = (
            "You are an SDTM authoring assistant. Produce a typed proposal for human review; "
            "never claim approval, certification, or unsupported certainty. Use only the exact "
            "context supplied. Preserve unresolved decisions explicitly. Do not invent source "
            "datasets, variables, controlled terms, or standards content. Return only JSON that "
            "matches the supplied schema."
        )
        user_instruction = (
            f"Create proposal type {run.proposal_type}"
            f"{' for domain ' + domain if domain else ''}. "
            "Every evidence_references entry must be a JSON pointer into the provided context. "
            "Return one JSON object matching this registered schema exactly:\n"
            f"{json.dumps(output_model.model_json_schema(), sort_keys=True, separators=(',', ':'))}"
            "\nExact context:\n"
            f"{json.dumps(run.context, sort_keys=True, separators=(',', ':'))}"
        )
        return ProposalGenerationRequest(
            system_instruction=system_instruction,
            user_instruction=user_instruction,
            output_schema=output_model.model_json_schema(),
        )

    def validate_proposal(
        self, session: Session, run: AiGenerationRun, payload: dict[str, Any]
    ) -> ProposalValidation:
        output_model = _OUTPUT_MODELS.get(run.proposal_type)
        if output_model is None:
            raise ValueError("unsupported SDTM proposal type")
        try:
            envelope = output_model.model_validate(payload)
        except ValidationError as error:
            raise ValueError("AI output does not match the registered SDTM schema") from error
        normalized = envelope.model_dump(mode="json")
        for reference in envelope.evidence_references:
            _resolve_json_pointer(run.context, reference)
        proposed = cast(dict[str, Any], normalized["proposal"])
        current = cast(dict[str, Any] | None, run.context.get("current_content"))
        diff = (
            {
                "op": "add" if current is None else "replace",
                "path": "/",
                "before": current,
                "after": proposed,
            },
        )
        return ProposalValidation(
            payload=normalized,
            diff=diff,
            assumptions=envelope.assumptions,
            unresolved_items=envelope.unresolved_items,
            evidence_references=envelope.evidence_references,
            model_limitations=envelope.model_limitations,
            validation_issues=(),
        )

    def apply_proposal(
        self,
        session: Session,
        registry: ModuleRegistry,
        proposal: AuthoringProposal,
        reviewer: str,
        decision_id: UUID,
    ) -> tuple[str, ...]:
        workbench = session.get(SdtmWorkbench, proposal.aggregate_id)
        if workbench is None:
            raise _problem(
                "sdtm_not_found",
                "SDTM workbench not found",
                "The workbench is missing.",
                404,
            )
        if workbench.revision != proposal.base_revision:
            raise _problem(
                "proposal_base_revision_stale",
                "Proposal base revision is stale",
                "The SDTM workbench changed after generation. Request a new proposal.",
                409,
            )
        if proposal.payload is None:
            raise _problem(
                "proposal_payload_missing",
                "Proposal payload is missing",
                "A proposal without validated content cannot be accepted.",
                409,
            )
        run = session.get(AiGenerationRun, proposal.generation_run_id)
        if run is None:
            raise RuntimeError("proposal generation run is missing")
        # Rebuild and fingerprint context at acceptance so immutable evidence cannot be applied
        # against silently changed dependencies.
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
                "The exact context changed after generation. Request a new proposal.",
                409,
            )
        domain = run.target.get("domain", "").upper()
        content = cast(dict[str, Any], proposal.payload["proposal"])
        if proposal.proposal_type == "sdtm_specification":
            live_standard = cast(dict[str, object], prepared.context["industry_standard"])
            specification_record = _save_specification(
                session,
                registry,
                workbench,
                SdtmSpecification.model_validate(content),
                Principal(subject=reviewer, scopes=frozenset()),
                standard_source={
                    key: live_standard[key]
                    for key in (
                        "source",
                        "standard_version_id",
                        "canonical_href",
                        "response_checksum",
                    )
                },
            )
            specification_record.originating_proposal_id = proposal.id
            specification_record.originating_decision_id = decision_id
            session.flush()
            return (str(specification_record.id),)
        if proposal.proposal_type == "sdtm_define":
            define_command = SdtmDefineModel.model_validate(content)
            define_specification = _latest_define_specification(session, workbench.id)
            if define_command.specification_revision != define_specification.revision:
                raise _problem(
                    "define_specification_misaligned",
                    "Define Specification revision is stale",
                    "Request a new Define proposal against the current Specification.",
                    409,
                )
            outputs = _output_artifacts(
                session,
                workbench,
                define_specification.revision,
                define_command.output_artifact_ids,
            )
            _validate_external_references(session, workbench, define_command, outputs)
            define_record = _save_define(
                session,
                workbench,
                define_command,
                Principal(subject=reviewer, scopes=frozenset()),
            )
            define_record.originating_proposal_id = proposal.id
            define_record.originating_decision_id = decision_id
            session.flush()
            return (str(define_record.id),)
        if proposal.proposal_type == "sdtm_csdrg":
            csdrg_command = SdtmCsdrgModel.model_validate(content)
            _require_current_csdrg_inputs(session, workbench, csdrg_command)
            csdrg_record = _save_csdrg(
                session,
                workbench,
                csdrg_command,
                Principal(subject=reviewer, scopes=frozenset()),
            )
            csdrg_record.originating_proposal_id = proposal.id
            csdrg_record.originating_decision_id = decision_id
            session.flush()
            return (str(csdrg_record.id),)
        if proposal.proposal_type == "sdtm_domain_mapping":
            return self._apply_domain_mapping(
                session,
                registry,
                workbench,
                domain,
                content,
                reviewer,
                proposal.id,
                decision_id,
            )
        if proposal.proposal_type == "sdtm_variable_mapping":
            return self._apply_variable_mapping(
                session,
                registry,
                workbench,
                domain,
                content,
                reviewer,
                proposal.id,
                decision_id,
            )
        return self._apply_program(
            session, workbench, content, reviewer, proposal.id, decision_id
        )

    @staticmethod
    def _apply_domain_mapping(
        session: Session,
        registry: ModuleRegistry,
        workbench: SdtmWorkbench,
        domain: str,
        content: dict[str, Any],
        reviewer: str,
        proposal_id: UUID,
        decision_id: UUID,
    ) -> tuple[str, ...]:
        command = SdtmDomainMappingWrite.model_validate(content)
        spec_record, specification = _specification(session, workbench)
        input_record = _input(session, workbench)
        _domain(specification, domain)
        if domain in command.upstream_domains:
            raise _problem(
                "sdtm_domain_mapping_self_reference",
                "Invalid upstream domain",
                "A domain cannot read itself.",
            )
        known_domains = {item.code for item in specification.domains}
        if not set(command.upstream_domains) <= known_domains:
            raise _problem(
                "sdtm_domain_mapping_upstream_unknown",
                "Unknown upstream domain",
                "Every upstream domain must be declared by the Specification.",
            )
        raw_context = _raw_context(session, registry, workbench, input_record)
        raw_codes = {
            str(item["code"])
            for item in cast(list[dict[str, object]], raw_context["datasets"])
        }
        selected_codes = {
            str(item["dataset_code"])
            for item in cast(list[dict[str, object]], input_record.payload["source_artifacts"])
        }
        if not set(command.raw_datasets) <= raw_codes & selected_codes:
            raise _problem(
                "sdtm_domain_mapping_raw_unknown",
                "Raw dataset is not selected",
                "Every Raw dataset must belong to the exact current Raw selection.",
            )
        _validate_cycle(session, workbench.id, domain, command.upstream_domains)
        prior = _head(session, SdtmDomainMappingRevision, workbench.id, domain)
        revision = (prior.revision + 1) if prior else 1
        payload = command.model_dump(mode="json")
        record = SdtmDomainMappingRevision(
            aggregate_id=workbench.id,
            study_id=workbench.study_id,
            domain_code=domain,
            revision=revision,
            specification_revision=spec_record.revision,
            input_selection_revision=input_record.revision,
            state="aligned",
            payload=payload,
            fingerprint=fingerprint(payload),
            created_by=reviewer,
            originating_proposal_id=proposal_id,
            originating_decision_id=decision_id,
        )
        session.add(record)
        variable = _head(session, SdtmVariableMappingRevision, workbench.id, domain)
        if variable is not None and variable.state == "aligned":
            variable.state = "misaligned"
            variable.alignment_reasons = ["domain_mapping_changed"]
        source = session.scalar(
            select(SdtmDomainSourceSelection).where(
                SdtmDomainSourceSelection.aggregate_id == workbench.id,
                SdtmDomainSourceSelection.domain_code == domain,
            )
        )
        if source is None:
            source = SdtmDomainSourceSelection(
                aggregate_id=workbench.id,
                study_id=workbench.study_id,
                domain_code=domain,
                revision=1,
                source_type="generated",
                source_revision=revision,
                fingerprint=record.fingerprint,
                updated_by=reviewer,
            )
            session.add(source)
        else:
            source.revision += 1
            source.source_type = "generated"
            source.source_revision = revision
            source.fingerprint = record.fingerprint
            source.updated_by = reviewer
        _mark_output_stale(session, workbench.id)
        workbench.revision += 1
        session.flush()
        return (str(record.id),)

    @staticmethod
    def _apply_variable_mapping(
        session: Session,
        registry: ModuleRegistry,
        workbench: SdtmWorkbench,
        domain: str,
        content: dict[str, Any],
        reviewer: str,
        proposal_id: UUID,
        decision_id: UUID,
    ) -> tuple[str, ...]:
        command = SdtmVariableMappingWrite.model_validate(content)
        spec_record, specification = _specification(session, workbench)
        target = _domain(specification, domain)
        mapping = _head(session, SdtmDomainMappingRevision, workbench.id, domain)
        if mapping is None or mapping.state != "aligned":
            raise _problem(
                "sdtm_domain_mapping_alignment_required",
                "Domain Mapping alignment required",
                "Accept a current Domain Mapping first.",
                409,
            )
        target_variables = {item.name for item in target.variables}
        contexts = {item.id for item in target.value_contexts}
        raw_allowed = set(cast(list[str], mapping.payload.get("raw_datasets", [])))
        sdtm_allowed = set(cast(list[str], mapping.payload.get("upstream_domains", [])))
        raw_context = _raw_context(session, registry, workbench, _input(session, workbench))
        raw_variables = {
            (str(dataset["code"]), str(variable["name"]))
            for dataset in cast(list[dict[str, object]], raw_context["datasets"])
            for variable in cast(list[dict[str, object]], dataset["variables"])
        }
        sdtm_variables = {
            (item.code, variable.name)
            for item in specification.domains
            for variable in item.variables
        }
        for cell in command.cells:
            if cell.target_variable not in target_variables or (
                cell.context_id is not None and cell.context_id not in contexts
            ):
                raise _problem(
                    "sdtm_variable_mapping_target_invalid",
                    "Variable Mapping target is invalid",
                    "Every target row and context column must be declared by the current "
                    "Specification.",
                )
            for source in cell.sources:
                allowed = raw_allowed if source.source_type == "raw" else sdtm_allowed
                known = raw_variables if source.source_type == "raw" else sdtm_variables
                if source.dataset not in allowed or (source.dataset, source.variable) not in known:
                    raise _problem(
                        "sdtm_variable_mapping_source_invalid",
                        "Variable Mapping source is invalid",
                        "Every source must resolve through the accepted Domain Mapping and exact "
                        "metadata.",
                    )
        prior = _head(session, SdtmVariableMappingRevision, workbench.id, domain)
        revision = (prior.revision + 1) if prior else 1
        payload = command.model_dump(mode="json")
        record = SdtmVariableMappingRevision(
            aggregate_id=workbench.id,
            study_id=workbench.study_id,
            domain_code=domain,
            revision=revision,
            specification_revision=spec_record.revision,
            domain_mapping_revision=mapping.revision,
            state="aligned",
            payload=payload,
            fingerprint=fingerprint(payload),
            created_by=reviewer,
            originating_proposal_id=proposal_id,
            originating_decision_id=decision_id,
        )
        session.add(record)
        _mark_output_stale(session, workbench.id)
        workbench.revision += 1
        session.flush()
        return (str(record.id),)

    @staticmethod
    def _apply_program(
        session: Session,
        workbench: SdtmWorkbench,
        content: dict[str, Any],
        reviewer: str,
        proposal_id: UUID,
        decision_id: UUID,
    ) -> tuple[str, ...]:
        command = SdtmCodeWorkareaCreate.model_validate(content)
        spec, dm, vm = _mapping_pins(session, workbench, command.domain)
        duplicate = session.scalar(
            select(SdtmCodeWorkarea.id).where(
                SdtmCodeWorkarea.aggregate_id == workbench.id,
                SdtmCodeWorkarea.name == command.name,
            )
        )
        if duplicate is not None:
            raise _problem(
                "sdtm_workarea_name_duplicate",
                "Code Workarea name already exists",
                "Request a revised proposal with a unique workarea name.",
                409,
            )
        record = SdtmCodeWorkarea(
            aggregate_id=workbench.id,
            study_id=workbench.study_id,
            name=command.name,
            domain_code=command.domain,
            language=command.language,
            revision=1,
            created_by=reviewer,
        )
        session.add(record)
        session.flush()
        revision = SdtmCodeRevision(
            workarea_id=record.id,
            aggregate_id=workbench.id,
            study_id=workbench.study_id,
            revision=1,
            specification_revision=spec.revision,
            domain_mapping_revision=dm.revision,
            variable_mapping_revision=vm.revision,
            source=command.source,
            fingerprint=fingerprint(
                {"source": command.source, "pins": [spec.revision, dm.revision, vm.revision]}
            ),
            created_by=reviewer,
            originating_proposal_id=proposal_id,
            originating_decision_id=decision_id,
        )
        session.add(revision)
        workbench.revision += 1
        session.flush()
        return (str(record.id), str(revision.id))


HANDLER = SdtmProposalCapability()
