"""External JWT validation and authenticated-principal contracts."""

from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

import jwt
from fastapi import Header, Request
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from app.common.problems import ProblemException
from app.config import Settings


@dataclass(frozen=True, slots=True)
class Principal:
    """Verified external identity used by application services."""

    subject: str
    scopes: frozenset[str]


class TokenVerifier(Protocol):
    """Boundary for externally issued bearer-token verification."""

    def verify(self, token: str) -> Principal:
        """Verify a token and return its trusted identity claims."""


class JwksTokenVerifier:
    """Validate asymmetric JWTs against an external JWKS endpoint."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = PyJWKClient(settings.jwt_jwks_url, cache_keys=True)

    def verify(self, token: str) -> Principal:
        """Validate signature, issuer, audience, expiry, and subject."""

        try:
            signing_key = self._client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=self._settings.jwt_algorithms.split(","),
                audience=self._settings.jwt_audience,
                issuer=self._settings.jwt_issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except PyJWTError as error:
            raise _unauthorized("The bearer token is invalid or expired.") from error
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise _unauthorized("The bearer token has no valid subject.")
        raw_scope = claims.get("scope", "")
        if not isinstance(raw_scope, str):
            raise _unauthorized("The bearer token scope claim is invalid.")
        return Principal(subject=subject, scopes=frozenset(raw_scope.split()))


def _unauthorized(detail: str) -> ProblemException:
    return ProblemException(
        status_code=401,
        code="invalid_token",
        title="Authentication failed",
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    """Authenticate a bearer token through the configured verifier."""

    if authorization is None or not authorization.startswith("Bearer "):
        raise _unauthorized("A bearer token is required.")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise _unauthorized("A bearer token is required.")
    verifier = cast(TokenVerifier, request.app.state.token_verifier)
    return verifier.verify(token)


def require_study_access(session: object, study_id: UUID, principal: Principal) -> None:
    """Reserved compatibility shim; services own concrete membership checks."""

    del session, study_id, principal
