"""CRM synchronization sandbox."""

from fastapi import FastAPI, status

from changeops_sandbox.app_factory import TenantId, create_sandbox_app
from changeops_sandbox.models import (
    CrmConfiguration,
    FieldPatchRequest,
    PatchPreview,
    PatchResult,
    ResetResult,
    RestoreResult,
    SnapshotRecord,
    VerificationCheck,
    VerificationRequest,
    VerificationResult,
)
from changeops_sandbox.seed_loader import load_seed
from changeops_sandbox.store import ConfigurationStore


def create_app(store: ConfigurationStore[CrmConfiguration] | None = None) -> FastAPI:
    state = store or ConfigurationStore(
        load_seed("crm.json", CrmConfiguration),
        CrmConfiguration,
        field_name="source_field",
    )
    app = create_sandbox_app(title="Enterprise ChangeOps CRM Sandbox", component="crm-sandbox")

    @app.get("/v1/configuration", response_model=CrmConfiguration, tags=["configuration"])
    async def configuration(tenant_id: TenantId) -> CrmConfiguration:
        return state.get(tenant_id)

    @app.post(
        "/v1/snapshots",
        response_model=SnapshotRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["change"],
    )
    async def snapshot(tenant_id: TenantId) -> SnapshotRecord:
        return state.snapshot(tenant_id)

    @app.post("/v1/patches/dry-run", response_model=PatchPreview, tags=["change"])
    async def dry_run(request: FieldPatchRequest, tenant_id: TenantId) -> PatchPreview:
        return state.dry_run(tenant_id, request)

    @app.post("/v1/patches/apply", response_model=PatchResult, tags=["change"])
    async def apply_patch(request: FieldPatchRequest, tenant_id: TenantId) -> PatchResult:
        return state.apply(tenant_id, request)

    @app.post(
        "/v1/snapshots/{snapshot_id}/restore",
        response_model=RestoreResult,
        tags=["change"],
    )
    async def restore(snapshot_id: str, tenant_id: TenantId) -> RestoreResult:
        return state.restore(tenant_id, snapshot_id)

    @app.post(
        "/v1/verification/synchronization",
        response_model=VerificationResult,
        tags=["verification"],
    )
    async def verify(
        request: VerificationRequest,
        tenant_id: TenantId,
    ) -> VerificationResult:
        current = state.get(tenant_id)
        field_matches = current.source_field == request.expected_field
        healthy = current.status == "healthy"
        checks = (
            VerificationCheck(
                name="source_field",
                passed=field_matches,
                detail=f"Configured source field is {current.source_field}.",
            ),
            VerificationCheck(
                name="service_health",
                passed=healthy,
                detail=f"CRM synchronization status is {current.status}.",
            ),
        )
        return VerificationResult(
            system_id=current.system_id,
            passed=all(check.passed for check in checks),
            checks=checks,
        )

    @app.post("/v1/admin/reset", response_model=ResetResult, tags=["admin"])
    async def reset(tenant_id: TenantId) -> ResetResult:
        return state.reset(tenant_id)

    return app


app = create_app()
