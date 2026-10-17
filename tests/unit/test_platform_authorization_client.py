from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from app.api.auth import Principal
from app.common.problems import ProblemException
from app.config import Settings
from app.platform.authorization import PlatformAuthorizationClient


def _decision(allowed: bool = True) -> dict[str, object]:
    return {
        "allowed": allowed,
        "decision_id": str(uuid4()),
        "policy_version": 3,
        "expires_at": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        "reason_code": "permission_granted" if allowed else "permission_not_granted",
    }


def test_positive_decision_is_cached_within_revocation_window() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json=_decision())

    settings = Settings(
        app_env="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    client = PlatformAuthorizationClient(settings, httpx.MockTransport(handler))
    client._token = ("service-token", float("inf"))
    principal = Principal("subject", frozenset(), "https://issuer.test")
    study_id = uuid4()

    assert client.decide(principal, "artifact.study.read", study_id).allowed is True
    assert client.decide(principal, "artifact.study.read", study_id).allowed is True
    assert requests == 1


def test_uncached_outage_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    settings = Settings(
        app_env="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    client = PlatformAuthorizationClient(settings, httpx.MockTransport(handler))
    client._token = ("service-token", float("inf"))

    with pytest.raises(ProblemException) as caught:
        client.decide(
            Principal("subject", frozenset(), "https://issuer.test"),
            "artifact.study.read",
            uuid4(),
        )
    assert caught.value.status_code == 503


def test_membership_event_invalidation_evicts_study_decisions() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json=_decision())

    settings = Settings(
        _env_file=None,
        app_env="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    client = PlatformAuthorizationClient(settings, httpx.MockTransport(handler))
    client._token = ("service-token", float("inf"))
    principal = Principal("subject", frozenset(), "https://issuer.test")
    study_id = uuid4()

    client.decide(principal, "artifact.study.read", study_id)
    client.invalidate(study_id=study_id)
    client.decide(principal, "artifact.study.read", study_id)

    assert requests == 2


def test_batch_decision_uses_one_request_for_study_collection() -> None:
    study_ids = (uuid4(), uuid4())
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(
            200,
            json={"decisions": [_decision(True), _decision(False)]},
        )

    settings = Settings(
        _env_file=None,
        app_env="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    client = PlatformAuthorizationClient(settings, httpx.MockTransport(handler))
    client._token = ("service-token", float("inf"))

    decisions = client.decide_batch(
        Principal("subject", frozenset(), "https://issuer.test"),
        "artifact.study.read",
        study_ids,
    )

    assert [item.allowed for item in decisions] == [True, False]
    assert seen_paths == ["/v1/authorization/decisions:batch"]


def test_service_token_requests_cognito_scope_and_resource() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        command = dict(httpx.QueryParams(request.content.decode()))
        assert command["grant_type"] == "client_credentials"
        assert command["scope"] == "https://aurinara-platform.local/service"
        assert command["resource"] == "https://aurinara-platform.local"
        return httpx.Response(200, json={"access_token": "token", "expires_in": 300})

    settings = Settings(
        _env_file=None,
        app_env="test",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    client = PlatformAuthorizationClient(settings, httpx.MockTransport(handler))

    assert client.service_token() == "token"


def test_service_token_omits_nullable_oauth_audience_and_resource() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        command = dict(httpx.QueryParams(request.content.decode()))
        assert command["scope"] == "aurinara-platform/service"
        assert "audience" not in command
        assert "resource" not in command
        return httpx.Response(200, json={"access_token": "token", "expires_in": 300})

    settings = Settings(
        _env_file=None,
        app_env="test",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
        platform_service_audience=None,
        platform_service_resource=None,
        platform_service_scope="aurinara-platform/service",
    )
    client = PlatformAuthorizationClient(settings, httpx.MockTransport(handler))

    assert client.service_token() == "token"
