"""Ephemeral asymmetric JWT issuer for local development only."""

from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DevJwtIssuerSettings(BaseSettings):
    """Explicit opt-in settings that prevent accidental non-development use."""

    model_config = SettingsConfigDict(
        env_prefix="DEV_JWT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = False
    issuer: str = "https://local-issuer.example"
    audience: str = "clinical-artifact-platform"

    @model_validator(mode="after")
    def require_explicit_enablement(self) -> "DevJwtIssuerSettings":
        if not self.enabled:
            raise ValueError("the development JWT issuer requires DEV_JWT_ENABLED=true")
        if not self.issuer or not self.audience:
            raise ValueError("development JWT issuer and audience must be non-empty")
        return self


class TokenRequest(BaseModel):
    """Manually requested local identity and short-lived authorization scope."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(default="local-developer", min_length=1, max_length=255)
    scope: str = Field(default="*", min_length=1, max_length=1000)
    lifetime_seconds: int = Field(default=3600, ge=60, le=3600)

    @field_validator("subject", "scope")
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("must not contain surrounding whitespace")
        return value


class TokenResponse(BaseModel):
    """OAuth-shaped response containing one ephemeral development token."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    scope: str


def _base64url_integer(value: int) -> str:
    size = max(1, (value.bit_length() + 7) // 8)
    return urlsafe_b64encode(value.to_bytes(size, "big")).rstrip(b"=").decode("ascii")


class EphemeralSigningKey:
    """One in-memory RSA key whose tokens expire when the service restarts."""

    def __init__(self) -> None:
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_numbers = self._private_key.public_key().public_numbers()
        modulus = _base64url_integer(public_numbers.n)
        exponent = _base64url_integer(public_numbers.e)
        digest = sha256(f"{modulus}.{exponent}".encode("ascii")).digest()
        self.kid = urlsafe_b64encode(digest[:18]).rstrip(b"=").decode("ascii")
        self.jwk: dict[str, str] = {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": self.kid,
            "n": modulus,
            "e": exponent,
        }

    def issue(self, command: TokenRequest, settings: DevJwtIssuerSettings) -> str:
        """Sign one bounded-lifetime token with the configured identity contract."""

        issued_at = datetime.now(UTC).replace(microsecond=0)
        expires_at = issued_at + timedelta(seconds=command.lifetime_seconds)
        return jwt.encode(
            {
                "iss": settings.issuer,
                "aud": settings.audience,
                "sub": command.subject,
                "iat": int(issued_at.timestamp()),
                "exp": int(expires_at.timestamp()),
                "scope": command.scope,
            },
            self._private_key,
            algorithm="RS256",
            headers={"kid": self.kid, "typ": "JWT"},
        )


def create_app(settings: DevJwtIssuerSettings) -> FastAPI:
    """Create a local issuer with an ephemeral key and no production fallback."""

    signing_key = EphemeralSigningKey()
    application = FastAPI(
        title="Aurinara Development JWT Issuer",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "kid": signing_key.kid}

    @application.get("/.well-known/jwks.json")
    def jwks() -> dict[str, list[dict[str, str]]]:
        return {"keys": [signing_key.jwk]}

    @application.post("/token", response_model=TokenResponse)
    def issue_token(command: TokenRequest) -> TokenResponse:
        return TokenResponse(
            access_token=signing_key.issue(command, settings),
            expires_in=command.lifetime_seconds,
            scope=command.scope,
        )

    return application


def create_environment_app() -> FastAPI:
    """Uvicorn factory that requires explicit development issuer enablement."""

    return create_app(DevJwtIssuerSettings())
