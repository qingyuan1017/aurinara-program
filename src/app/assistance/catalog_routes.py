"""Authenticated proxy for the Platform-owned clinical agent catalog."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_platform_agent_client
from app.assistance.platform_agents import (
    PlatformAgent,
    PlatformAgentClient,
    PlatformAgentClientError,
    as_problem,
)

router = APIRouter(prefix="/assistance", tags=["ai-proposals"])


@router.get("/agents", response_model=list[PlatformAgent])
def list_agents(
    principal: Annotated[Principal, Depends(get_principal)],
    client: Annotated[PlatformAgentClient, Depends(get_platform_agent_client)],
) -> list[PlatformAgent]:
    del principal
    try:
        return list(client.list_agents())
    except PlatformAgentClientError as error:
        raise as_problem(error) from error
