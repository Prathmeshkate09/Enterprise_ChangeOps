from typing import Any

from changeops_agent_fleet.app import create_app
from changeops_agent_fleet.evidence import StaticEvidenceProvider
from changeops_contracts import FleetAnalysisRequest
from changeops_core import Settings
from fastapi.testclient import TestClient


def test_registry_endpoint_is_tenant_scoped(evidence_payloads: dict[str, dict[str, Any]]) -> None:
    app = create_app(
        settings=Settings(agent_model_mode="fake"),
        evidence_provider=StaticEvidenceProvider(evidence_payloads),
    )

    with TestClient(app) as client:
        response = client.get("/v1/agents", headers={"X-Tenant-ID": "tenant-a"})

    assert response.status_code == 200
    assert len(response.json()) == 7
    assert {item["tenant_id"] for item in response.json()} == {"tenant-a"}


def test_analysis_rejects_cross_tenant_request(
    golden_request: FleetAnalysisRequest,
    evidence_payloads: dict[str, dict[str, Any]],
) -> None:
    app = create_app(
        settings=Settings(agent_model_mode="fake"),
        evidence_provider=StaticEvidenceProvider(evidence_payloads),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/analyses",
            headers={"X-Tenant-ID": "another-tenant"},
            json=golden_request.model_dump(mode="json"),
        )

    assert response.status_code == 404


def test_analysis_endpoint_returns_structured_result(
    golden_request: FleetAnalysisRequest,
    evidence_payloads: dict[str, dict[str, Any]],
) -> None:
    app = create_app(
        settings=Settings(agent_model_mode="fake"),
        evidence_provider=StaticEvidenceProvider(evidence_payloads),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/analyses",
            headers={"X-Tenant-ID": golden_request.event.tenant_id},
            json=golden_request.model_dump(mode="json"),
        )

    assert response.status_code == 200, response.text
    assert response.json()["model_mode"] == "fake"
    assert len(response.json()["remediation_proposals"]) == 3
