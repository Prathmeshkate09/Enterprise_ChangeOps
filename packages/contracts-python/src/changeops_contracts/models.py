"""Pydantic contracts matching specification section 5."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AnyUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

NonEmptyStr = Annotated[str, Field(min_length=1, max_length=512)]
Reference = Annotated[str, Field(min_length=1, max_length=2048)]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class ContractModel(BaseModel):
    """Fail-closed base for immutable wire contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class RiskLevel(StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ChangeEnvironment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    SANDBOX = "sandbox"


class WorkflowState(StrEnum):
    RECEIVED = "RECEIVED"
    SCREENING = "SCREENING"
    BLOCKED = "BLOCKED"
    ANALYZING = "ANALYZING"
    PLAN_READY = "PLAN_READY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    ROLLING_BACK = "ROLLING_BACK"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class PolicyEffect(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    BLOCK_SECURITY = "BLOCK_SECURITY"
    RATE_LIMIT = "RATE_LIMIT"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    SERVICE = "service"
    SYSTEM = "system"


class AuditStatus(StrEnum):
    SUCCESS = "success"
    REJECTED = "rejected"
    FAILURE = "failure"


class AgentStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class EvidenceTrust(StrEnum):
    PLATFORM = "platform"
    UNTRUSTED = "untrusted"


class ChangeSource(ContractModel):
    type: NonEmptyStr
    external_id: NonEmptyStr
    url: AnyUrl


class ChangeSubject(ContractModel):
    system_id: NonEmptyStr
    resource_type: NonEmptyStr
    resource_id: NonEmptyStr


class ChangeDetails(ContractModel):
    summary: NonEmptyStr
    old_version: NonEmptyStr
    new_version: NonEmptyStr
    artifact_refs: tuple[Reference, ...] = Field(min_length=1)


class ChangeEvent(ContractModel):
    schema_version: Literal["1.0"]
    event_id: NonEmptyStr
    tenant_id: NonEmptyStr
    event_type: NonEmptyStr
    source: ChangeSource
    occurred_at: AwareDatetime
    received_at: AwareDatetime
    subject: ChangeSubject
    change: ChangeDetails
    correlation_id: NonEmptyStr
    trace_id: NonEmptyStr


class ChangeRecord(ContractModel):
    change_id: NonEmptyStr
    tenant_id: NonEmptyStr
    event_id: NonEmptyStr
    change_type: NonEmptyStr
    title: NonEmptyStr
    description: NonEmptyStr
    source: ChangeSource
    environment: ChangeEnvironment
    status: WorkflowState
    risk_level: RiskLevel
    current_phase: WorkflowState
    workflow_execution_id: NonEmptyStr | None
    plan_version: int = Field(ge=0)
    plan_hash: Sha256Digest | None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    created_by: NonEmptyStr
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_state_and_timestamps(self) -> ChangeRecord:
        if self.current_phase != self.status:
            raise ValueError("current_phase must match status")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        return self


class ImpactFinding(ContractModel):
    finding_id: NonEmptyStr
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    system_id: NonEmptyStr
    finding_type: NonEmptyStr
    severity: RiskLevel
    confidence: Confidence
    summary: NonEmptyStr
    evidence_refs: tuple[Reference, ...] = Field(min_length=1)
    owner_refs: tuple[Reference, ...]
    recommended_actions: tuple[NonEmptyStr, ...]
    created_by_agent: NonEmptyStr
    created_at: AwareDatetime


class RemediationStep(ContractModel):
    step_id: NonEmptyStr
    order: int = Field(ge=1)
    agent_id: NonEmptyStr
    tool_name: NonEmptyStr
    resource: NonEmptyStr
    depends_on: tuple[NonEmptyStr, ...]
    risk_level: RiskLevel
    requires_approval: bool
    idempotency_key: NonEmptyStr


class RemediationPlan(ContractModel):
    plan_id: NonEmptyStr
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    version: int = Field(ge=1)
    risk_level: RiskLevel
    summary: NonEmptyStr
    preconditions: tuple[NonEmptyStr, ...]
    steps: tuple[RemediationStep, ...] = Field(min_length=1)
    verification_steps: tuple[NonEmptyStr, ...] = Field(min_length=1)
    rollback_steps: tuple[NonEmptyStr, ...] = Field(min_length=1)
    evidence_refs: tuple[Reference, ...] = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_step_graph(self) -> RemediationPlan:
        by_id = {step.step_id: step for step in self.steps}
        if len(by_id) != len(self.steps):
            raise ValueError("plan step_id values must be unique")
        orders = {step.order for step in self.steps}
        if len(orders) != len(self.steps):
            raise ValueError("plan step order values must be unique")
        if orders != set(range(1, len(self.steps) + 1)):
            raise ValueError("plan step order values must be contiguous and start at 1")
        for step in self.steps:
            for dependency_id in step.depends_on:
                dependency = by_id.get(dependency_id)
                if dependency is None:
                    raise ValueError(f"unknown step dependency: {dependency_id}")
                if dependency.order >= step.order:
                    raise ValueError("step dependencies must precede the dependent step")
        return self


class ToolIntent(ContractModel):
    schema_version: Literal["1.0"]
    intent_id: NonEmptyStr
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    workflow_execution_id: NonEmptyStr
    plan_id: NonEmptyStr
    plan_hash: Sha256Digest
    step_id: NonEmptyStr
    agent_identity: NonEmptyStr
    tool_name: NonEmptyStr
    action: NonEmptyStr
    resource: NonEmptyStr
    arguments: dict[str, JsonValue]
    reason: NonEmptyStr
    evidence_refs: tuple[Reference, ...]
    idempotency_key: NonEmptyStr
    requested_at: AwareDatetime


class PolicyDecision(ContractModel):
    decision_id: NonEmptyStr
    tenant_id: NonEmptyStr
    intent_id: NonEmptyStr
    effect: PolicyEffect
    computed_risk: RiskLevel
    approval_required: bool
    approval_valid: bool
    matched_policy_ids: tuple[NonEmptyStr, ...]
    reasons: tuple[NonEmptyStr, ...] = Field(min_length=1)
    evaluated_at: AwareDatetime


class Approval(ContractModel):
    approval_id: NonEmptyStr
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    plan_id: NonEmptyStr
    plan_hash: Sha256Digest
    decision: ApprovalDecision
    scope: tuple[NonEmptyStr, ...] = Field(min_length=1)
    approved_by: NonEmptyStr
    approved_at: AwareDatetime
    expires_at: AwareDatetime
    comment: NonEmptyStr

    @model_validator(mode="after")
    def validate_expiration(self) -> Approval:
        if self.expires_at <= self.approved_at:
            raise ValueError("approval expiration must be after the decision time")
        return self


class AuditEvent(ContractModel):
    audit_event_id: NonEmptyStr
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    trace_id: NonEmptyStr
    event_type: NonEmptyStr
    actor_type: ActorType
    actor_id: NonEmptyStr
    resource: NonEmptyStr
    action: NonEmptyStr
    decision_id: NonEmptyStr | None = None
    input_hash: Sha256Digest
    output_hash: Sha256Digest
    status: AuditStatus
    redacted_summary: NonEmptyStr
    created_at: AwareDatetime


class AgentInvocationBudget(ContractModel):
    max_model_calls: int = Field(ge=1, le=10)
    max_tool_calls: int = Field(ge=0, le=25)
    max_turns: int = Field(ge=1, le=10)
    timeout_seconds: float = Field(gt=0, le=300)


class AgentRegistration(ContractModel):
    agent_id: NonEmptyStr
    tenant_id: NonEmptyStr
    display_name: NonEmptyStr
    description: NonEmptyStr
    version: NonEmptyStr
    owner: NonEmptyStr
    capabilities: tuple[NonEmptyStr, ...] = Field(min_length=1)
    allowed_tools: tuple[NonEmptyStr, ...]
    allowed_resource_patterns: tuple[NonEmptyStr, ...] = Field(min_length=1)
    risk_ceiling: RiskLevel
    runtime_endpoint: AnyUrl
    identity_reference: NonEmptyStr
    status: AgentStatus
    budget: AgentInvocationBudget
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_registration(self) -> AgentRegistration:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        for values, label in (
            (self.capabilities, "capabilities"),
            (self.allowed_tools, "allowed_tools"),
            (self.allowed_resource_patterns, "allowed_resource_patterns"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} values must be unique")
        if any(tool == "*" or "*" in tool for tool in self.allowed_tools):
            raise ValueError("agent tools must be exact registered tool names")
        if any(pattern == "*" for pattern in self.allowed_resource_patterns):
            raise ValueError("agent resource scope cannot be unrestricted")
        return self


class EvidenceItem(ContractModel):
    evidence_id: NonEmptyStr
    tenant_id: NonEmptyStr
    source_system: NonEmptyStr
    source_resource: Reference
    summary: NonEmptyStr
    content_hash: Sha256Digest
    trust: EvidenceTrust
    observed_at: AwareDatetime
    attributes: dict[str, JsonValue]


class DependencyPath(ContractModel):
    systems: tuple[NonEmptyStr, ...] = Field(min_length=2)
    evidence_refs: tuple[Reference, ...] = Field(min_length=1)


class OrchestrationDirective(ContractModel):
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    normalized_objective: NonEmptyStr
    selected_agent_ids: tuple[NonEmptyStr, ...] = Field(min_length=6, max_length=6)
    evidence_refs: tuple[Reference, ...] = Field(min_length=1)
    confidence: Confidence
    unknowns: tuple[NonEmptyStr, ...]


class ImpactAnalysis(ContractModel):
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    affected_systems: tuple[NonEmptyStr, ...] = Field(min_length=1)
    dependency_paths: tuple[DependencyPath, ...]
    severity: RiskLevel
    confidence: Confidence
    evidence_refs: tuple[Reference, ...] = Field(min_length=1)
    owner_refs: tuple[Reference, ...]
    unknowns: tuple[NonEmptyStr, ...]


class ComplianceAnalysis(ContractModel):
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    applicable_policy_ids: tuple[NonEmptyStr, ...]
    required_approvals: tuple[NonEmptyStr, ...]
    required_evidence: tuple[NonEmptyStr, ...]
    forbidden_actions: tuple[NonEmptyStr, ...]
    retention_requirements: tuple[NonEmptyStr, ...]
    missing_policy_data: tuple[NonEmptyStr, ...]
    evidence_refs: tuple[Reference, ...] = Field(min_length=1)
    confidence: Confidence


class RemediationProposal(ContractModel):
    proposal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    agent_id: NonEmptyStr
    target_system: NonEmptyStr
    summary: NonEmptyStr
    proposed_tool: NonEmptyStr
    target_resource: NonEmptyStr
    proposed_arguments: dict[str, JsonValue]
    validation_actions: tuple[NonEmptyStr, ...] = Field(min_length=1)
    rollback_actions: tuple[NonEmptyStr, ...] = Field(min_length=1)
    risk_level: RiskLevel
    requires_approval: bool
    confidence: Confidence
    evidence_refs: tuple[Reference, ...] = Field(min_length=1)
    unknowns: tuple[NonEmptyStr, ...]


class VerificationProposal(ContractModel):
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    checks: tuple[NonEmptyStr, ...] = Field(min_length=1)
    partial_result_handling: NonEmptyStr
    failure_handling: NonEmptyStr
    evidence_refs: tuple[Reference, ...] = Field(min_length=1)
    confidence: Confidence


class AgentInvocationRecord(ContractModel):
    invocation_id: NonEmptyStr
    agent_id: NonEmptyStr
    identity_reference: NonEmptyStr
    model_name: NonEmptyStr
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    started_at: AwareDatetime
    completed_at: AwareDatetime
    output_hash: Sha256Digest
    evidence_refs: tuple[Reference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_invocation_times(self) -> AgentInvocationRecord:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be earlier than started_at")
        return self


class FleetAnalysisRequest(ContractModel):
    change_id: NonEmptyStr
    event: ChangeEvent


class FleetAnalysisResult(ContractModel):
    analysis_id: NonEmptyStr
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    trace_id: NonEmptyStr
    model_mode: Literal["fake", "live"]
    orchestration: OrchestrationDirective
    impact: ImpactAnalysis
    compliance: ComplianceAnalysis
    remediation_proposals: tuple[RemediationProposal, ...] = Field(min_length=3, max_length=3)
    verification: VerificationProposal
    draft_plan: RemediationPlan
    draft_plan_hash: Sha256Digest
    evidence: tuple[EvidenceItem, ...] = Field(min_length=1)
    invocations: tuple[AgentInvocationRecord, ...] = Field(min_length=7, max_length=7)
    max_parallel_agents: int = Field(ge=1)
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_analysis_scope(self) -> FleetAnalysisResult:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be earlier than started_at")
        scoped = (self.orchestration, self.impact, self.compliance, self.verification)
        if any(item.tenant_id != self.tenant_id for item in scoped):
            raise ValueError("all structured outputs must match the result tenant")
        if any(item.change_id != self.change_id for item in scoped):
            raise ValueError("all structured outputs must match the result change")
        if (
            self.draft_plan.tenant_id != self.tenant_id
            or self.draft_plan.change_id != self.change_id
        ):
            raise ValueError("draft plan scope must match the result")
        if any(
            proposal.tenant_id != self.tenant_id or proposal.change_id != self.change_id
            for proposal in self.remediation_proposals
        ):
            raise ValueError("all proposals must match the result scope")
        if len({invocation.agent_id for invocation in self.invocations}) != 7:
            raise ValueError("exactly seven distinct agent invocations are required")
        evidence_ids = {item.evidence_id for item in self.evidence}
        referenced = set(self.orchestration.evidence_refs)
        referenced.update(self.impact.evidence_refs)
        referenced.update(self.compliance.evidence_refs)
        referenced.update(self.verification.evidence_refs)
        for proposal in self.remediation_proposals:
            referenced.update(proposal.evidence_refs)
        if not referenced.issubset(evidence_ids):
            raise ValueError("structured outputs may reference only supplied evidence")
        return self
