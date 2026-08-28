"""Fail-closed deterministic evaluation of a governed tool intent."""

from __future__ import annotations

from datetime import UTC, datetime
from fnmatch import fnmatchcase
from uuid import uuid4

from changeops_contracts import (
    Approval,
    ApprovalDecision,
    ChangeRecord,
    PolicyDecision,
    PolicyEffect,
    RemediationPlan,
    RiskLevel,
    ToolIntent,
    UserRole,
    WorkflowState,
    calculate_plan_hash,
)

from changeops_policy_engine.models import IdentityKind, ToolRegistration, VerifiedIdentity

_RISK_ORDER = {
    RiskLevel.UNKNOWN: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


class PolicyEngine:
    """Evaluate all authorization inputs without consulting model output."""

    def evaluate(
        self,
        *,
        identity: VerifiedIdentity,
        intent: ToolIntent,
        change: ChangeRecord,
        plan: RemediationPlan,
        tool: ToolRegistration,
        approval: Approval | None,
        now: datetime | None = None,
    ) -> PolicyDecision:
        evaluated_at = now or datetime.now(UTC)
        failures: list[str] = []
        effect = PolicyEffect.DENY

        if identity.expires_at <= evaluated_at:
            failures.append("Authenticated identity is expired.")
        if identity.kind is not IdentityKind.AGENT:
            failures.append("Only an authenticated agent may submit a tool intent.")
        if identity.subject != intent.agent_identity:
            failures.append("Intent identity does not match the authenticated caller.")
        if identity.tenant_id != intent.tenant_id:
            failures.append("Intent tenant does not match the authenticated caller.")
        if change.tenant_id != intent.tenant_id or change.change_id != intent.change_id:
            failures.append("Intent does not match the authoritative change scope.")
        if change.workflow_execution_id != intent.workflow_execution_id:
            failures.append("Intent does not match the active workflow execution.")
        if change.status is not WorkflowState.EXECUTING:
            failures.append("Workflow state does not permit tool execution.")
        if change.plan_version != plan.version or change.plan_hash != intent.plan_hash:
            failures.append("Intent does not match the authoritative change plan.")
        if plan.tenant_id != intent.tenant_id or plan.change_id != intent.change_id:
            failures.append("Plan does not match the intent scope.")
        if plan.plan_id != intent.plan_id or calculate_plan_hash(plan) != intent.plan_hash:
            failures.append("Plan identifier or canonical hash does not match the intent.")

        step = next(
            (candidate for candidate in plan.steps if candidate.step_id == intent.step_id),
            None,
        )
        if step is None:
            failures.append("Intent step is not present in the approved plan.")
            step_risk = RiskLevel.UNKNOWN
            approval_required = tool.mutating
        else:
            step_risk = step.risk_level
            approval_required = step.requires_approval or tool.mutating
            if step.agent_id != intent.agent_identity:
                failures.append("Intent agent does not own the selected plan step.")
            if step.tool_name != intent.tool_name or step.tool_name != tool.tool_name:
                failures.append("Intent tool does not match the selected plan step.")
            if step.resource != intent.resource:
                failures.append("Intent resource does not match the selected plan step.")
            if step.arguments != intent.arguments:
                failures.append("Intent arguments do not match the selected plan step.")
            if step.idempotency_key != intent.idempotency_key:
                failures.append("Intent idempotency key does not match the selected plan step.")

        computed_risk = max((tool.risk_level, step_risk), key=_RISK_ORDER.__getitem__)
        expected_resource = tool.resource_pattern.format(tenant_id=intent.tenant_id)
        if tool.owning_agent_id != intent.agent_identity:
            failures.append("Agent is not authorized for this registered tool.")
        if tool.action != intent.action:
            failures.append("Intent action does not match the registered tool action.")
        if not fnmatchcase(intent.resource, expected_resource):
            failures.append("Intent resource is outside the registered agent scope.")
        if change.environment not in tool.allowed_environments:
            failures.append("Tool is not allowed in the authoritative change environment.")
            if tool.mutating:
                effect = PolicyEffect.BLOCK_SECURITY
        if computed_risk is RiskLevel.CRITICAL:
            failures.append("Critical-risk mutations are disabled in this build.")
            effect = PolicyEffect.BLOCK_SECURITY

        approval_valid = self._approval_valid(
            approval=approval,
            intent=intent,
            change=change,
            plan=plan,
            evaluated_at=evaluated_at,
        )
        if approval_required and not approval_valid:
            failures.append("A current exact-plan approval is required for this step.")
            if effect is not PolicyEffect.BLOCK_SECURITY:
                effect = PolicyEffect.REQUIRE_APPROVAL

        if not failures:
            effect = PolicyEffect.ALLOW
            reasons: tuple[str, ...] = (
                "Authenticated agent, tenant, tool, resource, workflow, and plan scope match.",
                "Exact-plan approval is current and covers the selected step.",
            )
        else:
            reasons = tuple(failures)

        return PolicyDecision(
            decision_id=f"decision_{uuid4().hex}",
            tenant_id=intent.tenant_id,
            intent_id=intent.intent_id,
            effect=effect,
            computed_risk=computed_risk,
            approval_required=approval_required,
            approval_valid=approval_valid,
            matched_policy_ids=tool.policy_ids,
            reasons=reasons,
            evaluated_at=evaluated_at,
        )

    @staticmethod
    def _approval_valid(
        *,
        approval: Approval | None,
        intent: ToolIntent,
        change: ChangeRecord,
        plan: RemediationPlan,
        evaluated_at: datetime,
    ) -> bool:
        if approval is None:
            return False
        return (
            approval.decision is ApprovalDecision.APPROVED
            and approval.tenant_id == intent.tenant_id
            and approval.change_id == intent.change_id
            and approval.plan_id == intent.plan_id == plan.plan_id
            and approval.plan_hash == intent.plan_hash == calculate_plan_hash(plan)
            and approval.plan_version == plan.version == change.plan_version
            and approval.environment == change.environment
            and intent.step_id in approval.scope
            and approval.expires_at > evaluated_at
            and approval.approved_at <= evaluated_at
            and bool({UserRole.APPROVER, UserRole.PLATFORM_ADMIN} & set(approval.approved_by_roles))
            and approval.approved_by != intent.agent_identity
        )
