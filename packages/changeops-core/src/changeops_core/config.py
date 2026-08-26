"""Validated, environment-driven configuration shared by all services."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    """Supported runtime environments."""

    LOCAL = "local"
    TEST = "test"
    SANDBOX = "sandbox"


class PersistenceBackend(StrEnum):
    """Supported operational-state adapters."""

    MEMORY = "memory"
    FIRESTORE = "firestore"


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    Cloud settings remain optional until the corresponding managed adapter is
    enabled. Production mutations are deliberately impossible in this build.
    """

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnvironment = Field(default=AppEnvironment.LOCAL, validation_alias="APP_ENV")
    app_region: str = Field(default="local", min_length=1, validation_alias="APP_REGION")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    control_api_host: str = Field(default="127.0.0.1", validation_alias="CONTROL_API_HOST")
    control_api_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        validation_alias="CONTROL_API_PORT",
    )
    control_tower_origin: str = Field(
        default="http://127.0.0.1:3000",
        validation_alias="CONTROL_TOWER_ORIGIN",
    )
    production_writes_enabled: bool = Field(
        default=False,
        validation_alias="PRODUCTION_WRITES_ENABLED",
    )
    persistence_backend: PersistenceBackend = Field(
        default=PersistenceBackend.MEMORY,
        validation_alias="PERSISTENCE_BACKEND",
    )

    google_cloud_project: str | None = Field(default=None, validation_alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str | None = Field(
        default=None,
        validation_alias="GOOGLE_CLOUD_LOCATION",
    )
    gemini_primary_model: str = Field(
        default="gemini-3.5-flash",
        validation_alias="GEMINI_PRIMARY_MODEL",
    )
    gemini_light_model: str = Field(
        default="gemini-3.5-flash-lite",
        validation_alias="GEMINI_LIGHT_MODEL",
    )
    firestore_database: str = Field(
        default="(default)",
        min_length=1,
        validation_alias="FIRESTORE_DATABASE",
    )
    pubsub_change_topic: str | None = Field(default=None, validation_alias="PUBSUB_CHANGE_TOPIC")
    pubsub_dead_letter_topic: str | None = Field(
        default=None,
        validation_alias="PUBSUB_DEAD_LETTER_TOPIC",
    )
    workflow_name: str | None = Field(default=None, validation_alias="WORKFLOW_NAME")
    artifact_bucket: str | None = Field(default=None, validation_alias="ARTIFACT_BUCKET")
    model_armor_template: str | None = Field(default=None, validation_alias="MODEL_ARMOR_TEMPLATE")
    agent_registry_location: str | None = Field(
        default=None,
        validation_alias="AGENT_REGISTRY_LOCATION",
    )
    agent_gateway_endpoint: str | None = Field(
        default=None,
        validation_alias="AGENT_GATEWAY_ENDPOINT",
    )
    memory_bank_id: str | None = Field(default=None, validation_alias="MEMORY_BANK_ID")
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
    )
    auth_audience: str | None = Field(default=None, validation_alias="AUTH_AUDIENCE")
    demo_tenant_id: str | None = Field(default=None, validation_alias="DEMO_TENANT_ID")

    @model_validator(mode="after")
    def reject_production_writes(self) -> "Settings":
        """Fail closed if any environment attempts to enable production writes."""

        if self.production_writes_enabled:
            raise ValueError("Production writes are disabled in Enterprise ChangeOps.")
        if (
            self.persistence_backend is PersistenceBackend.FIRESTORE
            and not self.google_cloud_project
        ):
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for the Firestore backend.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the validated process-wide settings instance."""

    return Settings()


def clear_settings_cache() -> None:
    """Clear cached settings for tests and explicit configuration reloads."""

    get_settings.cache_clear()
