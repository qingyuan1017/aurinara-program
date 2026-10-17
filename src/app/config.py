"""Application settings and environment safety checks."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Aurinara Clinical Artifact Platform"
    app_version: str = "0.1.0"
    app_log_level: str = "INFO"
    app_api_prefix: str = "/api/v1"
    app_cors_allow_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175"

    database_url: str | None = "postgresql+psycopg://clinical:clinical@localhost:55432/clinical"
    database_host: str | None = None
    database_port: int = 5432
    database_name: str | None = None
    database_user: str | None = None
    database_password: SecretStr | None = None
    database_ssl_mode: Literal["disable", "prefer", "require", "verify-ca", "verify-full"] = (
        "prefer"
    )
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_recycle_seconds: int = 1800
    database_connect_timeout_seconds: int = 10

    object_store_endpoint: str | None = "http://localhost:9000"
    object_store_bucket: str = "clinical-artifacts"
    object_store_access_key: SecretStr | None = SecretStr("minioadmin")
    object_store_secret_key: SecretStr | None = SecretStr("minioadmin")
    object_store_region: str = "us-east-1"
    object_store_path_style: bool = True

    pinned_asset_local_fallback: bool = True

    jwt_issuer: str = "https://local-issuer.example"
    jwt_audience: str = "clinical-artifact-platform"
    jwt_jwks_url: str = "http://localhost:8081/.well-known/jwks.json"
    jwt_algorithms: str = "RS256"

    platform_control_plane_url: str | None = None
    platform_authorization_mode: Literal["disabled", "shadow", "enforced"] = "disabled"
    platform_service_token_url: str | None = None
    platform_service_client_id: str | None = None
    platform_service_client_secret: SecretStr | None = None
    platform_service_audience: str | None = "aurinara-platform"
    platform_service_scope: str = "https://aurinara-platform.local/service"
    platform_service_resource: str | None = "https://aurinara-platform.local"
    platform_authorization_timeout_seconds: float = 2.0
    platform_authorization_cache_seconds: int = 30
    platform_event_queue_url: str | None = None
    platform_event_region: str = "us-east-1"
    platform_event_endpoint_url: str | None = None

    source_file_max_bytes: int = 1_073_741_824
    source_file_allowed_media_types: str = (
        "application/pdf,application/json,application/vnd.ms-excel,application/x-sas-xport,"
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "text/csv,text/plain,application/octet-stream"
    )
    raw_bulk_upload_max_files: int = 50
    raw_bulk_import_max_entries: int = 500
    raw_bulk_import_max_total_bytes: int = 2_147_483_648

    job_lease_seconds: int = 60
    job_lease_heartbeat_seconds: int = 15
    job_max_attempts: int = 3

    integration_delivery_enabled: bool = True
    integration_max_attempts: int = 5
    integration_request_timeout_seconds: int = 10
    integration_response_limit_bytes: int = 65_536
    integration_event_max_bytes: int = 65_536
    integration_allow_loopback_callbacks: bool = True
    integration_secret_encryption_key: SecretStr = SecretStr("development-only-change-me")

    cdisc_library_base_url: str = "https://library.cdisc.org/api"
    cdisc_library_api_key: SecretStr | None = None
    cdisc_library_timeout_seconds: int = 30
    cdisc_library_max_resources: int = 250_000
    cdisc_library_parallel_requests: int = 12

    executor_adapter: Literal["docker", "ecs"] = "docker"
    execution_network_disabled: bool = True
    execution_cpu_limit: float = 2.0
    execution_memory_mb: int = 4096
    execution_timeout_seconds: int = 1800
    execution_output_limit_bytes: int = 1_073_741_824
    execution_log_limit_bytes: int = 1_048_576
    python_runner_image: str = "aurinara-python-runner:local"
    r_runner_image: str = "aurinara-r-runner:local"
    sas_runner_adapter: str | None = None
    execution_workspace_root: str | None = None
    ecs_cluster_arn: str | None = None
    ecs_python_task_definition: str | None = None
    ecs_r_task_definition: str | None = None
    ecs_runner_container_name: str = "runner"
    ecs_subnet_ids: str = ""
    ecs_security_group_ids: str = ""
    ecs_assign_public_ip: bool = False
    ecs_poll_interval_seconds: float = 2.0

    @property
    def cors_allow_origins(self) -> list[str]:
        """Return the configured CORS origins as a trimmed, non-empty list."""

        return [
            origin.strip() for origin in self.app_cors_allow_origins.split(",") if origin.strip()
        ]

    @property
    def ecs_subnets(self) -> list[str]:
        """Return configured private subnets for disposable runner tasks."""

        return [item.strip() for item in self.ecs_subnet_ids.split(",") if item.strip()]

    @property
    def ecs_security_groups(self) -> list[str]:
        """Return configured security groups for disposable runner tasks."""

        return [item.strip() for item in self.ecs_security_group_ids.split(",") if item.strip()]

    @model_validator(mode="after")
    def validate_database_configuration(self) -> Self:
        if self.database_url:
            return self
        missing = [
            name
            for name, value in (
                ("DATABASE_HOST", self.database_host),
                ("DATABASE_NAME", self.database_name),
                ("DATABASE_USER", self.database_user),
                ("DATABASE_PASSWORD", self.database_password),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                "database URL or complete split database settings are required: "
                + ", ".join(missing)
            )
        return self

    @model_validator(mode="after")
    def validate_execution_configuration(self) -> Self:
        if self.job_lease_heartbeat_seconds <= 0:
            raise ValueError("job lease heartbeat must be positive")
        if self.job_lease_heartbeat_seconds * 3 >= self.job_lease_seconds:
            raise ValueError("job lease heartbeat must be less than one-third of the lease")
        if self.executor_adapter == "ecs":
            required = {
                "execution workspace root": self.execution_workspace_root,
                "ECS cluster ARN": self.ecs_cluster_arn,
                "ECS Python task definition": self.ecs_python_task_definition,
                "ECS R task definition": self.ecs_r_task_definition,
            }
            missing = [name for name, value in required.items() if not value]
            if not self.ecs_subnets:
                missing.append("ECS subnet IDs")
            if not self.ecs_security_groups:
                missing.append("ECS security group IDs")
            if missing:
                raise ValueError("ECS executor configuration is incomplete: " + ", ".join(missing))
            cpu_units = int(self.execution_cpu_limit * 1024)
            valid_memory: dict[int, range | tuple[int, ...]] = {
                256: (512, 1024, 2048),
                512: (1024, 2048, 3072, 4096),
                1024: range(2048, 8193, 1024),
                2048: range(4096, 16385, 1024),
                4096: range(8192, 30721, 1024),
                8192: range(16384, 61441, 4096),
                16384: range(32768, 122881, 8192),
            }
            if (
                cpu_units not in valid_memory
                or self.execution_memory_mb not in valid_memory[cpu_units]
            ):
                raise ValueError("execution CPU and memory must form a valid Fargate size")
        return self

    @model_validator(mode="after")
    def validate_platform_authorization(self) -> Self:
        if not 0 <= self.platform_authorization_cache_seconds <= 60:
            raise ValueError("platform authorization cache must be between 0 and 60 seconds")
        if self.platform_authorization_mode != "disabled" and not self.platform_control_plane_url:
            raise ValueError("platform control-plane URL is required when authorization is enabled")
        return self

    @model_validator(mode="after")
    def reject_unsafe_production_configuration(self) -> Self:
        """Fail fast when development-only settings leak into production."""

        if self.app_env != "production":
            return self

        unsafe: list[str] = []
        if (
            self.object_store_access_key is not None
            and self.object_store_access_key.get_secret_value() == "minioadmin"
        ):
            unsafe.append("default object-store access key")
        if (
            self.object_store_secret_key is not None
            and self.object_store_secret_key.get_secret_value() == "minioadmin"
        ):
            unsafe.append("default object-store secret key")
        if (self.object_store_access_key is None) != (self.object_store_secret_key is None):
            unsafe.append("partial static object-store credentials")
        if self.object_store_endpoint and "localhost" in self.object_store_endpoint:
            unsafe.append("local object-store endpoint")
        if self.object_store_path_style:
            unsafe.append("path-style object-store addressing")
        if self.integration_allow_loopback_callbacks:
            unsafe.append("loopback integration callbacks")
        if (
            self.integration_secret_encryption_key.get_secret_value()
            == "development-only-change-me"
        ):
            unsafe.append("development integration encryption key")
        if not self.execution_network_disabled:
            unsafe.append("execution network access")
        if self.pinned_asset_local_fallback:
            unsafe.append("pinned asset local fallback")
        if ":local" in self.python_runner_image or ":local" in self.r_runner_image:
            unsafe.append("mutable local runner image")
        if "@sha256:" not in self.python_runner_image or "@sha256:" not in self.r_runner_image:
            unsafe.append("mutable runner image reference")
        if unsafe:
            joined = ", ".join(unsafe)
            raise ValueError(f"unsafe production configuration: {joined}")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache settings inside the settings boundary."""

    return Settings()
