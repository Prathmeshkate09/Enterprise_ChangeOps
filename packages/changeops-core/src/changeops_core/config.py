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


class AgentModelMode(StrEnum):
    """Agent model providers supported by the fleet."""

    FAKE = "fake"
    LIVE = "live"


class GovernanceBackend(StrEnum):
    """Prompt, registry, memory, identity, and secret governance adapters."""

    LOCAL = "local"
    GOOGLE_CLOUD = "google_cloud"


class AgentIdentityMode(StrEnum):
    """Identity representation used in agent registrations."""

    LOCAL = "local"
    AGENT_IDENTITY = "agent_identity"
    SERVICE_ACCOUNT = "service_account"


class ServiceAuthMode(StrEnum):
    """Authentication applied to private service-to-service HTTP requests."""

    NONE = "none"
    GOOGLE_CLOUD = "google_cloud"


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
    agent_fleet_host: str = Field(default="127.0.0.1", validation_alias="AGENT_FLEET_HOST")
    agent_fleet_port: int = Field(
        default=8200,
        ge=1,
        le=65535,
        validation_alias="AGENT_FLEET_PORT",
    )
    tool_gateway_host: str = Field(default="127.0.0.1", validation_alias="TOOL_GATEWAY_HOST")
    tool_gateway_port: int = Field(
        default=8300,
        ge=1,
        le=65535,
        validation_alias="TOOL_GATEWAY_PORT",
    )
    tool_gateway_auth_secret: str | None = Field(
        default=None,
        min_length=32,
        validation_alias="TOOL_GATEWAY_AUTH_SECRET",
    )
    event_gateway_host: str = Field(default="127.0.0.1", validation_alias="EVENT_GATEWAY_HOST")
    event_gateway_port: int = Field(
        default=8400,
        ge=1,
        le=65535,
        validation_alias="EVENT_GATEWAY_PORT",
    )
    event_gateway_webhook_secret: str | None = Field(
        default=None,
        min_length=32,
        validation_alias="EVENT_GATEWAY_WEBHOOK_SECRET",
    )
    event_rate_limit_per_minute: int = Field(
        default=60,
        ge=1,
        le=10_000,
        validation_alias="EVENT_RATE_LIMIT_PER_MINUTE",
    )
    event_max_request_bytes: int = Field(
        default=262_144,
        ge=1_024,
        le=10_485_760,
        validation_alias="EVENT_MAX_REQUEST_BYTES",
    )
    workflow_coordinator_host: str = Field(
        default="127.0.0.1",
        validation_alias="WORKFLOW_COORDINATOR_HOST",
    )
    workflow_coordinator_port: int = Field(
        default=8500,
        ge=1,
        le=65535,
        validation_alias="WORKFLOW_COORDINATOR_PORT",
    )
    workflow_callback_url: str | None = Field(
        default=None,
        validation_alias="WORKFLOW_CALLBACK_URL",
    )
    workflow_callback_secret: str | None = Field(
        default=None,
        min_length=32,
        validation_alias="WORKFLOW_CALLBACK_SECRET",
    )
    workflow_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias="WORKFLOW_MAX_ATTEMPTS",
    )
    workflow_retry_base_seconds: float = Field(
        default=0.25,
        ge=0.01,
        le=60,
        validation_alias="WORKFLOW_RETRY_BASE_SECONDS",
    )
    agent_fleet_base_url: str = Field(
        default="http://127.0.0.1:8200",
        validation_alias="AGENT_FLEET_BASE_URL",
    )
    tool_gateway_base_url: str = Field(
        default="http://127.0.0.1:8300",
        validation_alias="TOOL_GATEWAY_BASE_URL",
    )
    control_api_base_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias="CONTROL_API_BASE_URL",
    )
    agent_model_mode: AgentModelMode = Field(
        default=AgentModelMode.FAKE,
        validation_alias="AGENT_MODEL_MODE",
    )
    agent_model_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=300,
        validation_alias="AGENT_MODEL_TIMEOUT_SECONDS",
    )
    catalog_base_url: str = Field(
        default="http://127.0.0.1:8100",
        validation_alias="CATALOG_BASE_URL",
    )
    crm_base_url: str = Field(
        default="http://127.0.0.1:8101",
        validation_alias="CRM_BASE_URL",
    )
    analytics_base_url: str = Field(
        default="http://127.0.0.1:8102",
        validation_alias="ANALYTICS_BASE_URL",
    )
    support_base_url: str = Field(
        default="http://127.0.0.1:8103",
        validation_alias="SUPPORT_BASE_URL",
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
    service_auth_mode: ServiceAuthMode = Field(
        default=ServiceAuthMode.NONE,
        validation_alias="SERVICE_AUTH_MODE",
    )

    google_cloud_project: str | None = Field(default=None, validation_alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str | None = Field(
        default=None,
        validation_alias="GOOGLE_CLOUD_LOCATION",
    )
    google_genai_use_vertexai: bool = Field(
        default=False,
        validation_alias="GOOGLE_GENAI_USE_VERTEXAI",
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
    pubsub_change_topic: str = Field(
        default="changeops-change-events",
        min_length=3,
        validation_alias="PUBSUB_CHANGE_TOPIC",
    )
    pubsub_change_subscription: str = Field(
        default="changeops-workflow-coordinator",
        min_length=3,
        validation_alias="PUBSUB_CHANGE_SUBSCRIPTION",
    )
    pubsub_dead_letter_topic: str = Field(
        default="changeops-change-events-dlq",
        min_length=3,
        validation_alias="PUBSUB_DEAD_LETTER_TOPIC",
    )
    pubsub_dead_letter_subscription: str = Field(
        default="changeops-change-events-dlq-inspection",
        min_length=3,
        validation_alias="PUBSUB_DEAD_LETTER_SUBSCRIPTION",
    )
    pubsub_manage_resources: bool = Field(
        default=True,
        validation_alias="PUBSUB_MANAGE_RESOURCES",
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
    governance_backend: GovernanceBackend = Field(
        default=GovernanceBackend.LOCAL,
        validation_alias="GOVERNANCE_BACKEND",
    )
    agent_identity_mode: AgentIdentityMode = Field(
        default=AgentIdentityMode.LOCAL,
        validation_alias="AGENT_IDENTITY_MODE",
    )
    agent_identity_prefix: str | None = Field(
        default=None,
        validation_alias="AGENT_IDENTITY_PREFIX",
    )
    agent_service_account_domain: str | None = Field(
        default=None,
        validation_alias="AGENT_SERVICE_ACCOUNT_DOMAIN",
    )
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
    )
    auth_audience: str | None = Field(default=None, validation_alias="AUTH_AUDIENCE")
    demo_tenant_id: str | None = Field(default=None, validation_alias="DEMO_TENANT_ID")
    enterprise_access_enabled: bool = Field(
        default=False, validation_alias="ENTERPRISE_ACCESS_ENABLED"
    )
    identity_platform_project: str | None = Field(
        default=None, validation_alias="IDENTITY_PLATFORM_PROJECT"
    )

    @model_validator(mode="after")
    def reject_production_writes(self) -> "Settings":
        """Fail closed if any environment attempts to enable production writes."""

        if self.production_writes_enabled:
            raise ValueError("Production writes are disabled in Enterprise ChangeOps.")
        if self.enterprise_access_enabled and (
            not self.identity_platform_project
            or self.persistence_backend is not PersistenceBackend.FIRESTORE
        ):
            raise ValueError(
                "Enterprise access requires IDENTITY_PLATFORM_PROJECT and Firestore persistence."
            )
        if (
            self.persistence_backend is PersistenceBackend.FIRESTORE
            and not self.google_cloud_project
        ):
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for the Firestore backend.")
        if self.agent_model_mode is AgentModelMode.LIVE and (
            not self.google_cloud_project
            or not self.google_cloud_location
            or not self.google_genai_use_vertexai
        ):
            raise ValueError(
                "Live Gemini mode requires GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, "
                "and GOOGLE_GENAI_USE_VERTEXAI=true."
            )
        if self.governance_backend is GovernanceBackend.GOOGLE_CLOUD:
            required = {
                "GOOGLE_CLOUD_PROJECT": self.google_cloud_project,
                "GOOGLE_CLOUD_LOCATION": self.google_cloud_location,
                "MODEL_ARMOR_TEMPLATE": self.model_armor_template,
                "AGENT_REGISTRY_LOCATION": self.agent_registry_location,
                "MEMORY_BANK_ID": self.memory_bank_id,
            }
            missing = tuple(name for name, value in required.items() if not value)
            if missing:
                raise ValueError(
                    "Managed governance requires explicit configuration: " + ", ".join(missing)
                )
            if self.agent_identity_mode is AgentIdentityMode.LOCAL:
                raise ValueError("Managed governance cannot use local agent identities.")
        if self.agent_identity_mode is AgentIdentityMode.AGENT_IDENTITY:
            if not self.agent_identity_prefix:
                raise ValueError("AGENT_IDENTITY_PREFIX is required for Agent Identity mode.")
        if self.agent_identity_mode is AgentIdentityMode.SERVICE_ACCOUNT:
            if not self.agent_service_account_domain:
                raise ValueError(
                    "AGENT_SERVICE_ACCOUNT_DOMAIN is required for service-account identity mode."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the validated process-wide settings instance."""

    return Settings()


def clear_settings_cache() -> None:
    """Clear cached settings for tests and explicit configuration reloads."""

    get_settings.cache_clear()
