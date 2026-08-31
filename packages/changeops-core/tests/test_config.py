import pytest
from changeops_core.config import (
    AgentIdentityMode,
    AgentModelMode,
    AppEnvironment,
    GovernanceBackend,
    PersistenceBackend,
    Settings,
)
from pydantic import ValidationError


def test_settings_have_safe_local_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env is AppEnvironment.LOCAL
    assert settings.production_writes_enabled is False
    assert settings.persistence_backend is PersistenceBackend.MEMORY
    assert settings.gemini_primary_model == "gemini-3.5-flash"
    assert settings.agent_model_mode is AgentModelMode.FAKE
    assert settings.pubsub_change_topic == "changeops-change-events"
    assert settings.pubsub_manage_resources is True
    assert settings.workflow_max_attempts == 3
    assert settings.control_api_base_url == "http://127.0.0.1:8000"
    assert settings.governance_backend is GovernanceBackend.LOCAL
    assert settings.agent_identity_mode is AgentIdentityMode.LOCAL


def test_production_writes_fail_closed() -> None:
    with pytest.raises(ValidationError, match="Production writes are disabled"):
        Settings(PRODUCTION_WRITES_ENABLED=True, _env_file=None)


def test_firestore_backend_requires_explicit_project() -> None:
    with pytest.raises(ValidationError, match="GOOGLE_CLOUD_PROJECT"):
        Settings(PERSISTENCE_BACKEND="firestore", _env_file=None)


def test_live_gemini_mode_requires_explicit_vertex_configuration() -> None:
    with pytest.raises(ValidationError, match="Live Gemini mode requires"):
        Settings(AGENT_MODEL_MODE="live", _env_file=None)


def test_live_gemini_mode_accepts_complete_vertex_configuration() -> None:
    settings = Settings(
        AGENT_MODEL_MODE="live",
        GOOGLE_CLOUD_PROJECT="changeops-project",
        GOOGLE_CLOUD_LOCATION="us-central1",
        GOOGLE_GENAI_USE_VERTEXAI=True,
        _env_file=None,
    )

    assert settings.agent_model_mode is AgentModelMode.LIVE


def test_managed_governance_requires_every_managed_resource() -> None:
    with pytest.raises(ValidationError, match="MODEL_ARMOR_TEMPLATE"):
        Settings(
            GOVERNANCE_BACKEND="google_cloud",
            AGENT_IDENTITY_MODE="service_account",
            AGENT_SERVICE_ACCOUNT_DOMAIN="changeops-project.iam.gserviceaccount.com",
            GOOGLE_CLOUD_PROJECT="changeops-project",
            GOOGLE_CLOUD_LOCATION="us-central1",
            _env_file=None,
        )


def test_managed_governance_accepts_documented_scoped_fallback() -> None:
    settings = Settings(
        GOVERNANCE_BACKEND="google_cloud",
        AGENT_IDENTITY_MODE="service_account",
        AGENT_SERVICE_ACCOUNT_DOMAIN="changeops-project.iam.gserviceaccount.com",
        GOOGLE_CLOUD_PROJECT="changeops-project",
        GOOGLE_CLOUD_LOCATION="us-central1",
        MODEL_ARMOR_TEMPLATE=(
            "projects/changeops-project/locations/us-central1/templates/changeops-input"
        ),
        AGENT_REGISTRY_LOCATION="us-central1",
        MEMORY_BANK_ID=("projects/changeops-project/locations/us-central1/reasoningEngines/123456"),
        _env_file=None,
    )

    assert settings.governance_backend is GovernanceBackend.GOOGLE_CLOUD
    assert settings.agent_identity_mode is AgentIdentityMode.SERVICE_ACCOUNT
