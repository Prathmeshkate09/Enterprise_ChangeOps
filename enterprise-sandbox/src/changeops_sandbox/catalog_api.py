"""Customer API registry sandbox."""

from typing import Annotated

from fastapi import FastAPI, Query, status

from changeops_sandbox.app_factory import TenantId, create_sandbox_app
from changeops_sandbox.models import (
    ApiContract,
    CatalogActivationRequest,
    CatalogActivationResult,
    CatalogSeed,
    DependencyEdge,
    ResetResult,
    RestoreResult,
    SnapshotRecord,
)
from changeops_sandbox.seed_loader import load_seed
from changeops_sandbox.store import CatalogStore


def create_app(store: CatalogStore | None = None) -> FastAPI:
    state = store or CatalogStore(load_seed("catalog.json", CatalogSeed))
    app = create_sandbox_app(
        title="Enterprise ChangeOps Customer API Registry",
        component="customer-api-registry",
    )

    @app.get("/v1/contracts/customer-api", response_model=ApiContract, tags=["catalog"])
    async def active_contract(tenant_id: TenantId) -> ApiContract:
        return state.active_contract(tenant_id)

    @app.get(
        "/v1/contracts/customer-api/versions/{version}",
        response_model=ApiContract,
        tags=["catalog"],
    )
    async def contract_version(version: str, _: TenantId) -> ApiContract:
        return state.contract_version(version)

    @app.get("/v1/dependencies", response_model=list[DependencyEdge], tags=["catalog"])
    async def dependencies(
        _: TenantId,
        source: Annotated[str | None, Query(min_length=1)] = None,
    ) -> tuple[DependencyEdge, ...]:
        return state.dependencies(source)

    @app.post(
        "/v1/snapshots",
        response_model=SnapshotRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["catalog"],
    )
    async def snapshot(tenant_id: TenantId) -> SnapshotRecord:
        return state.snapshot(tenant_id)

    @app.post(
        "/v1/contracts/customer-api/activate",
        response_model=CatalogActivationResult,
        tags=["catalog"],
    )
    async def activate(
        request: CatalogActivationRequest,
        tenant_id: TenantId,
    ) -> CatalogActivationResult:
        return state.activate(tenant_id, request)

    @app.post(
        "/v1/snapshots/{snapshot_id}/restore",
        response_model=RestoreResult,
        tags=["catalog"],
    )
    async def restore(snapshot_id: str, tenant_id: TenantId) -> RestoreResult:
        return state.restore(tenant_id, snapshot_id)

    @app.post("/v1/admin/reset", response_model=ResetResult, tags=["admin"])
    async def reset(tenant_id: TenantId) -> ResetResult:
        return state.reset(tenant_id)

    return app


app = create_app()
