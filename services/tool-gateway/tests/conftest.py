"""Shared Tool Gateway acceptance fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from changeops_contracts import (
    ActorType,
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
)
from changeops_core import AppEnvironment, Settings, StateTransitionService
from changeops_persistence import InMemoryChangeStateRepository
from changeops_policy_engine import IdentityKind, ToolRegistration
from changeops_sandbox.models import CrmConfiguration, FieldPatchRequest
from changeops_sandbox.seed_loader import load_seed
from changeops_sandbox.store import ConfigurationStore
from changeops_tool_gateway.app import create_app
from changeops_tool_gateway.errors import GatewayValidationError
from changeops_tool_gateway.identity import HmacIdentityVerifier
from changeops_tool_gateway.models import FieldPatchArguments
from changeops_tool_gateway.repository import InMemoryGovernanceRepository
from fastapi.testclient import TestClient
from pydantic import AnyUrl, JsonValue, ValidationError

NOW = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)
TEST_KEY_MATERIAL = "-".join(("phase5", "test", "identity", "key", "material", "32bytes"))
AUDIENCE = "enterprise-changeops-tool-gateway"


class SandboxStoreExecutor:
    def __init__(self, store: ConfigurationStore[CrmConfiguration]) -> None:
        self.store = store
        self.execution_count = 0

    def validate_arguments(self, intent: ToolIntent) -> FieldPatchArguments:
        try:
            return FieldPatchArguments.model_validate(intent.arguments)
        except ValidationError as error:
            raise GatewayValidationError from error

    async def execute(
        self,
        *,
        intent: ToolIntent,
        registration: ToolRegistration,
        arguments: FieldPatchArguments,
        request_id: str,
    ) -> dict[str, JsonValue]:
        del registration, request_id
        self.execution_count += 1
        result = self.store.apply(
            intent.tenant_id,
            FieldPatchRequest(
                old_field=arguments.old_field,
                new_field=arguments.new_field,
                idempotency_key=intent.idempotency_key,
                change_id=intent.change_id,
                plan_hash=intent.plan_hash,
            ),
        )
        return result.model_dump(mode="json")


def build_plan() -> RemediationPlan:
    return RemediationPlan(
        plan_id="plan_phase5",
        tenant_id="tenant_phase5",
        change_id="chg_phase5",
        version=1,
        risk_level=RiskLevel.HIGH,
        summary="Update the CRM identifier mapping.",
        preconditions=("sandbox healthy",),
        steps=(
            RemediationStep(
                step_id="step_crm",
                order=1,
                agent_id="crm",
                tool_name="crm.update_field_mapping",
                resource="crm://tenant/tenant_phase5/configuration/crm-sync",
                arguments={"old_field": "customer_id", "new_field": "customer_uuid"},
                depends_on=(),
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                idempotency_key="chg_phase5:crm:update-field-mapping",
            ),
        ),
        verification_steps=("verify CRM mapping",),
        rollback_steps=("restore CRM snapshot",),
        evidence_refs=("evidence://crm/mapping/v4",),
        created_at=NOW,
    )


def build_change(plan: RemediationPlan) -> ChangeRecord:
    return ChangeRecord(
        change_id=plan.change_id,
        tenant_id=plan.tenant_id,
        event_id="evt_phase5",
        change_type="api.contract.changed",
        title="Rename customer identifier",
        description="Rename customer_id to customer_uuid.",
        source=ChangeSource(
            type="github",
            external_id="pr-42",
            url=AnyUrl("https://example.invalid/pr/42"),
        ),
        environment=ChangeEnvironment.SANDBOX,
        status=WorkflowState.AWAITING_APPROVAL,
        risk_level=RiskLevel.HIGH,
        current_phase=WorkflowState.AWAITING_APPROVAL,
        workflow_execution_id="wf_phase5",
        plan_version=plan.version,
        plan_hash=calculate_plan_hash(plan),
        created_at=NOW,
        updated_at=NOW,
        created_by="workflow-coordinator",
        version=5,
    )


def build_intent(plan: RemediationPlan, *, intent_id: str = "intent_phase5") -> ToolIntent:
    step = plan.steps[0]
    return ToolIntent(
        schema_version="1.0",
        intent_id=intent_id,
        tenant_id=plan.tenant_id,
        change_id=plan.change_id,
        workflow_execution_id="wf_phase5",
        plan_id=plan.plan_id,
        plan_hash=calculate_plan_hash(plan),
        step_id=step.step_id,
        agent_identity=step.agent_id,
        tool_name=step.tool_name,
        action="update",
        resource=step.resource,
        arguments=step.arguments,
        reason="Apply approved sandbox migration.",
        evidence_refs=("evidence://crm/mapping/v4",),
        idempotency_key=step.idempotency_key,
        requested_at=NOW,
    )


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Request-ID": "req_phase5"}


@pytest.fixture
def gateway_stack() -> dict[str, Any]:
    plan = build_plan()
    changes = InMemoryChangeStateRepository()
    changes.add(build_change(plan))
    governance = InMemoryGovernanceRepository()
    verifier = HmacIdentityVerifier(TEST_KEY_MATERIAL, AUDIENCE, clock=lambda: NOW)
    sandbox_store = ConfigurationStore(
        load_seed("crm.json", CrmConfiguration),
        CrmConfiguration,
        field_name="source_field",
    )
    executor = SandboxStoreExecutor(sandbox_store)
    app = create_app(
        settings=Settings(app_env=AppEnvironment.SANDBOX),
        identity_verifier=verifier,
        governance_repository=governance,
        change_repository=changes,
        tool_executor=executor,
        clock=lambda: NOW,
    )
    tokens = {
        "service": verifier.issue(
            subject="workflow-coordinator",
            tenant_id=plan.tenant_id,
            kind=IdentityKind.SERVICE,
        ),
        "approver": verifier.issue(
            subject="user_approver",
            tenant_id=plan.tenant_id,
            kind=IdentityKind.USER,
            roles=(UserRole.APPROVER.value,),
        ),
        "auditor": verifier.issue(
            subject="user_auditor",
            tenant_id=plan.tenant_id,
            kind=IdentityKind.USER,
            roles=(UserRole.AUDITOR.value,),
        ),
        "crm": verifier.issue(
            subject="crm",
            tenant_id=plan.tenant_id,
            kind=IdentityKind.AGENT,
        ),
        "other_tenant": verifier.issue(
            subject="crm",
            tenant_id="tenant_other",
            kind=IdentityKind.AGENT,
        ),
    }
    return {
        "app": app,
        "plan": plan,
        "changes": changes,
        "governance": governance,
        "executor": executor,
        "sandbox_store": sandbox_store,
        "tokens": tokens,
    }


def approve_and_start(stack: dict[str, Any]) -> None:
    plan: RemediationPlan = stack["plan"]
    tokens: dict[str, str] = stack["tokens"]
    with TestClient(stack["app"]) as client:
        created = client.post(
            "/v1/approvals",
            headers=authorization(tokens["service"]),
            json={
                "approval_id": "approval_phase5",
                "plan": plan.model_dump(mode="json"),
                "environment": "sandbox",
                "scope": ["step_crm"],
                "expires_at": (NOW + timedelta(minutes=30)).isoformat(),
            },
        )
        assert created.status_code == 201, created.text
        approved = client.post(
            "/v1/approvals/approval_phase5/approve",
            headers=authorization(tokens["approver"]),
            json={"expected_version": 1, "comment": "Approved for sandbox execution."},
        )
        assert approved.status_code == 200, approved.text

    transitions = StateTransitionService(stack["changes"], clock=lambda: NOW)
    approved_change = transitions.transition(
        tenant_id=plan.tenant_id,
        change_id=plan.change_id,
        target=WorkflowState.APPROVED,
        expected_version=5,
        trace_id="wf_phase5",
        actor_type=ActorType.USER,
        actor_id="user_approver",
    )
    transitions.transition(
        tenant_id=plan.tenant_id,
        change_id=plan.change_id,
        target=WorkflowState.EXECUTING,
        expected_version=approved_change.version,
        trace_id="wf_phase5",
        actor_type=ActorType.SERVICE,
        actor_id="workflow-coordinator",
    )
