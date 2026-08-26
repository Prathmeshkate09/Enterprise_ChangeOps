import pytest
from changeops_core.config import AppEnvironment, PersistenceBackend, Settings
from pydantic import ValidationError


def test_settings_have_safe_local_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env is AppEnvironment.LOCAL
    assert settings.production_writes_enabled is False
    assert settings.persistence_backend is PersistenceBackend.MEMORY
    assert settings.gemini_primary_model == "gemini-3.5-flash"


def test_production_writes_fail_closed() -> None:
    with pytest.raises(ValidationError, match="Production writes are disabled"):
        Settings(PRODUCTION_WRITES_ENABLED=True, _env_file=None)


def test_firestore_backend_requires_explicit_project() -> None:
    with pytest.raises(ValidationError, match="GOOGLE_CLOUD_PROJECT"):
        Settings(PERSISTENCE_BACKEND="firestore", _env_file=None)
