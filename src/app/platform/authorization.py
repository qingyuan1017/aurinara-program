"""Fail-closed client for shared control-plane authorization decisions."""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from uuid import UUID

import httpx

from app.api.auth import Principal
from app.common.metrics import emit_metric
from app.common.problems import ProblemException
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    decision_id: UUID
    policy_version: int
    expires_at: datetime
    reason_code: str


class PlatformAuthorizationClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.mode = settings.platform_authorization_mode
        self._base_url = (settings.platform_control_plane_url or "").rstrip("/")
        self._token_url = settings.platform_service_token_url
        self._client_id = settings.platform_service_client_id
        self._client_secret = settings.platform_service_client_secret
        self._audience = settings.platform_service_audience
        self._scope = settings.platform_service_scope
        self._resource = settings.platform_service_resource
        self._max_cache_seconds = settings.platform_authorization_cache_seconds
        self._client = httpx.Client(
            transport=transport,
            timeout=settings.platform_authorization_timeout_seconds,
        )
        self._lock = threading.Lock()
        self._token: tuple[str, float] | None = None
        self._cache: dict[tuple[object, ...], tuple[Decision, float]] = {}

    def decide(self, principal: Principal, action: str, study_id: UUID) -> Decision:
        issuer = principal.issuer or get_settings().jwt_issuer
        key = (issuer, principal.subject, action, study_id)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and cached[1] > now:
            return cached[0]
        try:
            response = self._client.post(
                f"{self._base_url}/v1/authorization/decisions",
                headers={"Authorization": f"Bearer {self.service_token()}"},
                json={
                    "principal": {"issuer": issuer, "subject": principal.subject},
                    "action": action,
                    "resource": {
                        "product": "aurinara",
                        "type": "study",
                        "id": str(study_id),
                        "study_id": str(study_id),
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
            decision = Decision(
                allowed=bool(payload["allowed"]),
                decision_id=UUID(payload["decision_id"]),
                policy_version=int(payload["policy_version"]),
                expires_at=datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")),
                reason_code=str(payload["reason_code"]),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            cached = self._cache.get(key)
            if cached is not None and cached[1] > time.monotonic():
                return cached[0]
            emit_metric(
                "PlatformAuthorizationFailures",
                1,
                environment=get_settings().app_env,
            )
            raise ProblemException(
                status_code=503,
                code="authorization_unavailable",
                title="Authorization unavailable",
                detail="The authorization service is temporarily unavailable.",
            ) from error
        if decision.allowed and self._max_cache_seconds:
            ttl = min(
                self._max_cache_seconds,
                max(0.0, decision.expires_at.timestamp() - time.time()),
            )
            self._cache[key] = (decision, time.monotonic() + ttl)
        return decision

    def decide_batch(
        self, principal: Principal, action: str, study_ids: tuple[UUID, ...]
    ) -> tuple[Decision, ...]:
        """Resolve a study collection with one control-plane request."""

        if not study_ids:
            return ()
        issuer = principal.issuer or get_settings().jwt_issuer
        now = time.monotonic()
        resolved: dict[UUID, Decision] = {}
        missing: list[UUID] = []
        for study_id in study_ids:
            cached = self._cache.get((issuer, principal.subject, action, study_id))
            if cached is not None and cached[1] > now:
                resolved[study_id] = cached[0]
            else:
                missing.append(study_id)
        if missing:
            try:
                response = self._client.post(
                    f"{self._base_url}/v1/authorization/decisions:batch",
                    headers={"Authorization": f"Bearer {self.service_token()}"},
                    json={
                        "decisions": [
                            {
                                "principal": {"issuer": issuer, "subject": principal.subject},
                                "action": action,
                                "resource": {
                                    "product": "aurinara",
                                    "type": "study",
                                    "id": str(study_id),
                                    "study_id": str(study_id),
                                },
                            }
                            for study_id in missing
                        ]
                    },
                )
                response.raise_for_status()
                payloads = response.json()["decisions"]
                if len(payloads) != len(missing):
                    raise ValueError("authorization batch response length mismatch")
                for study_id, payload in zip(missing, payloads, strict=True):
                    decision = Decision(
                        allowed=bool(payload["allowed"]),
                        decision_id=UUID(payload["decision_id"]),
                        policy_version=int(payload["policy_version"]),
                        expires_at=datetime.fromisoformat(
                            payload["expires_at"].replace("Z", "+00:00")
                        ),
                        reason_code=str(payload["reason_code"]),
                    )
                    resolved[study_id] = decision
                    if decision.allowed and self._max_cache_seconds:
                        ttl = min(
                            self._max_cache_seconds,
                            max(0.0, decision.expires_at.timestamp() - time.time()),
                        )
                        self._cache[(issuer, principal.subject, action, study_id)] = (
                            decision,
                            time.monotonic() + ttl,
                        )
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                emit_metric(
                    "PlatformAuthorizationFailures",
                    1,
                    environment=get_settings().app_env,
                )
                raise ProblemException(
                    status_code=503,
                    code="authorization_unavailable",
                    title="Authorization unavailable",
                    detail="The authorization service is temporarily unavailable.",
                ) from error
        return tuple(resolved[study_id] for study_id in study_ids)

    def service_token(self) -> str:
        """Return a cached client-credentials token for control-plane calls."""
        now = time.monotonic()
        if self._token is not None and self._token[1] > now:
            return self._token[0]
        if not self._token_url or not self._client_id or self._client_secret is None:
            raise ProblemException(
                status_code=503,
                code="authorization_unavailable",
                title="Authorization unavailable",
                detail="Service authentication is not configured.",
            )
        try:
            token_command = {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret.get_secret_value(),
            }
            if self._audience:
                token_command["audience"] = self._audience
            if self._scope:
                token_command["scope"] = self._scope
            if self._resource:
                token_command["resource"] = self._resource
            response = self._client.post(self._token_url, data=token_command)
            response.raise_for_status()
            payload = response.json()
            token = str(payload["access_token"])
            expires_in = max(30, int(payload.get("expires_in", 300)))
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise ProblemException(
                status_code=503,
                code="authorization_unavailable",
                title="Authorization unavailable",
                detail="Service authentication is temporarily unavailable.",
            ) from error
        with self._lock:
            self._token = (token, time.monotonic() + expires_in - 15)
        return token

    def invalidate(self, *, study_id: UUID | None = None) -> None:
        """Invalidate cached allows after a membership, policy, or user event."""

        with self._lock:
            if study_id is None:
                self._cache.clear()
            else:
                self._cache = {
                    key: value for key, value in self._cache.items() if key[3] != study_id
                }


@lru_cache(maxsize=1)
def get_platform_authorization() -> PlatformAuthorizationClient:
    return PlatformAuthorizationClient(get_settings())
