"""Typed API gate for the customer identifier migration and compensation path."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

from changeops_sandbox.analytics_api import create_app as create_analytics_app
from changeops_sandbox.catalog_api import create_app as create_catalog_app
from changeops_sandbox.crm_api import create_app as create_crm_app
from changeops_sandbox.models import AnalyticsDataProfile
from changeops_sandbox.support_api import create_app as create_support_app
from fastapi.testclient import TestClient

TENANT_HEADERS = {"X-Tenant-ID": "tenant_demo", "X-Request-ID": "req_phase2_test"}
PLAN_HASH = f"sha256:{'a' * 64}"


def patch_payload(system: str) -> dict[str, Any]:
    return {
        "old_field": "customer_id",
        "new_field": "customer_uuid",
        "idempotency_key": f"chg_001:{system}:customer-uuid",
        "change_id": "chg_001",
        "plan_hash": PLAN_HASH,
    }


def post_json(client: TestClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, headers=TENANT_HEADERS, json=payload)
    response.raise_for_status()
    return response.json()


def get_json(client: TestClient, path: str) -> dict[str, Any]:
    response = client.get(path, headers=TENANT_HEADERS)
    response.raise_for_status()
    return response.json()


def test_typed_calls_complete_verify_and_roll_back_field_migration() -> None:
    with ExitStack() as stack:
        catalog = stack.enter_context(TestClient(create_catalog_app()))
        crm = stack.enter_context(TestClient(create_crm_app()))
        analytics = stack.enter_context(TestClient(create_analytics_app()))
        support = stack.enter_context(TestClient(create_support_app()))

        catalog_snapshot = post_json(catalog, "/v1/snapshots", {})
        crm_snapshot = post_json(crm, "/v1/snapshots", {})
        analytics_snapshot = post_json(analytics, "/v1/snapshots", {})
        support_snapshot = post_json(support, "/v1/snapshots", {})

        activation = post_json(
            catalog,
            "/v1/contracts/customer-api/activate",
            {
                "version": "2.0.0",
                "idempotency_key": "chg_001:catalog:activate-v2",
                "change_id": "chg_001",
                "plan_hash": PLAN_HASH,
            },
        )
        assert activation["active_contract"]["identifier_field"] == "customer_uuid"

        crm_preview = post_json(crm, "/v1/patches/dry-run", patch_payload("crm"))
        assert crm_preview["would_change"] is True
        post_json(crm, "/v1/patches/apply", patch_payload("crm"))

        usage = get_json(analytics, "/v1/field-usage?field=customer_id")
        assert "transformation://customer-daily-etl" in usage["resources"]
        post_json(analytics, "/v1/admin/transient-failures", {"count": 1})
        first_analytics_attempt = analytics.post(
            "/v1/patches/apply",
            headers=TENANT_HEADERS,
            json=patch_payload("analytics"),
        )
        assert first_analytics_attempt.status_code == 503
        assert first_analytics_attempt.json()["error"]["code"] == "transient_sandbox_failure"
        analytics_result = post_json(
            analytics,
            "/v1/patches/apply",
            patch_payload("analytics"),
        )
        assert analytics_result["replayed"] is False
        analytics_replay = post_json(
            analytics,
            "/v1/patches/apply",
            patch_payload("analytics"),
        )
        assert analytics_replay["replayed"] is True

        post_json(support, "/v1/patches/apply", patch_payload("support"))

        assert get_json(crm, "/v1/configuration")["source_field"] == "customer_uuid"
        assert get_json(analytics, "/v1/configuration")["source_field"] == "customer_uuid"
        assert get_json(support, "/v1/configuration")["lookup_field"] == "customer_uuid"
        assert (
            post_json(
                crm,
                "/v1/verification/synchronization",
                {"expected_field": "customer_uuid"},
            )["passed"]
            is True
        )
        analytics_quality = post_json(
            analytics,
            "/v1/verification/data-quality",
            {"expected_field": "customer_uuid"},
        )
        assert analytics_quality["passed"] is True
        assert analytics_quality["observed_row_count"] == analytics_quality["baseline_row_count"]
        assert (
            post_json(
                support,
                "/v1/verification/lookup",
                {"expected_field": "customer_uuid"},
            )["passed"]
            is True
        )

        post_json(
            support,
            f"/v1/snapshots/{support_snapshot['snapshot_id']}/restore",
            {},
        )
        post_json(
            analytics,
            f"/v1/snapshots/{analytics_snapshot['snapshot_id']}/restore",
            {},
        )
        post_json(crm, f"/v1/snapshots/{crm_snapshot['snapshot_id']}/restore", {})
        post_json(
            catalog,
            f"/v1/snapshots/{catalog_snapshot['snapshot_id']}/restore",
            {},
        )

        assert get_json(crm, "/v1/configuration")["source_field"] == "customer_id"
        assert get_json(analytics, "/v1/configuration")["source_field"] == "customer_id"
        assert get_json(support, "/v1/configuration")["lookup_field"] == "customer_id"
        assert get_json(catalog, "/v1/contracts/customer-api")["version"] == "1.4.0"


def test_idempotent_crm_retry_does_not_increment_schema_twice() -> None:
    with TestClient(create_crm_app()) as client:
        payload = patch_payload("crm")
        first = post_json(client, "/v1/patches/apply", payload)
        second = post_json(client, "/v1/patches/apply", payload)

        assert first["replayed"] is False
        assert second["replayed"] is True
        assert get_json(client, "/v1/configuration")["schema_version"] == 5


def test_analytics_data_quality_is_computed_from_observed_profile() -> None:
    degraded_profile = AnalyticsDataProfile(
        system_id="customer-daily-etl",
        observed_row_count=998,
        identifier_null_count=2,
    )
    with TestClient(create_analytics_app(data_profile=degraded_profile)) as client:
        result = post_json(
            client,
            "/v1/verification/data-quality",
            {"expected_field": "customer_id"},
        )

        assert result["passed"] is False
        assert result["observed_row_count"] == 998
        assert result["null_rate"] == 2 / 998
        checks = {check["name"]: check for check in result["checks"]}
        assert checks["row_count"]["passed"] is False
        assert checks["null_rate"]["passed"] is False


def test_cross_tenant_snapshot_restore_fails_closed() -> None:
    with TestClient(create_crm_app()) as client:
        snapshot = client.post(
            "/v1/snapshots",
            headers={"X-Tenant-ID": "tenant_alpha"},
        ).json()
        response = client.post(
            f"/v1/snapshots/{snapshot['snapshot_id']}/restore",
            headers={"X-Tenant-ID": "tenant_beta"},
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "tenant_scope_violation"


def test_tenant_and_request_validation_use_stable_errors() -> None:
    with TestClient(create_support_app()) as client:
        missing_tenant = client.get("/v1/configuration", headers={"X-Request-ID": "req_known"})
        invalid_patch = client.post(
            "/v1/patches/apply",
            headers=TENANT_HEADERS,
            json={"old_field": "customer_id"},
        )

        assert missing_tenant.status_code == 401
        assert missing_tenant.headers["X-Request-ID"] == "req_known"
        assert missing_tenant.json()["error"]["code"] == "tenant_required"
        assert invalid_patch.status_code == 422
        assert invalid_patch.json()["error"]["code"] == "validation_error"
        assert all("input" not in detail for detail in invalid_patch.json()["error"]["details"])


def test_catalog_marks_unmanaged_dependency_for_human_follow_up() -> None:
    with TestClient(create_catalog_app()) as client:
        payload = get_json(client, "/v1/dependencies?source=customer-api")

        unmanaged = [edge for edge in payload if edge["managed"] is False]
        assert unmanaged == [
            {"source": "customer-api", "target": "order-service", "managed": False}
        ]
