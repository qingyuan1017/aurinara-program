"""Service-contract tests for Platform-owned clinical agents."""

import json
from uuid import uuid4

import httpx

from app.assistance.contracts import ProposalGenerationRequest
from app.assistance.platform_agents import PlatformAgentClient
from app.config import Settings


class Authorization:
    def service_token(self) -> str:
        return "service-token"


def test_catalog_and_invocation_use_service_token_and_exact_revision() -> None:
    agent_id = uuid4()
    operation_id = uuid4()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer service-token"
        agent = {
            "id": str(agent_id),
            "name": "Clinical agent",
            "description": None,
            "capabilities": ["clinical_proposal_v1"],
            "revision": 4,
        }
        if request.method == "GET":
            return httpx.Response(200, json=[agent])
        body = json.loads(request.content)
        assert body["agent_id"] == str(agent_id)
        assert body["agent_revision"] == 4
        assert body["operation_id"] == str(operation_id)
        return httpx.Response(
            200,
            json={
                "schema_version": "1.0.0",
                "agent": agent,
                "output": {"proposal": {}},
                "response_checksum": "a" * 64,
                "usage": {"input_tokens": 9},
                "runtime_session_id": f"aurinara-{operation_id}",
                "trace_id": "trace-1",
            },
        )

    settings = Settings(
        _env_file=None,
        app_env="test",
        platform_control_plane_url="https://platform.example.test",
    )
    client = PlatformAgentClient(
        settings,
        Authorization(),  # type: ignore[arg-type]
        httpx.MockTransport(handler),
    )
    assert client.list_agents()[0].revision == 4
    result = client.invoke(
        agent_id=agent_id,
        agent_revision=4,
        operation_id=operation_id,
        request=ProposalGenerationRequest(
            system_instruction="Return JSON.",
            user_instruction="Use exact evidence.",
            output_schema={"type": "object"},
        ),
        temperature=0.1,
        max_output_tokens=1024,
    )
    assert result.payload == {"proposal": {}}
    assert result.usage["platform_agent"]["agent_name"] == "Clinical agent"
    assert result.usage["platform_agent"]["agent_revision"] == 4
    assert result.usage["platform_agent"]["trace_id"] == "trace-1"
    assert [request.url.path for request in calls] == [
        "/v1/playground/service/agents",
        "/v1/playground/service/invocations",
    ]
