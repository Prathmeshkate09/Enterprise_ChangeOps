"""Exercise the Phase 2 sandbox migration and compensation over real HTTP."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

TENANT_ID = os.environ.get("SANDBOX_TENANT_ID", "tenant_demo")
PLAN_HASH = f"sha256:{'a' * 64}"
BASE_URLS = {
    "catalog": os.environ.get("CATALOG_SANDBOX_URL", "http://127.0.0.1:8100"),
    "crm": os.environ.get("CRM_SANDBOX_URL", "http://127.0.0.1:8101"),
    "analytics": os.environ.get("ANALYTICS_SANDBOX_URL", "http://127.0.0.1:8102"),
    "support": os.environ.get("SUPPORT_SANDBOX_URL", "http://127.0.0.1:8103"),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def request_json(
    service: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    expected_status: int = 200,
) -> dict[str, Any]:
    url = f"{BASE_URLS[service]}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Request-ID": f"req_phase2_{service}",
            "X-Tenant-ID": TENANT_ID,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            status = response.status
            document: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        status = error.code
        document = json.loads(error.read().decode("utf-8"))
    require(
        status == expected_status,
        f"{service} {method} {path} returned {status}, expected {expected_status}: {document}",
    )
    return document


def patch_payload(service: str) -> dict[str, Any]:
    return {
        "old_field": "customer_id",
        "new_field": "customer_uuid",
        "idempotency_key": f"chg_001:{service}:customer-uuid",
        "change_id": "chg_001",
        "plan_hash": PLAN_HASH,
    }


def main() -> None:
    for service in BASE_URLS:
        request_json(service, "POST", "/v1/admin/reset", {})

    snapshots = {
        service: request_json(
            service,
            "POST",
            "/v1/snapshots",
            {},
            expected_status=201,
        )["snapshot_id"]
        for service in BASE_URLS
    }
    request_json(
        "catalog",
        "POST",
        "/v1/contracts/customer-api/activate",
        {
            "version": "2.0.0",
            "idempotency_key": "chg_001:catalog:activate-v2",
            "change_id": "chg_001",
            "plan_hash": PLAN_HASH,
        },
    )
    request_json("crm", "POST", "/v1/patches/dry-run", patch_payload("crm"))
    request_json("crm", "POST", "/v1/patches/apply", patch_payload("crm"))
    request_json("analytics", "POST", "/v1/admin/transient-failures", {"count": 1})
    transient = request_json(
        "analytics",
        "POST",
        "/v1/patches/apply",
        patch_payload("analytics"),
        expected_status=503,
    )
    require(
        transient["error"]["code"] == "transient_sandbox_failure",
        "Analytics did not return the declared transient error.",
    )
    request_json("analytics", "POST", "/v1/patches/apply", patch_payload("analytics"))
    replay = request_json(
        "analytics",
        "POST",
        "/v1/patches/apply",
        patch_payload("analytics"),
    )
    require(replay["replayed"] is True, "Analytics retry was not idempotently replayed.")
    request_json("support", "POST", "/v1/patches/apply", patch_payload("support"))

    verification_paths = {
        "crm": "/v1/verification/synchronization",
        "analytics": "/v1/verification/data-quality",
        "support": "/v1/verification/lookup",
    }
    for service, path in verification_paths.items():
        result = request_json(
            service,
            "POST",
            path,
            {"expected_field": "customer_uuid"},
        )
        require(result["passed"] is True, f"{service} verification failed: {result}")

    for service in ("support", "analytics", "crm", "catalog"):
        request_json(
            service,
            "POST",
            f"/v1/snapshots/{snapshots[service]}/restore",
            {},
        )

    restored_fields = {
        "crm": request_json("crm", "GET", "/v1/configuration")["source_field"],
        "analytics": request_json("analytics", "GET", "/v1/configuration")["source_field"],
        "support": request_json("support", "GET", "/v1/configuration")["lookup_field"],
        "catalog": request_json("catalog", "GET", "/v1/contracts/customer-api")["identifier_field"],
    }
    require(
        all(field == "customer_id" for field in restored_fields.values()),
        f"Rollback did not restore the original field: {restored_fields}",
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "tenant_id": TENANT_ID,
                "migration": "customer_id -> customer_uuid -> customer_id",
                "analytics_transient_retry": "passed",
                "idempotent_replay": "passed",
                "restored_fields": restored_fields,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
