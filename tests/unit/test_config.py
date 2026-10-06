"""Settings safety tests."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_development_defaults_are_loadable() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.execution_network_disabled is True


def test_unsafe_production_defaults_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unsafe production configuration"):
        Settings(_env_file=None, app_env="production")


def test_safe_production_configuration_is_accepted() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        object_store_access_key="not-default",
        object_store_secret_key="not-default-secret",
        integration_allow_loopback_callbacks=False,
        integration_secret_encryption_key="production-key-from-secret-store",
        execution_network_disabled=True,
        pinned_asset_local_fallback=False,
    )

    assert settings.app_env == "production"
    assert settings.pinned_asset_local_fallback is False


def test_pinned_asset_local_fallback_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="pinned asset local fallback"):
        Settings(
            _env_file=None,
            app_env="production",
            object_store_access_key="not-default",
            object_store_secret_key="not-default-secret",
            integration_allow_loopback_callbacks=False,
            integration_secret_encryption_key="production-key-from-secret-store",
            execution_network_disabled=True,
            pinned_asset_local_fallback=True,
        )
