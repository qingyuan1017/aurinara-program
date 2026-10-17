"""Settings safety tests."""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.database import build_database_url, create_database_engine


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
        object_store_endpoint=None,
        object_store_access_key=None,
        object_store_secret_key=None,
        object_store_path_style=False,
        integration_allow_loopback_callbacks=False,
        integration_secret_encryption_key="production-key-from-secret-store",
        execution_network_disabled=True,
        pinned_asset_local_fallback=False,
        python_runner_image="example.dkr.ecr.us-east-1.amazonaws.com/python@sha256:"
        + "a" * 64,
        r_runner_image="example.dkr.ecr.us-east-1.amazonaws.com/r@sha256:" + "b" * 64,
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


def test_ecs_executor_rejects_an_invalid_fargate_size() -> None:
    with pytest.raises(ValidationError, match="valid Fargate size"):
        Settings(
            _env_file=None,
            app_env="test",
            executor_adapter="ecs",
            execution_workspace_root="/mnt/execution",
            ecs_cluster_arn="cluster",
            ecs_python_task_definition="python",
            ecs_r_task_definition="r",
            ecs_subnet_ids="subnet-a",
            ecs_security_group_ids="sg-a",
            execution_cpu_limit=1.5,
        )


def test_split_database_settings_build_a_tls_postgresql_url() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=None,
        database_host="database.internal",
        database_name="aurinara",
        database_user="application",
        database_password="secret",
        database_ssl_mode="require",
    )

    engine = create_database_engine(settings)
    migration_url = build_database_url(settings)

    assert engine.url.host == "database.internal"
    assert engine.url.database == "aurinara"
    assert engine.url.query["sslmode"] == "require"
    assert migration_url.host == "database.internal"
    assert migration_url.password == "secret"
