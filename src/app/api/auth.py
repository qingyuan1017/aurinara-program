"""External JWT validation and authenticated-principal contracts."""

from dataclasses import dataclass
from typing import Literal, Protocol, cast

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
    issuer: str = ""
    kind: Literal["human", "service"] = "human"


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
        kind = claims.get("principal_kind", claims.get("actor_type"))
        if kind is None and claims.get("token_use") == "id":
            # Cognito ID tokens are issued only for authenticated users. The
            # signature-verified token_use claim is therefore the trusted
            # human classification for browser sessions; Cognito does not add
            # the platform's provider-neutral principal_kind claim by default.
            kind = "human"
        if kind not in {"human", "service"}:
            raise _unauthorized("The bearer token has no valid principal kind.")
        return Principal(
            subject=subject,
            scopes=frozenset(raw_scope.split()),
            issuer=str(claims["iss"]),
            kind=kind,
        )


def require_human_principal(principal: Principal) -> None:
    """Reject service identities at human review-decision boundaries."""

    if principal.kind != "human":
        raise ProblemException(
            status_code=403,
            code="human_reviewer_required",
            title="A human reviewer is required",
            detail="Service identities cannot accept, reject, or request revision of AI proposals.",
        )


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
