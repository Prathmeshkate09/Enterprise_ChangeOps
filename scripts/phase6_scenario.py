"""Live Pub/Sub, durable workflow, retry, DLQ, and rollback Phase 6 gate."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from changeops_contracts import (
    ChangeDetails,
    ChangeEvent,
    ChangeSource,
    ChangeSubject,
    UserRole,
    derive_workflow_id,
)
from changeops_policy_engine import IdentityKind
from changeops_tool_gateway.identity import HmacIdentityVerifier
from pydantic import AnyUrl

EVENT_GATEWAY_URL = os.environ.get("EVENT_GATEWAY_URL", "http://127.0.0.1:8400").rstrip("/")
WORKFLOW_URL = os.environ.get("WORKFLOW_COORDINATOR_URL", "http://127.0.0.1:8500").rstrip("/")
TOOL_GATEWAY_URL = os.environ.get("TOOL_GATEWAY_URL", "http://127.0.0.1:8300").rstrip("/")
CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://127.0.0.1:8000").rstrip("/")
SANDBOX_URLS = {
    "catalog": os.environ.get("CATALOG_BASE_URL", "http://127.0.0.1:8100").rstrip("/"),
    "crm": os.environ.get("CRM_BASE_URL", "http://127.0.0.1:8101").rstrip("/"),
    "analytics": os.environ.get("ANALYTICS_BASE_URL", "http://127.0.0.1:8102").rstrip("/"),
    "support": os.environ.get("SUPPORT_BASE_URL", "http://127.0.0.1:8103").rstrip("/"),
}
WEBHOOK_KEY = os.environ.get(
    "EVENT_GATEWAY_WEBHOOK_SECRET", "local-changeops-event-webhook-secret-2026"
)
IDENTITY_KEY = os.environ.get(
    "TOOL_GATEWAY_AUTH_SECRET", "local-changeops-tool-gateway-secret-2026"
)
AUDIENCE = os.environ.get("AUTH_AUDIENCE", "enterprise-changeops-tool-gateway")


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    tenant_id: str | None = None,
    payload: dict[str, Any] | None = None,
    raw_body: bytes | None = None,
    headers: dict[str, str] | None = None,
    expected_status: int = 200,
    timeout: float = 90,
) -> dict[str, Any]:
    request_headers = {"X-Request-ID": f"req_phase6_{uuid4().hex}"}
    if headers is not None:
        request_headers.update(headers)
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    if tenant_id is not None:
        request_headers["X-Tenant-ID"] = tenant_id
    data = raw_body
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(payload, separators=(",", ":")).encode()
    request = urllib.request.Request(  # noqa: S310 - fixed local acceptance endpoints.
        url,
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            status_code = response.status
            response_body = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        status_code = error.code
        response_body = json.loads(error.read().decode())
    if status_code != expected_status:
        raise AssertionError(
            f"{method} {url} returned {status_code}, expected {expected_status}: {response_body}"
        )
    if not isinstance(response_body, dict):
        raise AssertionError(f"{method} {url} returned a non-object response")
    return response_body


def build_event(*, tenant_id: str, event_id: str, event_type: str) -> ChangeEvent:
    timestamp = datetime.now(UTC)
    return ChangeEvent(
        schema_version="1.0",
        event_id=event_id,
        tenant_id=tenant_id,
        event_type=event_type,
        source=ChangeSource(
            type="github",
            external_id=f"pr-{event_id}",
            url=AnyUrl("https://example.invalid/changeops/phase6"),
        ),
        occurred_at=timestamp,
        received_at=timestamp,
        subject=ChangeSubject(
            system_id="customer-api",
            resource_type="api-contract",
            resource_id="customer-api-v2",
        ),
        change=ChangeDetails(
            summary="Rename customer_id to customer_uuid",
            old_version="1.4.0",
            new_version="2.0.0",
            artifact_refs=("artifact://contracts/customer-v2-diff.json",),
        ),
        correlation_id=f"correlation-{event_id}",
        trace_id=f"trace-{event_id}",
    )


def publish(event: ChangeEvent) -> dict[str, Any]:
    body = event.model_dump_json().encode()
    signature = hmac.new(WEBHOOK_KEY.encode(), body, hashlib.sha256).hexdigest()
    return request_json(
        "POST",
        f"{EVENT_GATEWAY_URL}/v1/events/change",
        raw_body=body,
        headers={
            "Content-Type": "application/json",
            "X-ChangeOps-Signature": f"sha256={signature}",
        },
        expected_status=202,
    )


def workflow(event: ChangeEvent, change_id: str) -> dict[str, Any]:
    workflow_id = derive_workflow_id(event)
    query = urllib.parse.urlencode({"change_id": change_id})
    return request_json(
        "GET",
        f"{WORKFLOW_URL}/v1/workflows/{workflow_id}?{query}",
        tenant_id=event.tenant_id,
    )


def wait_for_workflow(
    event: ChangeEvent,
    change_id: str,
    statuses: set[str],
    *,
    timeout_seconds: float = 120,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            current = workflow(event, change_id)
            if current["status"] in statuses:
                return current
            last_error = AssertionError(f"workflow status is {current['status']}")
        except (AssertionError, OSError, TimeoutError) as error:
            last_error = error
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for workflow states {statuses}: {last_error}")


def wait_for_health(url: str, *, timeout_seconds: float = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = request_json("GET", url, timeout=3)
            if result.get("status") in {"ok", "ready"}:
                return
        except (AssertionError, OSError, TimeoutError) as error:
            last_error = error
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {url}: {last_error}")


def reset_tenant(tenant_id: str) -> None:
    for base_url in SANDBOX_URLS.values():
        result = request_json(
            "POST",
            f"{base_url}/v1/admin/reset",
            tenant_id=tenant_id,
            payload={},
        )
        assert result["reset"] is True


def approver_token(tenant_id: str) -> str:
    issuer = HmacIdentityVerifier(IDENTITY_KEY, AUDIENCE)
    return issuer.issue(
        subject="user_phase6_approver",
        tenant_id=tenant_id,
        kind=IdentityKind.USER,
        roles=(UserRole.APPROVER.value,),
    )


def auditor_token(tenant_id: str) -> str:
    issuer = HmacIdentityVerifier(IDENTITY_KEY, AUDIENCE)
    return issuer.issue(
        subject="user_phase6_auditor",
        tenant_id=tenant_id,
        kind=IdentityKind.USER,
        roles=(UserRole.AUDITOR.value,),
    )


def approve(waiting: dict[str, Any]) -> dict[str, Any]:
    approval_id = waiting["approval_id"]
    return request_json(
        "POST",
        f"{TOOL_GATEWAY_URL}/v1/approvals/{approval_id}/approve",
        token=approver_token(str(waiting["tenant_id"])),
        payload={
            "expected_version": 1,
            "comment": "Approved for the Phase 6 sandbox acceptance gate.",
        },
        timeout=120,
    )


def restart_coordinator() -> None:
    if os.environ.get("PHASE6_SKIP_RESTART", "false").lower() == "true":
        return
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker is required for the restart durability gate.")
    subprocess.run(  # noqa: S603 - fixed Docker Compose restart command.
        [docker, "compose", "restart", "workflow-coordinator"],
        check=True,
    )
    wait_for_health(f"{WORKFLOW_URL}/health/ready")


def assert_configuration(tenant_id: str, expected_field: str) -> None:
    expected_keys = {"crm": "source_field", "analytics": "source_field", "support": "lookup_field"}
    for system, key in expected_keys.items():
        configuration = request_json(
            "GET",
            f"{SANDBOX_URLS[system]}/v1/configuration",
            tenant_id=tenant_id,
        )
        assert configuration[key] == expected_field


def successful_workflow(run_id: str) -> None:
    tenant_id = f"tenant_phase6_success_{run_id}"
    reset_tenant(tenant_id)
    request_json(
        "POST",
        f"{SANDBOX_URLS['analytics']}/v1/admin/transient-failures",
        tenant_id=tenant_id,
        payload={"count": 1},
    )
    event = build_event(
        tenant_id=tenant_id,
        event_id=f"evt_phase6_success_{run_id}",
        event_type="api.contract.changed",
    )
    accepted = publish(event)
    waiting = wait_for_workflow(event, str(accepted["change_id"]), {"WAITING_APPROVAL"})

    restart_coordinator()
    after_restart = workflow(event, str(accepted["change_id"]))
    assert after_restart["status"] == "WAITING_APPROVAL"
    assert after_restart["approval_id"] == waiting["approval_id"]

    approve(after_restart)
    completed = wait_for_workflow(event, str(accepted["change_id"]), {"COMPLETED"})
    attempts = {task["system_id"]: task["attempt_count"] for task in completed["tasks"]}
    assert attempts == {"crm": 1, "analytics": 2, "support": 1}
    assert_configuration(tenant_id, "customer_uuid")

    duplicate = publish(event)
    assert duplicate["replayed"] is True
    duplicate_workflow = workflow(event, str(accepted["change_id"]))
    assert duplicate_workflow["version"] == completed["version"]
    audit = request_json(
        "GET",
        f"{TOOL_GATEWAY_URL}/v1/audit?limit=100",
        token=auditor_token(tenant_id),
    )
    success_events = [
        item for item in audit["items"] if item["event_type"] == "TOOL_EXECUTION_SUCCEEDED"
    ]
    failure_events = [
        item for item in audit["items"] if item["event_type"] == "TOOL_EXECUTION_FAILED"
    ]
    assert len(success_events) == 3
    assert len(failure_events) == 1

    change_audit = request_json(
        "GET",
        f"{CONTROL_API_URL}/v1/changes/{accepted['change_id']}/audit",
        tenant_id=tenant_id,
    )
    event_types = {item["event_type"] for item in change_audit["items"]}
    assert {
        "WORKFLOW_STEP_RETRY_SCHEDULED",
        "WORKFLOW_VERIFICATION_SUCCEEDED",
    }.issubset(event_types)


def rollback_workflow(run_id: str) -> None:
    tenant_id = f"tenant_phase6_rollback_{run_id}"
    reset_tenant(tenant_id)
    request_json(
        "POST",
        f"{SANDBOX_URLS['support']}/v1/admin/verification-failures",
        tenant_id=tenant_id,
        payload={"count": 1},
    )
    event = build_event(
        tenant_id=tenant_id,
        event_id=f"evt_phase6_rollback_{run_id}",
        event_type="api.contract.changed",
    )
    accepted = publish(event)
    waiting = wait_for_workflow(event, str(accepted["change_id"]), {"WAITING_APPROVAL"})
    approve(waiting)
    failed = wait_for_workflow(event, str(accepted["change_id"]), {"FAILED"})

    assert failed["last_error_code"] == "SUPPORT_VERIFICATION_FAILED"
    assert all(task["status"] == "ROLLED_BACK" for task in failed["tasks"])
    assert_configuration(tenant_id, "customer_id")


def permanent_failure(run_id: str) -> None:
    tenant_id = f"tenant_phase6_permanent_{run_id}"
    event = build_event(
        tenant_id=tenant_id,
        event_id=f"evt_phase6_permanent_{run_id}",
        event_type="unsupported.contract.changed",
    )
    accepted = publish(event)
    dead = wait_for_workflow(event, str(accepted["change_id"]), {"DEAD_LETTERED"})
    assert dead["delivery_attempts"] == 1
    assert dead["last_error_code"] == "UNSUPPORTED_EVENT_TYPE"
    duplicate = publish(event)
    assert duplicate["replayed"] is True
    time.sleep(1)
    assert workflow(event, str(accepted["change_id"]))["delivery_attempts"] == 1
    dead_letters = request_json(
        "GET",
        f"{WORKFLOW_URL}/v1/dead-letters?limit=10",
        tenant_id=tenant_id,
    )
    assert dead_letters["count"] == 1


def main() -> None:
    run_id = os.environ.get("PHASE6_RUN_ID", uuid4().hex[:12])
    successful_workflow(run_id)
    rollback_workflow(run_id)
    permanent_failure(run_id)
    print(
        "Phase 6 gate passed: the workflow survived a coordinator restart, retried one "
        "transient failure, completed without duplicate writes, restored all snapshots "
        "after a verification failure, and dead-lettered a permanent event once.",
        flush=True,
    )


if __name__ == "__main__":
    main()
