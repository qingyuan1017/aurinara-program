"""JWT authentication boundary tests."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api.auth import JwksTokenVerifier
from app.common.problems import ProblemException
from app.config import Settings


class _StaticJwksClient:
    def __init__(self, public_key: object) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token: str) -> SimpleNamespace:
        return SimpleNamespace(key=self._public_key)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        jwt_issuer="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_example",
        jwt_audience="development-spa-client",
        jwt_jwks_url="https://issuer.example/.well-known/jwks.json",
    )


def _verifier_and_token(
    monkeypatch: pytest.MonkeyPatch,
    **extra_claims: object,
) -> tuple[JwksTokenVerifier, str]:
    settings = _settings()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks_client = _StaticJwksClient(private_key.public_key())
    monkeypatch.setattr(
        "app.api.auth.PyJWKClient",
        lambda *_args, **_kwargs: jwks_client,
    )
    now = datetime.now(UTC).replace(microsecond=0)
    claims: dict[str, object] = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": "cognito-user-id",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **extra_claims,
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test"})
    return JwksTokenVerifier(settings), token


def test_cognito_id_token_is_a_human_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier, token = _verifier_and_token(monkeypatch, token_use="id")

    principal = verifier.verify(token)

    assert principal.subject == "cognito-user-id"
    assert principal.kind == "human"
    assert principal.scopes == frozenset()


def test_explicit_service_principal_remains_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier, token = _verifier_and_token(
        monkeypatch,
        principal_kind="service",
        scope="studies:read",
    )

    principal = verifier.verify(token)

    assert principal.kind == "service"
    assert principal.scopes == frozenset({"studies:read"})


@pytest.mark.parametrize(
    "extra_claims",
    [
        {},
        {"token_use": "access"},
        {"token_use": "id", "principal_kind": "administrator"},
    ],
)
def test_untrusted_principal_classification_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    extra_claims: dict[str, object],
) -> None:
    verifier, token = _verifier_and_token(monkeypatch, **extra_claims)

    with pytest.raises(ProblemException) as raised:
        verifier.verify(token)

    assert raised.value.status_code == 401
    assert raised.value.detail == "The bearer token has no valid principal kind."
