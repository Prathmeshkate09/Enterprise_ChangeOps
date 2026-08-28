"""Support portal lookup sandbox."""

from typing import Annotated

from fastapi import FastAPI, Query, status

from changeops_sandbox.app_factory import TenantId, create_sandbox_app
from changeops_sandbox.models import (
    FieldPatchRequest,
    FieldUsageResult,
    PatchPreview,
    PatchResult,
    ResetResult,
    RestoreResult,
    SnapshotRecord,
    SupportConfiguration,
    VerificationCheck,
    VerificationFailureRequest,
    VerificationFailureState,
    VerificationRequest,
    VerificationResult,
)
from changeops_sandbox.seed_loader import load_seed
from changeops_sandbox.store import ConfigurationStore


def create_app(store: ConfigurationStore[SupportConfiguration] | None = None) -> FastAPI:
    state = store or ConfigurationStore(
        load_seed("support.json", SupportConfiguration),
        SupportConfiguration,
        field_name="lookup_field",
    )
    app = create_sandbox_app(
        title="Enterprise ChangeOps Support Sandbox",
        component="support-sandbox",
    )

    @app.get("/v1/configuration", response_model=SupportConfiguration, tags=["configuration"])
    async def configuration(tenant_id: TenantId) -> SupportConfiguration:
        return state.get(tenant_id)

    @app.get("/v1/field-usage", response_model=FieldUsageResult, tags=["discovery"])
    async def field_usage(
        tenant_id: TenantId,
        field: Annotated[str, Query(min_length=1)],
    ) -> FieldUsageResult:
        current = state.get(tenant_id)
        resources: tuple[str, ...] = ()
        if field == current.lookup_field:
            resources = tuple(f"form://{form}" for form in current.dependent_forms)
        return FieldUsageResult(field=field, resources=resources)

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
        "/v1/verification/lookup",
        response_model=VerificationResult,
        tags=["verification"],
    )
    async def verify(
        request: VerificationRequest,
        tenant_id: TenantId,
    ) -> VerificationResult:
        current = state.get(tenant_id)
        injected_failure = state.consume_verification_failure(tenant_id)
        field_matches = current.lookup_field == request.expected_field and not injected_failure
        healthy = current.status == "healthy"
        checks = (
            VerificationCheck(
                name="lookup_field",
                passed=field_matches,
                detail=(
                    "Injected support lookup verification failure."
                    if injected_failure
                    else f"Support lookup field is {current.lookup_field}."
                ),
            ),
            VerificationCheck(
                name="dependent_forms",
                passed=bool(current.dependent_forms),
                detail="Dependent synthetic forms remain registered.",
            ),
            VerificationCheck(
                name="service_health",
                passed=healthy,
                detail=f"Support portal status is {current.status}.",
            ),
        )
        return VerificationResult(
            system_id=current.system_id,
            passed=all(check.passed for check in checks),
            checks=checks,
        )

    @app.post(
        "/v1/admin/verification-failures",
        response_model=VerificationFailureState,
        tags=["admin"],
    )
    async def inject_verification_failure(
        request: VerificationFailureRequest,
        tenant_id: TenantId,
    ) -> VerificationFailureState:
        return state.inject_verification_failures(tenant_id, request.count)

    @app.post("/v1/admin/reset", response_model=ResetResult, tags=["admin"])
    async def reset(tenant_id: TenantId) -> ResetResult:
        return state.reset(tenant_id)

    return app


app = create_app()
