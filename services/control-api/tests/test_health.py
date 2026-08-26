from changeops_core import Settings
from changeops_persistence import InMemoryChangeStateRepository
from control_api.app import create_app
from control_api.main import app
from fastapi.testclient import TestClient


def test_liveness_is_local_and_cache_safe() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"service": "control-api", "status": "ok"}


def test_metadata_discloses_safe_environment() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json()["production_writes_enabled"] is False
    assert response.json()["persistence_backend"] == "memory"


class UnavailableRepository(InMemoryChangeStateRepository):
    def check_ready(self) -> None:
        raise RuntimeError("simulated persistence outage")


def test_readiness_fails_when_persistence_is_unavailable() -> None:
    settings = Settings(APP_ENV="test", PERSISTENCE_BACKEND="memory", _env_file=None)
    unavailable_app = create_app(repository=UnavailableRepository(), settings=settings)

    with TestClient(unavailable_app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"service": "control-api", "status": "unavailable"}
