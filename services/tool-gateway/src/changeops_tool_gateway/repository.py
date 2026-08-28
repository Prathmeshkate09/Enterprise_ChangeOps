"""Thread-safe Phase 5 approval, plan, idempotency, and audit persistence port."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from threading import RLock
from typing import Protocol

from changeops_contracts import (
    Approval,
    AuditEvent,
    PolicyDecision,
    RemediationPlan,
    ToolIntent,
    UserRole,
    calculate_plan_hash,
    sha256_digest,
)
from pydantic import JsonValue

from changeops_tool_gateway.errors import (
    ApprovalRequiredError,
    AuthorizationError,
    GatewayConflictError,
    GatewayNotFoundError,
)
from changeops_tool_gateway.models import (
    ApprovalRequestRecord,
    ApprovalRequestStatus,
    ExecutionReservation,
    ToolExecutionRecord,
    ToolExecutionStatus,
)


def same_approval_request(current: ApprovalRequestRecord, candidate: ApprovalRequestRecord) -> bool:
    """Compare the immutable approval scope while ignoring server creation time."""

    ignored = {"requested_at"}
    return current.model_dump(mode="python", exclude=ignored) == candidate.model_dump(
        mode="python", exclude=ignored
    )


def same_approval_decision(
    *,
    current: ApprovalRequestRecord,
    target: ApprovalRequestStatus,
    expected_version: int,
    decided_by: str,
    decided_by_roles: tuple[UserRole, ...],
    comment: str,
) -> bool:
    """Allow only the exact retry of an already committed approval decision."""

    return (
        current.status is target
        and current.version == expected_version + 1
        and current.decided_by == decided_by
        and current.decided_by_roles == decided_by_roles
        and current.comment == comment
    )


class GovernanceRepository(Protocol):
    def check_ready(self) -> None: ...

    def create_approval_request(
        self, *, record: ApprovalRequestRecord, plan: RemediationPlan
    ) -> ApprovalRequestRecord: ...

    def get_plan(self, tenant_id: str, change_id: str, plan_id: str) -> RemediationPlan: ...

    def get_approval_request(self, tenant_id: str, approval_id: str) -> ApprovalRequestRecord: ...

    def list_approval_requests(
        self, tenant_id: str, *, limit: int
    ) -> tuple[ApprovalRequestRecord, ...]: ...

    def decide_approval(
        self,
        *,
        tenant_id: str,
        approval_id: str,
        target: ApprovalRequestStatus,
        expected_version: int,
        decided_by: str,
        decided_by_roles: tuple[UserRole, ...],
        comment: str,
        decided_at: datetime,
    ) -> ApprovalRequestRecord: ...

    def reserve_execution(
        self,
        *,
        intent: ToolIntent,
        decision: PolicyDecision,
        approval: Approval | None,
        input_hash: str,
        now: datetime,
    ) -> ExecutionReservation: ...

    def complete_execution(
        self,
        *,
        tenant_id: str,
        change_id: str,
        execution_id: str,
        output: dict[str, JsonValue],
        output_hash: str,
        completed_at: datetime,
    ) -> ToolExecutionRecord: ...

    def fail_execution(
        self,
        *,
        tenant_id: str,
        change_id: str,
        execution_id: str,
        error_code: str,
        failed_at: datetime,
    ) -> ToolExecutionRecord: ...

    def record_audit(self, event: AuditEvent) -> None: ...

    def list_audit(self, tenant_id: str, *, limit: int) -> tuple[AuditEvent, ...]: ...


class InMemoryGovernanceRepository:
    """Atomic local adapter with the same tenant partitions as Firestore."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._plans: dict[tuple[str, str, str], RemediationPlan] = {}
        self._approvals: dict[tuple[str, str], ApprovalRequestRecord] = {}
        self._approval_tenants: dict[str, set[str]] = defaultdict(set)
        self._executions: dict[tuple[str, str], ToolExecutionRecord] = {}
        self._execution_ids: dict[tuple[str, str], str] = {}
        self._audit: dict[tuple[str, str], AuditEvent] = {}

    def check_ready(self) -> None:
        return None

    def create_approval_request(
        self, *, record: ApprovalRequestRecord, plan: RemediationPlan
    ) -> ApprovalRequestRecord:
        plan_key = (plan.tenant_id, plan.change_id, plan.plan_id)
        approval_key = (record.tenant_id, record.approval_id)
        with self._lock:
            if calculate_plan_hash(plan) != record.plan_hash:
                raise GatewayConflictError("Approval request plan hash is not canonical.")
            existing_plan = self._plans.get(plan_key)
            if existing_plan is not None and calculate_plan_hash(existing_plan) != record.plan_hash:
                raise GatewayConflictError("A different plan already uses this plan identifier.")
            existing_approval = self._approvals.get(approval_key)
            if existing_approval is not None:
                if existing_plan == plan and same_approval_request(existing_approval, record):
                    return existing_approval
                raise GatewayConflictError("Approval request identifier already exists.")
            self._plans[plan_key] = plan
            self._approvals[approval_key] = record
            self._approval_tenants[record.approval_id].add(record.tenant_id)
            return record

    def get_plan(self, tenant_id: str, change_id: str, plan_id: str) -> RemediationPlan:
        with self._lock:
            plan = self._plans.get((tenant_id, change_id, plan_id))
            if plan is None:
                raise GatewayNotFoundError("plan")
            return plan

    def get_approval_request(self, tenant_id: str, approval_id: str) -> ApprovalRequestRecord:
        with self._lock:
            record = self._approvals.get((tenant_id, approval_id))
            if record is not None:
                return record
            if self._approval_tenants.get(approval_id):
                raise GatewayNotFoundError("approval")
            raise GatewayNotFoundError("approval")

    def list_approval_requests(
        self, tenant_id: str, *, limit: int
    ) -> tuple[ApprovalRequestRecord, ...]:
        with self._lock:
            records = [
                record for (owner, _), record in self._approvals.items() if owner == tenant_id
            ]
            records.sort(key=lambda item: (item.requested_at, item.approval_id), reverse=True)
            return tuple(records[:limit])

    def decide_approval(
        self,
        *,
        tenant_id: str,
        approval_id: str,
        target: ApprovalRequestStatus,
        expected_version: int,
        decided_by: str,
        decided_by_roles: tuple[UserRole, ...],
        comment: str,
        decided_at: datetime,
    ) -> ApprovalRequestRecord:
        with self._lock:
            current = self.get_approval_request(tenant_id, approval_id)
            if current.status is not ApprovalRequestStatus.PENDING:
                if same_approval_decision(
                    current=current,
                    target=target,
                    expected_version=expected_version,
                    decided_by=decided_by,
                    decided_by_roles=decided_by_roles,
                    comment=comment,
                ):
                    return current
                raise GatewayConflictError("Approval request already has a final decision.")
            if current.version != expected_version:
                raise GatewayConflictError(
                    "Approval request version is stale.", code="VERSION_CONFLICT"
                )
            if current.expires_at <= decided_at:
                raise GatewayConflictError("Approval request has expired.", code="APPROVAL_EXPIRED")
            if current.requested_by == decided_by:
                raise AuthorizationError(
                    "Separation of duties prevents the plan requester from approving it."
                )
            updated = ApprovalRequestRecord.model_validate(
                {
                    **current.model_dump(mode="python"),
                    "status": target,
                    "decided_by": decided_by,
                    "decided_by_roles": decided_by_roles,
                    "decided_at": decided_at,
                    "comment": comment,
                    "version": current.version + 1,
                }
            )
            self._approvals[(tenant_id, approval_id)] = updated
            return updated

    def reserve_execution(
        self,
        *,
        intent: ToolIntent,
        decision: PolicyDecision,
        approval: Approval | None,
        input_hash: str,
        now: datetime,
    ) -> ExecutionReservation:
        key = (intent.tenant_id, intent.idempotency_key)
        with self._lock:
            if decision.approval_required:
                if approval is None:
                    raise ApprovalRequiredError
                current = self.get_approval_request(intent.tenant_id, approval.approval_id)
                stored = current.as_approval()
                if stored != approval or stored is None or stored.expires_at <= now:
                    raise ApprovalRequiredError
                if intent.step_id not in stored.scope or stored.plan_hash != intent.plan_hash:
                    raise ApprovalRequiredError

            existing_id = self._execution_ids.get(key)
            if existing_id is not None:
                existing = self._executions[(intent.tenant_id, existing_id)]
                if existing.input_hash != input_hash:
                    raise GatewayConflictError(
                        "Idempotency key was already used for a different tool action.",
                        code="IDEMPOTENCY_CONFLICT",
                    )
                if existing.status is ToolExecutionStatus.SUCCEEDED:
                    return ExecutionReservation(record=existing, replayed=True)
                if (
                    existing.status is ToolExecutionStatus.RESERVED
                    and existing.updated_at > now - timedelta(minutes=2)
                ):
                    raise GatewayConflictError(
                        "The idempotent tool action is already in progress.",
                        code="EXECUTION_IN_PROGRESS",
                    )
                reserved = ToolExecutionRecord.model_validate(
                    {
                        **existing.model_dump(mode="python"),
                        "intent_id": intent.intent_id,
                        "decision_id": decision.decision_id,
                        "approval_id": approval.approval_id if approval else None,
                        "status": ToolExecutionStatus.RESERVED,
                        "attempt_count": existing.attempt_count + 1,
                        "output": None,
                        "output_hash": None,
                        "error_code": None,
                        "updated_at": now,
                    }
                )
                self._executions[(intent.tenant_id, existing_id)] = reserved
                return ExecutionReservation(record=reserved, replayed=False)

            execution_digest = sha256_digest(
                {"tenant_id": intent.tenant_id, "key": intent.idempotency_key}
            )
            execution_id = f"execution_{execution_digest[7:31]}"
            record = ToolExecutionRecord(
                execution_id=execution_id,
                tenant_id=intent.tenant_id,
                change_id=intent.change_id,
                intent_id=intent.intent_id,
                idempotency_key=intent.idempotency_key,
                input_hash=input_hash,
                approval_id=approval.approval_id if approval else None,
                decision_id=decision.decision_id,
                status=ToolExecutionStatus.RESERVED,
                attempt_count=1,
                created_at=now,
                updated_at=now,
            )
            self._executions[(intent.tenant_id, execution_id)] = record
            self._execution_ids[key] = execution_id
            return ExecutionReservation(record=record, replayed=False)

    def complete_execution(
        self,
        *,
        tenant_id: str,
        change_id: str,
        execution_id: str,
        output: dict[str, JsonValue],
        output_hash: str,
        completed_at: datetime,
    ) -> ToolExecutionRecord:
        with self._lock:
            current = self._executions.get((tenant_id, execution_id))
            if current is None:
                raise GatewayNotFoundError("tool execution")
            if current.change_id != change_id:
                raise GatewayNotFoundError("tool execution")
            if current.status is not ToolExecutionStatus.RESERVED:
                raise GatewayConflictError("Tool execution is not reserved.")
            updated = ToolExecutionRecord.model_validate(
                {
                    **current.model_dump(mode="python"),
                    "status": ToolExecutionStatus.SUCCEEDED,
                    "output": output,
                    "output_hash": output_hash,
                    "updated_at": completed_at,
                }
            )
            self._executions[(tenant_id, execution_id)] = updated
            return updated

    def fail_execution(
        self,
        *,
        tenant_id: str,
        change_id: str,
        execution_id: str,
        error_code: str,
        failed_at: datetime,
    ) -> ToolExecutionRecord:
        with self._lock:
            current = self._executions.get((tenant_id, execution_id))
            if current is None:
                raise GatewayNotFoundError("tool execution")
            if current.change_id != change_id:
                raise GatewayNotFoundError("tool execution")
            if current.status is not ToolExecutionStatus.RESERVED:
                raise GatewayConflictError("Tool execution is not reserved.")
            updated = ToolExecutionRecord.model_validate(
                {
                    **current.model_dump(mode="python"),
                    "status": ToolExecutionStatus.FAILED,
                    "error_code": error_code,
                    "updated_at": failed_at,
                }
            )
            self._executions[(tenant_id, execution_id)] = updated
            return updated

    def record_audit(self, event: AuditEvent) -> None:
        with self._lock:
            key = (event.tenant_id, event.audit_event_id)
            if key in self._audit:
                raise GatewayConflictError("Audit event identifier already exists.")
            self._audit[key] = event

    def list_audit(self, tenant_id: str, *, limit: int) -> tuple[AuditEvent, ...]:
        with self._lock:
            events = [event for (owner, _), event in self._audit.items() if owner == tenant_id]
            events.sort(key=lambda event: (event.created_at, event.audit_event_id), reverse=True)
            return tuple(events[:limit])
