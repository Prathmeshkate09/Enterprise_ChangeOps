"""FastAPI boundary for tenant-scoped Phase 4 analysis."""

from __future__ import annotations

from typing import Annotated

from changeops_contracts import AgentRegistration, FleetAnalysisRequest, FleetAnalysisResult
from changeops_core import Settings, configure_logging, get_settings
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from changeops_agent_fleet.evidence import (
    EvidenceProvider,
    EvidenceUnavailableError,
    HttpEvidenceProvider,
)
from changeops_agent_fleet.fleet import AgentFleet

TenantId = Annotated[str, Header(alias="X-Tenant-ID", min_length=1, max_length=128)]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    service: str
    status: str
    model_mode: str


def create_app(
    *, settings: Settings | None = None, evidence_provider: EvidenceProvider | None = None
) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)
    provider = evidence_provider or HttpEvidenceProvider(
        {
            "catalog": resolved.catalog_base_url,
            "crm": resolved.crm_base_url,
            "analytics": resolved.analytics_base_url,
            "support": resolved.support_base_url,
        }
    )
    runtime_url = f"http://{resolved.agent_fleet_host}:{resolved.agent_fleet_port}"
    fleet = AgentFleet(settings=resolved, evidence_provider=provider, runtime_base_url=runtime_url)
    app = FastAPI(
        title="Enterprise ChangeOps Agent Fleet",
        version="0.4.0",
        description="Evidence-backed, analysis-only Google ADK agent workflow.",
    )

    @app.exception_handler(EvidenceUnavailableError)
    async def evidence_unavailable(_: Request, __: EvidenceUnavailableError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": "evidence_unavailable",
                    "message": "Authoritative evidence could not be collected.",
                }
            },
        )

    @app.get("/health/live", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            service="agent-fleet", status="ok", model_mode=resolved.agent_model_mode.value
        )

    @app.get("/v1/agents", response_model=list[AgentRegistration])
    async def agents(tenant_id: TenantId) -> tuple[AgentRegistration, ...]:
        return fleet.registrations(tenant_id)

    @app.get("/v1/agents/{agent_id}", response_model=AgentRegistration)
    async def agent(agent_id: str, tenant_id: TenantId) -> AgentRegistration:
        registration = next(
            (item for item in fleet.registrations(tenant_id) if item.agent_id == agent_id), None
        )
        if registration is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
        return registration

    @app.post("/v1/analyses", response_model=FleetAnalysisResult)
    async def analyze(request: FleetAnalysisRequest, tenant_id: TenantId) -> FleetAnalysisResult:
        if request.event.tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="change not found")
        return await fleet.analyze(request)

    return app
