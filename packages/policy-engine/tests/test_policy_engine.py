"""Deterministic RBAC/ABAC, risk, and exact-plan approval tests."""

from datetime import UTC, datetime, timedelta

from changeops_contracts import (
    Approval,
    ApprovalDecision,
    ChangeEnvironment,
    ChangeRecord,
    ChangeSource,
    PolicyEffect,
    RemediationPlan,
    RemediationStep,
    RiskLevel,
    ToolIntent,
    UserRole,
    WorkflowState,
    calculate_plan_hash,
)
from changeops_policy_engine import (
    IdentityKind,
    PolicyEngine,
    VerifiedIdentity,
    build_default_tool_registry,
)
from pydantic import AnyUrl

NOW = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)


def make_plan() -> RemediationPlan:
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


def make_change(plan: RemediationPlan) -> ChangeRecord:
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
        status=WorkflowState.EXECUTING,
        risk_level=RiskLevel.HIGH,
        current_phase=WorkflowState.EXECUTING,
        workflow_execution_id="wf_phase5",
        plan_version=plan.version,
        plan_hash=calculate_plan_hash(plan),
        created_at=NOW,
        updated_at=NOW,
        created_by="workflow-coordinator",
        version=7,
    )


def make_intent(plan: RemediationPlan) -> ToolIntent:
    step = plan.steps[0]
    return ToolIntent(
        schema_version="1.0",
        intent_id="intent_phase5",
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


def make_identity() -> VerifiedIdentity:
    return VerifiedIdentity(
        subject="crm",
        tenant_id="tenant_phase5",
        kind=IdentityKind.AGENT,
        audience="gateway",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=15),
    )


def make_approval(plan: RemediationPlan, *, plan_hash: str | None = None) -> Approval:
    return Approval(
        approval_id="approval_phase5",
        tenant_id=plan.tenant_id,
        change_id=plan.change_id,
        plan_id=plan.plan_id,
        plan_hash=plan_hash or calculate_plan_hash(plan),
        plan_version=plan.version,
        environment=ChangeEnvironment.SANDBOX,
        decision=ApprovalDecision.APPROVED,
        scope=(plan.steps[0].step_id,),
        approved_by="user_approver",
        approved_by_roles=(UserRole.APPROVER,),
        approved_at=NOW - timedelta(seconds=30),
        expires_at=NOW + timedelta(minutes=30),
        comment="Approved for sandbox execution.",
    )


def evaluate(approval: Approval | None, *, intent: ToolIntent | None = None):  # type: ignore[no-untyped-def]
    plan = make_plan()
    selected_intent = intent or make_intent(plan)
    tool = build_default_tool_registry().get(selected_intent.tool_name)
    assert tool is not None
    return PolicyEngine().evaluate(
        identity=make_identity(),
        intent=selected_intent,
        change=make_change(plan),
        plan=plan,
        tool=tool,
        approval=approval,
        now=NOW,
    )


def test_exact_plan_approval_allows_registered_sandbox_write() -> None:
    plan = make_plan()
    decision = evaluate(make_approval(plan))

    assert decision.effect is PolicyEffect.ALLOW
    assert decision.computed_risk is RiskLevel.HIGH
    assert decision.approval_valid is True


def test_missing_approval_fails_closed() -> None:
    decision = evaluate(None)

    assert decision.effect is PolicyEffect.REQUIRE_APPROVAL
    assert decision.approval_valid is False


def test_old_plan_approval_fails_closed() -> None:
    plan = make_plan()
    decision = evaluate(make_approval(plan, plan_hash=f"sha256:{'0' * 64}"))

    assert decision.effect is PolicyEffect.REQUIRE_APPROVAL
    assert decision.approval_valid is False


def test_arguments_not_bound_to_plan_are_denied() -> None:
    plan = make_plan()
    intent_document = make_intent(plan).model_dump(mode="python")
    intent_document["arguments"] = {
        "old_field": "customer_id",
        "new_field": "attacker_selected_field",
    }
    decision = evaluate(make_approval(plan), intent=ToolIntent.model_validate(intent_document))

    assert decision.effect is PolicyEffect.DENY
    assert any("arguments" in reason for reason in decision.reasons)
