"""Typed approval, execution, and HTTP contracts for the Tool Gateway."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from changeops_contracts import (
    Approval,
    ApprovalDecision,
    AuditEvent,
    ChangeEnvironment,
    PolicyDecision,
    RemediationPlan,
    ToolIntent,
    UserRole,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

NonEmptyStr = Annotated[str, Field(min_length=1, max_length=512)]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class GatewayModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class ApprovalRequestStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class ToolExecutionStatus(StrEnum):
    RESERVED = "RESERVED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ApprovalCreateRequest(GatewayModel):
    approval_id: NonEmptyStr
    plan: RemediationPlan
    environment: ChangeEnvironment
    scope: tuple[NonEmptyStr, ...] = Field(min_length=1)
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_scope(self) -> ApprovalCreateRequest:
        step_ids = {step.step_id for step in self.plan.steps}
        if not set(self.scope).issubset(step_ids):
            raise ValueError("approval scope must contain only plan step identifiers")
        if len(self.scope) != len(set(self.scope)):
            raise ValueError("approval scope values must be unique")
        return self


class ApprovalDecisionRequest(GatewayModel):
    expected_version: int = Field(ge=1)
    comment: NonEmptyStr


class ApprovalRequestRecord(GatewayModel):
    approval_id: NonEmptyStr
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    plan_id: NonEmptyStr
    plan_hash: Sha256Digest
    plan_version: int = Field(ge=1)
    environment: ChangeEnvironment
    scope: tuple[NonEmptyStr, ...] = Field(min_length=1)
    status: ApprovalRequestStatus
    requested_by: NonEmptyStr
    requested_at: AwareDatetime
    expires_at: AwareDatetime
    decided_by: NonEmptyStr | None = None
    decided_by_roles: tuple[UserRole, ...] = ()
    decided_at: AwareDatetime | None = None
    comment: NonEmptyStr | None = None
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> ApprovalRequestRecord:
        if self.expires_at <= self.requested_at:
            raise ValueError("approval request expiration must be after creation")
        decided = self.status is not ApprovalRequestStatus.PENDING
        decision_fields = (self.decided_by, self.decided_at, self.comment)
        if decided and any(value is None for value in decision_fields):
            raise ValueError("decided approval requests require decision metadata")
        if not decided and any(value is not None for value in decision_fields):
            raise ValueError("pending approval requests cannot contain decision metadata")
        if not decided and self.decided_by_roles:
            raise ValueError("pending approval requests cannot contain decision roles")
        if self.decided_at is not None and self.decided_at < self.requested_at:
            raise ValueError("approval decision cannot precede its request")
        return self

    def as_approval(self) -> Approval | None:
        if self.status is not ApprovalRequestStatus.APPROVED:
            return None
        if self.decided_by is None or self.decided_at is None or self.comment is None:
            raise RuntimeError("approved request is missing validated decision metadata")
        return Approval(
            approval_id=self.approval_id,
            tenant_id=self.tenant_id,
            change_id=self.change_id,
            plan_id=self.plan_id,
            plan_hash=self.plan_hash,
            plan_version=self.plan_version,
            environment=self.environment,
            decision=ApprovalDecision.APPROVED,
            scope=self.scope,
            approved_by=self.decided_by,
            approved_by_roles=self.decided_by_roles,
            approved_at=self.decided_at,
            expires_at=self.expires_at,
            comment=self.comment,
        )


class ApprovalListResponse(GatewayModel):
    items: tuple[ApprovalRequestRecord, ...]
    count: int = Field(ge=0)


class GatewayExecutionRequest(GatewayModel):
    intent: ToolIntent
    approval_id: NonEmptyStr | None = None


class ToolExecutionRecord(GatewayModel):
    execution_id: NonEmptyStr
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    intent_id: NonEmptyStr
    idempotency_key: NonEmptyStr
    input_hash: Sha256Digest
    approval_id: NonEmptyStr | None
    decision_id: NonEmptyStr
    status: ToolExecutionStatus
    attempt_count: int = Field(ge=1)
    output: dict[str, JsonValue] | None = None
    output_hash: Sha256Digest | None = None
    error_code: NonEmptyStr | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_status_fields(self) -> ToolExecutionRecord:
        if self.status is ToolExecutionStatus.SUCCEEDED and (
            self.output is None or self.output_hash is None or self.error_code is not None
        ):
            raise ValueError("successful execution requires output and no error")
        if self.status is ToolExecutionStatus.FAILED and self.error_code is None:
            raise ValueError("failed execution requires an error code")
        if self.status is ToolExecutionStatus.RESERVED and any(
            value is not None for value in (self.output, self.output_hash, self.error_code)
        ):
            raise ValueError("reserved execution cannot have a result")
        return self


class ExecutionReservation(GatewayModel):
    record: ToolExecutionRecord
    replayed: bool


class GatewayExecutionResult(GatewayModel):
    execution_id: NonEmptyStr
    decision: PolicyDecision
    output: dict[str, JsonValue]
    output_hash: Sha256Digest
    replayed: bool


class AuditListResponse(GatewayModel):
    items: tuple[AuditEvent, ...]
    count: int = Field(ge=0)


class HealthResponse(GatewayModel):
    service: str
    status: str
    environment: ChangeEnvironment | str


class FieldPatchArguments(GatewayModel):
    old_field: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]
    new_field: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]

    @model_validator(mode="after")
    def validate_change(self) -> FieldPatchArguments:
        if self.old_field == self.new_field:
            raise ValueError("old_field and new_field must differ")
        return self


class PatchExecutionOutput(GatewayModel):
    system_id: NonEmptyStr
    field_name: NonEmptyStr
    before: NonEmptyStr
    after: NonEmptyStr
    idempotency_key: NonEmptyStr
    configuration_hash: Sha256Digest
    replayed: bool


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
