"""Test-only completion of provider output through the real proposal lifecycle."""

from typing import Any, cast
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.assistance.contracts import ProviderResult
from app.assistance.models import AiGenerationRun, AuthoringProposal
from app.assistance.platform_agents import PlatformAgent
from app.assistance.service import AssistanceService, ProposalCapability
from app.common.time import utc_now
from app.execution.jobs import Job
from app.kernel.contracts import ModuleCapability

SYNTHETIC_AGENT_ID = uuid4()


class SyntheticPlatformAgentClient:
    def get_agent(self, agent_id):
        assert agent_id == SYNTHETIC_AGENT_ID
        return PlatformAgent(
            id=SYNTHETIC_AGENT_ID,
            name="Synthetic integration agent",
            description=None,
            capabilities=["clinical_proposal_v1"],
            revision=1,
        )


async def accept_typed_proposal(
    client: AsyncClient,
    *,
    application: Any,
    module_key: str,
    collection: str,
    aggregate_id: str,
    etag: str,
    proposal_type: str,
    proposal_payload: dict[str, object],
    target: dict[str, str] | None = None,
) -> Any:
    """Inject deterministic provider output, then accept it through the public API."""

    nonce = str(uuid4())
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": f"create-{nonce}",
    }
    created = await client.post(
        f"/api/v1/{collection}/{aggregate_id}/proposals",
        headers=headers,
        json={
            "agent_id": str(SYNTHETIC_AGENT_ID),
            "proposal_type": proposal_type,
            "target": target or {},
        },
    )
    assert created.status_code == 202, created.text
    proposal_id = created.json()["id"]
    factory = application.state.session_factory
    registry = application.state.module_registry
    with factory.begin() as session:
        proposal = session.get(AuthoringProposal, proposal_id)
        assert proposal is not None
        run = session.get(AiGenerationRun, proposal.generation_run_id)
        assert run is not None
        handler = cast(
            ProposalCapability,
            registry.require_handler(module_key, ModuleCapability.PROPOSALS),
        )
        AssistanceService().complete_generation(
            session,
            run=run,
            proposal=proposal,
            result=ProviderResult(
                payload={
                    "proposal": proposal_payload,
                    "assumptions": [],
                    "unresolved_items": [],
                    "evidence_references": ["/aggregate"],
                    "model_limitations": ["Deterministic synthetic integration fixture."],
                },
                response_checksum="a" * 64,
                usage={"fixture": True},
            ),
            handler=handler,
        )
        job = session.scalar(select(Job).where(Job.operation_id == run.id))
        assert job is not None
        job.status = "succeeded"
        job.completed_at = utc_now()
    accepted = await client.post(
        f"/api/v1/{collection}/{aggregate_id}/proposals/{proposal_id}:accept",
        headers={
            "Authorization": "Bearer test-token",
            "If-Match": etag,
            "Idempotency-Key": f"accept-{nonce}",
        },
        json={"rationale": "Reviewed deterministic integration proposal evidence."},
    )
    assert accepted.status_code == 200, accepted.text
    aggregate = await client.get(
        f"/api/v1/{collection}/{aggregate_id}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert aggregate.status_code == 200, aggregate.text
    accepted.headers["ETag"] = aggregate.headers["etag"]
    return accepted
