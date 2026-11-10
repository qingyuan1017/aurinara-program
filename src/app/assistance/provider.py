"""Provider boundary for Platform-owned, product-scoped agents."""

from typing import Protocol
from uuid import UUID

from app.assistance.contracts import ProposalGenerationRequest, ProviderResult
from app.assistance.platform_agents import PlatformAgentClient, PlatformAgentClientError
from app.config import Settings


class ProviderError(RuntimeError):
    """Typed safe provider failure without response-body leakage."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ProposalProvider(Protocol):
    def generate(
        self,
        request: ProposalGenerationRequest,
        *,
        operation_id: UUID,
        agent_id: UUID,
        agent_revision: int,
    ) -> ProviderResult: ...


class PlatformAgentProvider:
    """Invoke the exact agent revision selected from the Platform catalog."""

    def __init__(
        self, settings: Settings, client: PlatformAgentClient | None = None
    ) -> None:
        self._settings = settings
        self._client = client or PlatformAgentClient(settings)

    def generate(
        self,
        request: ProposalGenerationRequest,
        *,
        operation_id: UUID,
        agent_id: UUID,
        agent_revision: int,
    ) -> ProviderResult:
        if (
            not self._settings.assistance_enabled
            or self._settings.assistance_provider != "platform_agent"
        ):
            raise ProviderError(
                "assistance_not_configured",
                "Platform agent proposal generation is not configured.",
            )
        try:
            return self._client.invoke(
                agent_id=agent_id,
                agent_revision=agent_revision,
                operation_id=operation_id,
                request=request,
                temperature=self._settings.assistance_temperature,
                max_output_tokens=self._settings.assistance_max_output_tokens,
            )
        except PlatformAgentClientError as error:
            raise ProviderError(error.code, error.detail) from error


def create_proposal_provider(settings: Settings) -> ProposalProvider:
    """Create the only supported AI transport; no direct runtime fallback exists."""

    return PlatformAgentProvider(settings)
