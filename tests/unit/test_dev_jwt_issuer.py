"""Development issuer signs short-lived tokens compatible with the API contract."""

from datetime import UTC, datetime

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from support.dev_jwt_issuer import DevJwtIssuerSettings, create_app


@pytest.mark.anyio
async def test_issuer_publishes_jwks_and_signs_required_claims() -> None:
    settings = DevJwtIssuerSettings(
        enabled=True,
        issuer="https://local-issuer.example",
        audience="clinical-artifact-platform",
    )
    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)), base_url="http://issuer"
    ) as client:
        jwks = (await client.get("/.well-known/jwks.json")).json()
        response = await client.post(
            "/token",
            json={"subject": "developer-1", "scope": "*", "lifetime_seconds": 300},
        )

    assert response.status_code == 200
    token_response = response.json()
    token = token_response["access_token"]
    header = jwt.get_unverified_header(token)
    assert header["kid"] == jwks["keys"][0]["kid"]
    public_key = jwt.PyJWK.from_dict(jwks["keys"][0]).key
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=settings.issuer,
        audience=settings.audience,
        options={"require": ["exp", "iat", "iss", "aud", "sub"]},
    )
    assert claims["sub"] == "developer-1"
    assert claims["scope"] == "*"
    assert claims["exp"] - claims["iat"] == 300
    assert claims["exp"] > int(datetime.now(UTC).timestamp())


@pytest.mark.anyio
async def test_issuer_rejects_long_lived_tokens() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(DevJwtIssuerSettings(enabled=True))),
        base_url="http://issuer",
    ) as client:
        response = await client.post(
            "/token",
            json={"subject": "developer-1", "scope": "*", "lifetime_seconds": 3601},
        )

    assert response.status_code == 422


def test_issuer_requires_explicit_enablement() -> None:
    with pytest.raises(ValueError, match="DEV_JWT_ENABLED"):
        DevJwtIssuerSettings(enabled=False)
