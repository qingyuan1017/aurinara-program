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

    database_url: str = "postgresql+psycopg://clinical:clinical@localhost:55432/clinical"

    object_store_endpoint: str = "http://localhost:9000"
    object_store_bucket: str = "clinical-artifacts"
    object_store_access_key: SecretStr = SecretStr("minioadmin")
    object_store_secret_key: SecretStr = SecretStr("minioadmin")
    object_store_region: str = "us-east-1"
    object_store_path_style: bool = True

    pinned_asset_local_fallback: bool = True

    jwt_issuer: str = "https://local-issuer.example"
    jwt_audience: str = "clinical-artifact-platform"
    jwt_jwks_url: str = "http://localhost:8081/.well-known/jwks.json"
    jwt_algorithms: str = "RS256"

    source_file_max_bytes: int = 1_073_741_824
    source_file_allowed_media_types: str = (
        "application/pdf,application/json,application/vnd.ms-excel,"
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "text/csv,text/plain,application/octet-stream"
    )

    job_lease_seconds: int = 60
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

    executor_adapter: str = "docker"
    execution_network_disabled: bool = True
    execution_cpu_limit: float = 2.0
    execution_memory_mb: int = 4096
    execution_timeout_seconds: int = 1800
    execution_output_limit_bytes: int = 1_073_741_824
    execution_log_limit_bytes: int = 1_048_576
    python_runner_image: str = "aurinara-python-runner:local"
    r_runner_image: str = "aurinara-r-runner:local"
    sas_runner_adapter: str | None = None

    @model_validator(mode="after")
    def reject_unsafe_production_configuration(self) -> Self:
        """Fail fast when development-only settings leak into production."""

        if self.app_env != "production":
            return self

        unsafe: list[str] = []
        if self.object_store_access_key.get_secret_value() == "minioadmin":
            unsafe.append("default object-store access key")
        if self.object_store_secret_key.get_secret_value() == "minioadmin":
            unsafe.append("default object-store secret key")
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
        if unsafe:
            joined = ", ".join(unsafe)
            raise ValueError(f"unsafe production configuration: {joined}")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache settings inside the settings boundary."""

    return Settings()
