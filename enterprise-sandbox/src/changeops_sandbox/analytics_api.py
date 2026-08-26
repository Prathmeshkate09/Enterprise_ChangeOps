"""Analytics transformation sandbox with deterministic transient failure injection."""

from typing import Annotated

from fastapi import FastAPI, Query, status

from changeops_sandbox.app_factory import TenantId, create_sandbox_app
from changeops_sandbox.models import (
    AnalyticsConfiguration,
    AnalyticsDataProfile,
    DataQualityResult,
    FieldPatchRequest,
    FieldUsageResult,
    PatchPreview,
    PatchResult,
    ResetResult,
    RestoreResult,
    SnapshotRecord,
    TransientFailureRequest,
    TransientFailureState,
    VerificationCheck,
    VerificationRequest,
)
from changeops_sandbox.seed_loader import load_seed
from changeops_sandbox.store import ConfigurationStore


def create_app(
    store: ConfigurationStore[AnalyticsConfiguration] | None = None,
    data_profile: AnalyticsDataProfile | None = None,
) -> FastAPI:
    state = store or ConfigurationStore(
        load_seed("analytics.json", AnalyticsConfiguration),
        AnalyticsConfiguration,
        field_name="source_field",
    )
    observed_data = data_profile or load_seed(
        "analytics_data_profile.json",
        AnalyticsDataProfile,
    )
    app = create_sandbox_app(
        title="Enterprise ChangeOps Analytics Sandbox",
        component="analytics-sandbox",
    )

    @app.get("/v1/configuration", response_model=AnalyticsConfiguration, tags=["configuration"])
    async def configuration(tenant_id: TenantId) -> AnalyticsConfiguration:
        return state.get(tenant_id)

    @app.get("/v1/field-usage", response_model=FieldUsageResult, tags=["discovery"])
    async def field_usage(
        tenant_id: TenantId,
        field: Annotated[str, Query(min_length=1)],
    ) -> FieldUsageResult:
        current = state.get(tenant_id)
        resources: tuple[str, ...] = ()
        if field == current.source_field:
            resources = (
                f"transformation://{current.system_id}",
                *(f"dashboard://{dashboard}" for dashboard in current.dependent_dashboards),
            )
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
        "/v1/admin/transient-failures",
        response_model=TransientFailureState,
        tags=["admin"],
    )
    async def inject_failure(
        request: TransientFailureRequest,
        tenant_id: TenantId,
    ) -> TransientFailureState:
        return state.inject_transient_failures(tenant_id, request.count)

    @app.post(
        "/v1/verification/data-quality",
        response_model=DataQualityResult,
        tags=["verification"],
    )
    async def verify(
        request: VerificationRequest,
        tenant_id: TenantId,
    ) -> DataQualityResult:
        current = state.get(tenant_id)
        field_matches = current.source_field == request.expected_field
        healthy = current.status == "healthy"
        dataset_matches = observed_data.system_id == current.system_id
        row_count_matches = observed_data.observed_row_count == current.baseline_row_count
        null_rate = observed_data.identifier_null_count / observed_data.observed_row_count
        identifiers_complete = null_rate == 0.0
        checks = (
            VerificationCheck(
                name="source_field",
                passed=field_matches,
                detail=f"Transformation source field is {current.source_field}.",
            ),
            VerificationCheck(
                name="dataset_identity",
                passed=dataset_matches,
                detail=f"Observed dataset belongs to {observed_data.system_id}.",
            ),
            VerificationCheck(
                name="row_count",
                passed=row_count_matches,
                detail=(
                    f"Observed {observed_data.observed_row_count} rows against the "
                    f"{current.baseline_row_count}-row baseline."
                ),
            ),
            VerificationCheck(
                name="null_rate",
                passed=identifiers_complete,
                detail=(
                    f"Observed {observed_data.identifier_null_count} null identifiers "
                    f"across {observed_data.observed_row_count} rows."
                ),
            ),
            VerificationCheck(
                name="service_health",
                passed=healthy,
                detail=f"Analytics transformation status is {current.status}.",
            ),
        )
        return DataQualityResult(
            system_id=current.system_id,
            passed=all(check.passed for check in checks),
            checks=checks,
            baseline_row_count=current.baseline_row_count,
            observed_row_count=observed_data.observed_row_count,
            null_rate=null_rate,
        )

    @app.post("/v1/admin/reset", response_model=ResetResult, tags=["admin"])
    async def reset(tenant_id: TenantId) -> ResetResult:
        return state.reset(tenant_id)

    return app


app = create_app()
