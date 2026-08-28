"""Live Firestore and sandbox acceptance gate for Phase 5 governance."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from changeops_contracts import (
    ActorType,
    AuditEvent,
    AuditStatus,
    ChangeEnvironment,
    ChangeRecord,
    ChangeSource,
    RemediationPlan,
    RemediationStep,
    RiskLevel,
    ToolIntent,
    UserRole,
    WorkflowState,
    calculate_plan_hash,
    sha256_digest,
)
from changeops_core import StateTransitionService
from changeops_persistence import FirestoreChangeStateRepository
from changeops_policy_engine import IdentityKind
from changeops_tool_gateway.identity import HmacIdentityVerifier
from pydantic import AnyUrl

GATEWAY_URL = os.environ.get("TOOL_GATEWAY_URL", "http://127.0.0.1:8300").rstrip("/")
CRM_URL = os.environ.get("CRM_BASE_URL", "http://127.0.0.1:8101").rstrip("/")
AUDIENCE = os.environ.get("AUTH_AUDIENCE", "enterprise-changeops-tool-gateway")


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    tenant_id: str | None = None,
    payload: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    headers = {"X-Request-ID": "req_phase5_live"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if tenant_id is not None:
        headers["X-Tenant-ID"] = tenant_id
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - URLs are fixed local gate endpoints.
        url, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            status_code = response.status
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        status_code = error.code
        body = json.loads(error.read().decode("utf-8"))
    if status_code != expected_status:
        raise AssertionError(
            f"{method} {url} returned {status_code}, expected {expected_status}: {body}"
        )
    if not isinstance(body, dict):
        raise AssertionError(f"{method} {url} returned a non-object response")
    return body


def build_plan(tenant_id: str, change_id: str, timestamp: datetime) -> RemediationPlan:
    return RemediationPlan(
        plan_id=f"plan_{change_id}",
        tenant_id=tenant_id,
        change_id=change_id,
        version=1,
        risk_level=RiskLevel.HIGH,
        summary="Update the CRM customer identifier mapping.",
        preconditions=("CRM sandbox is healthy",),
        steps=(
            RemediationStep(
                step_id="step_crm",
                order=1,
                agent_id="crm",
                tool_name="crm.update_field_mapping",
                resource=f"crm://tenant/{tenant_id}/configuration/crm-sync",
                arguments={"old_field": "customer_id", "new_field": "customer_uuid"},
                depends_on=(),
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                idempotency_key=f"{change_id}:crm:update-field-mapping",
            ),
        ),
        verification_steps=("verify CRM synchronization mapping",),
        rollback_steps=("restore CRM configuration snapshot",),
        evidence_refs=("evidence://crm/mapping/v4",),
        created_at=timestamp,
    )


def build_change(plan: RemediationPlan, timestamp: datetime) -> tuple[ChangeRecord, AuditEvent]:
    plan_hash = calculate_plan_hash(plan)
    change = ChangeRecord(
        change_id=plan.change_id,
        tenant_id=plan.tenant_id,
        event_id=f"evt_{plan.change_id}",
        change_type="api.contract.changed",
        title="Rename customer identifier",
        description="Rename customer_id to customer_uuid.",
        source=ChangeSource(
            type="simulator",
            external_id=f"source_{plan.change_id}",
            url=AnyUrl("https://example.invalid/phase5"),
        ),
        environment=ChangeEnvironment.SANDBOX,
        status=WorkflowState.AWAITING_APPROVAL,
        risk_level=RiskLevel.HIGH,
        current_phase=WorkflowState.AWAITING_APPROVAL,
        workflow_execution_id=f"wf_{plan.change_id}",
        plan_version=plan.version,
        plan_hash=plan_hash,
        created_at=timestamp,
        updated_at=timestamp,
        created_by="phase5-live-gate",
        version=5,
    )
    audit = AuditEvent(
        audit_event_id=f"audit_{plan.change_id}_awaiting",
        tenant_id=plan.tenant_id,
        change_id=plan.change_id,
        trace_id=change.workflow_execution_id or "wf_missing",
        event_type="CHANGE_AWAITING_APPROVAL",
        actor_type=ActorType.SERVICE,
        actor_id="phase5-live-gate",
        resource=f"changes/{plan.change_id}",
        action="seed_phase5_gate",
        input_hash=sha256_digest({"change_id": plan.change_id}),
        output_hash=sha256_digest(change),
        status=AuditStatus.SUCCESS,
        redacted_summary="Phase 5 live gate change seeded.",
        created_at=timestamp,
    )
    return change, audit


def build_intent(plan: RemediationPlan, *, intent_id: str) -> ToolIntent:
    step = plan.steps[0]
    return ToolIntent(
        schema_version="1.0",
        intent_id=intent_id,
        tenant_id=plan.tenant_id,
        change_id=plan.change_id,
        workflow_execution_id=f"wf_{plan.change_id}",
        plan_id=plan.plan_id,
        plan_hash=calculate_plan_hash(plan),
        step_id=step.step_id,
        agent_identity=step.agent_id,
        tool_name=step.tool_name,
        action="update",
        resource=step.resource,
        arguments=step.arguments,
        reason="Apply the approved sandbox migration.",
        evidence_refs=("evidence://crm/mapping/v4",),
        idempotency_key=step.idempotency_key,
        requested_at=datetime.now(UTC),
    )


def main() -> None:
    tenant_id = os.environ["PHASE5_TENANT_ID"]
    signing_key = os.environ["TOOL_GATEWAY_AUTH_SECRET"]
    timestamp = datetime.now(UTC) - timedelta(seconds=2)
    change_id = f"chg_{tenant_id.removeprefix('tenant_')}"
    plan = build_plan(tenant_id, change_id, timestamp)
    change, audit = build_change(plan, timestamp)

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "changeops-local")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    repository = FirestoreChangeStateRepository.from_project(project, database)
    repository.add_with_audit(change, audit)

    verifier = HmacIdentityVerifier(signing_key, AUDIENCE)
    service_token = verifier.issue(
        subject="workflow-coordinator",
        tenant_id=tenant_id,
        kind=IdentityKind.SERVICE,
    )
    approver_token = verifier.issue(
        subject="user_phase5_approver",
        tenant_id=tenant_id,
        kind=IdentityKind.USER,
        roles=(UserRole.APPROVER.value,),
    )
    auditor_token = verifier.issue(
        subject="user_phase5_auditor",
        tenant_id=tenant_id,
        kind=IdentityKind.USER,
        roles=(UserRole.AUDITOR.value,),
    )
    agent_token = verifier.issue(
        subject="crm",
        tenant_id=tenant_id,
        kind=IdentityKind.AGENT,
    )

    request_json(
        "POST",
        f"{GATEWAY_URL}/v1/approvals",
        token=service_token,
        payload={
            "approval_id": f"approval_{change_id}",
            "plan": plan.model_dump(mode="json"),
            "environment": "sandbox",
            "scope": ["step_crm"],
            "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        },
        expected_status=201,
    )
    request_json(
        "POST",
        f"{GATEWAY_URL}/v1/approvals/approval_{change_id}/approve",
        token=approver_token,
        payload={"expected_version": 1, "comment": "Approved for live sandbox gate."},
    )

    transitions = StateTransitionService(repository)
    approved = transitions.transition(
        tenant_id=tenant_id,
        change_id=change_id,
        target=WorkflowState.APPROVED,
        expected_version=5,
        trace_id=f"wf_{change_id}",
        actor_type=ActorType.USER,
        actor_id="user_phase5_approver",
    )
    transitions.transition(
        tenant_id=tenant_id,
        change_id=change_id,
        target=WorkflowState.EXECUTING,
        expected_version=approved.version,
        trace_id=f"wf_{change_id}",
        actor_type=ActorType.SERVICE,
        actor_id="workflow-coordinator",
    )

    intent = build_intent(plan, intent_id=f"intent_{change_id}_first")
    blocked = request_json(
        "POST",
        f"{GATEWAY_URL}/internal/v1/tool-intents/evaluate-and-execute",
        token=agent_token,
        payload={"intent": intent.model_dump(mode="json")},
        expected_status=409,
    )
    assert blocked["code"] == "APPROVAL_REQUIRED"
    before = request_json("GET", f"{CRM_URL}/v1/configuration", tenant_id=tenant_id)
    assert before["source_field"] == "customer_id"

    first = request_json(
        "POST",
        f"{GATEWAY_URL}/internal/v1/tool-intents/evaluate-and-execute",
        token=agent_token,
        payload={
            "intent": intent.model_dump(mode="json"),
            "approval_id": f"approval_{change_id}",
        },
    )
    duplicate = build_intent(plan, intent_id=f"intent_{change_id}_duplicate")
    replay = request_json(
        "POST",
        f"{GATEWAY_URL}/internal/v1/tool-intents/evaluate-and-execute",
        token=agent_token,
        payload={
            "intent": duplicate.model_dump(mode="json"),
            "approval_id": f"approval_{change_id}",
        },
    )
    after = request_json("GET", f"{CRM_URL}/v1/configuration", tenant_id=tenant_id)
    assert first["replayed"] is False
    assert replay["replayed"] is True
    assert first["execution_id"] == replay["execution_id"]
    assert after["source_field"] == "customer_uuid"
    assert after["schema_version"] == before["schema_version"] + 1

    old_intent = intent.model_dump(mode="json")
    old_intent["plan_hash"] = f"sha256:{'0' * 64}"
    old_plan = request_json(
        "POST",
        f"{GATEWAY_URL}/internal/v1/tool-intents/evaluate-and-execute",
        token=agent_token,
        payload={
            "intent": old_intent,
            "approval_id": f"approval_{change_id}",
        },
        expected_status=409,
    )
    assert old_plan["code"] == "APPROVAL_REQUIRED"
    audit_response = request_json("GET", f"{GATEWAY_URL}/v1/audit?limit=100", token=auditor_token)
    event_types = {item["event_type"] for item in audit_response["items"]}
    assert {
        "APPROVAL_REQUESTED",
        "APPROVAL_GRANTED",
        "TOOL_POLICY_DENIED",
        "TOOL_EXECUTION_SUCCEEDED",
        "TOOL_EXECUTION_REPLAYED",
    }.issubset(event_types)
    print(
        "Phase 5 gate passed: unapproved and stale-plan writes were blocked, "
        "the exact approved plan changed CRM sandbox state, and a duplicate intent "
        "replayed without a second mutation.",
        flush=True,
    )


if __name__ == "__main__":
    main()
