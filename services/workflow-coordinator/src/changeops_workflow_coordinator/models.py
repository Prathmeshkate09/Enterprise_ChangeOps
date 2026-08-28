"""Strict durable workflow records and callback contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from changeops_contracts import ChangeEvent, RemediationPlan, calculate_plan_hash
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

NonEmptyStr = Annotated[str, Field(min_length=1, max_length=512)]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class WorkflowModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class WorkflowRuntimeStatus(StrEnum):
    RECEIVED = "RECEIVED"
    ANALYZING = "ANALYZING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    ROLLING_BACK = "ROLLING_BACK"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    DEAD_LETTERED = "DEAD_LETTERED"


class WorkflowTaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"


class WorkflowTaskRecord(WorkflowModel):
    step_id: NonEmptyStr
    system_id: Literal["crm", "analytics", "support"]
    status: WorkflowTaskStatus
    attempt_count: int = Field(ge=0)
    snapshot_id: NonEmptyStr | None = None
    snapshot_hash: Sha256Digest | None = None
    execution_id: NonEmptyStr | None = None
    output_hash: Sha256Digest | None = None
    error_code: NonEmptyStr | None = None
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_artifacts(self) -> WorkflowTaskRecord:
        if (self.snapshot_id is None) != (self.snapshot_hash is None):
            raise ValueError("snapshot identifier and hash must be stored together")
        if self.status is WorkflowTaskStatus.SUCCEEDED and (
            self.execution_id is None or self.output_hash is None
        ):
            raise ValueError("successful workflow tasks require execution evidence")
        if self.status in {WorkflowTaskStatus.FAILED, WorkflowTaskStatus.ROLLBACK_FAILED} and (
            self.error_code is None
        ):
            raise ValueError("failed workflow tasks require an error code")
        return self


class WorkflowExecutionRecord(WorkflowModel):
    workflow_execution_id: NonEmptyStr
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    event_id: NonEmptyStr
    trace_id: NonEmptyStr
    event: ChangeEvent
    status: WorkflowRuntimeStatus
    delivery_attempts: int = Field(ge=1)
    plan: RemediationPlan | None = None
    plan_hash: Sha256Digest | None = None
    approval_id: NonEmptyStr | None = None
    approval_expires_at: AwareDatetime | None = None
    tasks: tuple[WorkflowTaskRecord, ...] = ()
    last_error_code: NonEmptyStr | None = None
    started_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> WorkflowExecutionRecord:
        if self.event.tenant_id != self.tenant_id or self.event.event_id != self.event_id:
            raise ValueError("workflow event scope must match the workflow record")
        if self.updated_at < self.started_at:
            raise ValueError("workflow updated_at cannot precede started_at")
        if (self.plan is None) != (self.plan_hash is None):
            raise ValueError("workflow plan and hash must be stored together")
        if self.plan is not None:
            if (
                self.plan.tenant_id != self.tenant_id
                or self.plan.change_id != self.change_id
                or calculate_plan_hash(self.plan) != self.plan_hash
            ):
                raise ValueError("workflow plan scope or hash is invalid")
            if {task.step_id for task in self.tasks} != {step.step_id for step in self.plan.steps}:
                raise ValueError("workflow tasks must match every plan step")
        elif self.tasks:
            raise ValueError("workflow tasks cannot exist before a plan")
        terminal = self.status in {
            WorkflowRuntimeStatus.COMPLETED,
            WorkflowRuntimeStatus.FAILED,
            WorkflowRuntimeStatus.NEEDS_ATTENTION,
            WorkflowRuntimeStatus.DEAD_LETTERED,
        }
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal workflow status and completed_at must agree")
        return self


class ApprovalCallbackRequest(WorkflowModel):
    tenant_id: NonEmptyStr
    change_id: NonEmptyStr
    approval_id: NonEmptyStr
    plan_hash: Sha256Digest
    plan_version: int = Field(ge=1)
    status: Literal["APPROVED", "REJECTED", "CHANGES_REQUESTED"]
    decided_at: AwareDatetime


class DeadLetterRecord(WorkflowModel):
    dead_letter_id: NonEmptyStr
    tenant_id: NonEmptyStr
    event_id: NonEmptyStr
    workflow_execution_id: NonEmptyStr
    error_code: NonEmptyStr
    input_hash: Sha256Digest
    created_at: AwareDatetime


class WorkflowListResponse(WorkflowModel):
    items: tuple[WorkflowExecutionRecord, ...]
    count: int = Field(ge=0)


class DeadLetterListResponse(WorkflowModel):
    items: tuple[DeadLetterRecord, ...]
    count: int = Field(ge=0)


class HealthResponse(WorkflowModel):
    service: str
    status: str
