"""Typed service-to-service client for Platform-owned agent selection and invocation."""

from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.assistance.contracts import ProposalGenerationRequest, ProviderResult
from app.common.problems import ProblemException
from app.config import Settings
from app.platform.authorization import PlatformAuthorizationClient


class PlatformAgent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str | None
    capabilities: list[str]
    revision: int = Field(ge=1)


class PlatformInvocationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    agent: PlatformAgent
    output: dict[str, Any]
    response_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    usage: dict[str, Any]
    runtime_session_id: str
    trace_id: str | None = None


class PlatformAgentClientError(RuntimeError):
    def __init__(self, code: str, detail: str, *, status_code: int = 502) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class PlatformAgentClient:
    """Use the existing Cognito service identity; never expose runtime coordinates."""

    def __init__(
        self,
        settings: Settings,
        authorization: PlatformAuthorizationClient | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = (settings.platform_control_plane_url or "").rstrip("/")
        self._authorization = authorization or PlatformAuthorizationClient(settings)
        self._client = httpx.Client(
            transport=transport,
            timeout=settings.assistance_timeout_seconds,
            follow_redirects=False,
        )

    def list_agents(self) -> tuple[PlatformAgent, ...]:
        response = self._request("GET", "/v1/playground/service/agents")
        try:
            return tuple(TypeAdapter(list[PlatformAgent]).validate_json(response.content))
        except ValueError as error:
            raise PlatformAgentClientError(
                "platform_agent_response_invalid",
                "Platform returned an invalid agent catalog.",
            ) from error

    def get_agent(self, agent_id: UUID) -> PlatformAgent:
        response = self._request("GET", f"/v1/playground/service/agents/{agent_id}")
        try:
            return PlatformAgent.model_validate_json(response.content)
        except ValueError as error:
            raise PlatformAgentClientError(
                "platform_agent_response_invalid",
                "Platform returned invalid agent metadata.",
            ) from error

    def invoke(
        self,
        *,
        agent_id: UUID,
        agent_revision: int,
        operation_id: UUID,
        request: ProposalGenerationRequest,
        temperature: float,
        max_output_tokens: int,
    ) -> ProviderResult:
        response = self._request(
            "POST",
            "/v1/playground/service/invocations",
            json={
                "schema_version": "1.0.0",
                "agent_id": str(agent_id),
                "agent_revision": agent_revision,
                "operation_id": str(operation_id),
                "request": request.model_dump(mode="json"),
                "generation_parameters": {
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                },
            },
        )
        try:
            envelope = PlatformInvocationResponse.model_validate_json(response.content)
        except ValueError as error:
            raise PlatformAgentClientError(
                "platform_agent_response_invalid",
                "Platform returned an invalid proposal response.",
            ) from error
        if envelope.agent.id != agent_id or envelope.agent.revision != agent_revision:
            raise PlatformAgentClientError(
                "platform_agent_selection_mismatch",
                "Platform returned a different agent selection than requested.",
            )
        usage = {
            "provider": envelope.usage,
            "platform_agent": {
                "contract_version": envelope.schema_version,
                "agent_id": str(envelope.agent.id),
                "agent_name": envelope.agent.name,
                "agent_revision": envelope.agent.revision,
                "runtime_session_id": envelope.runtime_session_id,
            },
        }
        if envelope.trace_id:
            usage["platform_agent"]["trace_id"] = envelope.trace_id
        return ProviderResult(
            payload=envelope.output,
            response_checksum=envelope.response_checksum,
            usage=usage,
        )

    def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        if not self._base_url:
            raise PlatformAgentClientError(
                "assistance_not_configured",
                "The Platform control-plane URL is not configured.",
                status_code=503,
            )
        try:
            response = self._client.request(
                method,
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._authorization.service_token()}"},
                json=json,
            )
            response.raise_for_status()
            return response
        except ProblemException as error:
            raise PlatformAgentClientError(
                "platform_service_authentication_unavailable",
                "Platform service authentication is unavailable.",
                status_code=503,
            ) from error
        except httpx.HTTPStatusError as error:
            code = "platform_agent_request_failed"
            status_code = error.response.status_code
            if status_code in {401, 403}:
                code = "platform_service_authentication_unavailable"
                status_code = 503
            elif status_code == 404:
                code = "platform_agent_not_found"
            elif status_code == 409:
                code = "platform_agent_revision_stale"
            raise PlatformAgentClientError(
                code,
                "Platform rejected the agent request.",
                status_code=status_code,
            ) from error
        except httpx.HTTPError as error:
            raise PlatformAgentClientError(
                "platform_agent_unavailable",
                "Platform agent service is unavailable.",
                status_code=503,
            ) from error


def as_problem(error: PlatformAgentClientError) -> ProblemException:
    return ProblemException(
        status_code=error.status_code,
        code=error.code,
        title="Platform agent request failed",
        detail=error.detail,
    )
