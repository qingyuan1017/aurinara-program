"""Platform-agent boundary and human-review safety tests."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.api.auth import Principal, require_human_principal
from app.assistance.contracts import ProposalCreate, ProposalGenerationRequest, ProposalStatus
from app.assistance.platform_agents import PlatformAgentClientError
from app.assistance.provider import PlatformAgentProvider, ProviderError, create_proposal_provider
from app.assistance.service import AssistanceService, PreparedProposal
from app.common.canonical import fingerprint
from app.common.problems import ProblemException
from app.config import Settings


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        assistance_enabled=enabled,
        platform_control_plane_url="https://platform.example.test",
        platform_service_token_url="https://identity.example.test/oauth2/token",
        platform_service_client_id="aurinara-api",
        platform_service_client_secret="secret",
    )


def _request() -> ProposalGenerationRequest:
    return ProposalGenerationRequest(
        system_instruction="Return typed JSON.",
        user_instruction="Use exact context.",
        output_schema={"type": "object"},
    )


def test_platform_provider_invokes_exact_selected_agent_revision() -> None:
    agent_id = uuid4()
    operation_id = uuid4()

    class Client:
        def invoke(self, **kwargs: Any):
            from app.assistance.contracts import ProviderResult

            assert kwargs["agent_id"] == agent_id
            assert kwargs["agent_revision"] == 7
            assert kwargs["operation_id"] == operation_id
            return ProviderResult(
                payload={"proposal": {}}, response_checksum="a" * 64, usage={}
            )

    provider = PlatformAgentProvider(_settings(), Client())  # type: ignore[arg-type]
    result = provider.generate(
        _request(),
        operation_id=operation_id,
        agent_id=agent_id,
        agent_revision=7,
    )
    assert result.payload == {"proposal": {}}
    assert isinstance(create_proposal_provider(_settings()), PlatformAgentProvider)


def test_platform_provider_maps_safe_service_failure() -> None:
    class Client:
        def invoke(self, **_kwargs: Any):
            raise PlatformAgentClientError(
                "platform_agent_revision_stale", "Platform rejected the agent request."
            )

    with pytest.raises(ProviderError) as raised:
        PlatformAgentProvider(_settings(), Client()).generate(  # type: ignore[arg-type]
            _request(), operation_id=uuid4(), agent_id=uuid4(), agent_revision=1
        )
    assert raised.value.code == "platform_agent_revision_stale"


def test_service_identity_cannot_make_human_review_decision() -> None:
    principal = Principal(subject="worker", scopes=frozenset(), kind="service")
    with pytest.raises(ProblemException) as raised:
        require_human_principal(principal)
    assert raised.value.status_code == 403
    assert raised.value.code == "human_reviewer_required"


def test_human_identity_can_reach_review_service() -> None:
    require_human_principal(Principal(subject="reviewer", scopes=frozenset()))


def test_disabled_assistance_is_rejected_before_catalog_or_context() -> None:
    class Handler:
        def prepare_proposal(self, *_args: Any, **_kwargs: Any) -> PreparedProposal:
            raise AssertionError("context must not be assembled when assistance is disabled")

    class Client:
        def get_agent(self, _agent_id: UUID):
            raise AssertionError("catalog must not be queried when assistance is disabled")

    with pytest.raises(ProblemException) as raised:
        AssistanceService().create(
            None,  # type: ignore[arg-type]
            module_key="sdtm",
            aggregate_id=uuid4(),
            command=ProposalCreate(
                agent_id=uuid4(), proposal_type="sdtm_specification"
            ),
            created_by="reviewer",
            handler=Handler(),  # type: ignore[arg-type]
            settings=_settings(enabled=False),
            registry=None,  # type: ignore[arg-type]
            agent_client=Client(),  # type: ignore[arg-type]
        )
    assert raised.value.code == "assistance_not_configured"


def _run(bound_context: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        aggregate_id=uuid4(),
        proposal_type="sdtm_specification",
        target={},
        guidance=None,
        base_revision=7,
        context_fingerprint=fingerprint(bound_context),
        generation_parameters={"platform_agent_id": str(uuid4())},
        status=ProposalStatus.QUEUED,
        started_at=None,
        completed_at=None,
        failure=None,
    )


def test_generation_preflight_retries_one_transient_context_mismatch() -> None:
    bound = {"selection": {"revision": 3, "checksum": "bound"}}
    prepared = [
        PreparedProposal(
            study_id=uuid4(), aggregate_type="sdtm_workbench", base_revision=7,
            schema_version="1.0.0", instruction_version="test-1",
            context={"selection": {"revision": 3, "checksum": "transient"}},
        ),
        PreparedProposal(
            study_id=uuid4(), aggregate_type="sdtm_workbench", base_revision=7,
            schema_version="1.0.0", instruction_version="test-1", context=bound,
        ),
    ]

    class Handler:
        calls = 0

        def prepare_proposal(self, *_args: Any, **_kwargs: Any) -> PreparedProposal:
            item = prepared[self.calls]
            self.calls += 1
            return item

        def generation_request(self, _run: Any) -> ProposalGenerationRequest:
            return _request()

    handler = Handler()
    run = _run(bound)
    proposal = SimpleNamespace(status=ProposalStatus.QUEUED)
    result = AssistanceService().begin_generation(
        None, run=run, proposal=proposal, handler=handler, registry=None  # type: ignore[arg-type]
    )
    assert result == _request()
    assert handler.calls == 2


def test_generation_preflight_fails_after_two_context_mismatches() -> None:
    stale = PreparedProposal(
        study_id=uuid4(), aggregate_type="sdtm_workbench", base_revision=8,
        schema_version="1.0.0", instruction_version="test-1", context={"revision": 8},
    )

    class Handler:
        calls = 0

        def prepare_proposal(self, *_args: Any, **_kwargs: Any) -> PreparedProposal:
            self.calls += 1
            return stale

        def generation_request(self, _run: Any) -> ProposalGenerationRequest:
            raise AssertionError("a stale context must never reach the provider")

    handler = Handler()
    run = _run({"revision": 7})
    proposal = SimpleNamespace(
        status=ProposalStatus.QUEUED, completed_at=None, failure=None
    )
    result = AssistanceService().begin_generation(
        None, run=run, proposal=proposal, handler=handler, registry=None  # type: ignore[arg-type]
    )
    assert result is None
    assert handler.calls == 2
    assert proposal.failure["code"] == "proposal_context_stale"
