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
