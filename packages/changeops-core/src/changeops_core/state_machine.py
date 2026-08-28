"""Deterministic, audited workflow state transitions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

from changeops_contracts import (
    ActorType,
    AuditEvent,
    AuditStatus,
    ChangeRecord,
    WorkflowState,
    sha256_digest,
)
from changeops_persistence import (
    ChangeStateRepository,
    OptimisticConcurrencyError,
)

_ALLOWED_TRANSITIONS: Mapping[WorkflowState, frozenset[WorkflowState]] = MappingProxyType(
    {
        WorkflowState.RECEIVED: frozenset(
            {WorkflowState.SCREENING, WorkflowState.CANCELLED, WorkflowState.FAILED}
        ),
        WorkflowState.SCREENING: frozenset(
            {
                WorkflowState.BLOCKED,
                WorkflowState.ANALYZING,
                WorkflowState.CANCELLED,
                WorkflowState.FAILED,
                WorkflowState.NEEDS_ATTENTION,
            }
        ),
        WorkflowState.BLOCKED: frozenset(
            {WorkflowState.SCREENING, WorkflowState.CANCELLED, WorkflowState.NEEDS_ATTENTION}
        ),
        WorkflowState.ANALYZING: frozenset(
            {
                WorkflowState.PLAN_READY,
                WorkflowState.BLOCKED,
                WorkflowState.CANCELLED,
                WorkflowState.FAILED,
                WorkflowState.NEEDS_ATTENTION,
            }
        ),
        WorkflowState.PLAN_READY: frozenset(
            {
                WorkflowState.AWAITING_APPROVAL,
                WorkflowState.EXECUTING,
                WorkflowState.ANALYZING,
                WorkflowState.CANCELLED,
                WorkflowState.NEEDS_ATTENTION,
            }
        ),
        WorkflowState.AWAITING_APPROVAL: frozenset(
            {
                WorkflowState.APPROVED,
                WorkflowState.REJECTED,
                WorkflowState.CANCELLED,
                WorkflowState.NEEDS_ATTENTION,
            }
        ),
        WorkflowState.APPROVED: frozenset(
            {
                WorkflowState.EXECUTING,
                WorkflowState.CANCELLED,
                WorkflowState.NEEDS_ATTENTION,
            }
        ),
        WorkflowState.REJECTED: frozenset({WorkflowState.ANALYZING, WorkflowState.CANCELLED}),
        WorkflowState.EXECUTING: frozenset(
            {
                WorkflowState.VERIFYING,
                WorkflowState.ROLLING_BACK,
                WorkflowState.FAILED,
                WorkflowState.PARTIAL,
                WorkflowState.NEEDS_ATTENTION,
            }
        ),
        WorkflowState.VERIFYING: frozenset(
            {
                WorkflowState.COMPLETED,
                WorkflowState.ROLLING_BACK,
                WorkflowState.FAILED,
                WorkflowState.PARTIAL,
                WorkflowState.NEEDS_ATTENTION,
            }
        ),
        WorkflowState.ROLLING_BACK: frozenset(
            {
                WorkflowState.FAILED,
                WorkflowState.PARTIAL,
                WorkflowState.CANCELLED,
                WorkflowState.NEEDS_ATTENTION,
            }
        ),
        WorkflowState.NEEDS_ATTENTION: frozenset(
            {
                WorkflowState.SCREENING,
                WorkflowState.ANALYZING,
                WorkflowState.AWAITING_APPROVAL,
                WorkflowState.EXECUTING,
                WorkflowState.VERIFYING,
                WorkflowState.ROLLING_BACK,
                WorkflowState.FAILED,
                WorkflowState.CANCELLED,
            }
        ),
        WorkflowState.COMPLETED: frozenset(),
        WorkflowState.FAILED: frozenset(),
        WorkflowState.PARTIAL: frozenset(),
        WorkflowState.CANCELLED: frozenset(),
    }
)


class InvalidStateTransitionError(RuntimeError):
    """Raised only after the rejected transition is durably audited."""

    def __init__(
        self,
        current: WorkflowState,
        target: WorkflowState,
        audit_event_id: str,
    ) -> None:
        super().__init__(f"Workflow cannot transition from {current} to {target}.")
        self.current = current
        self.target = target
        self.audit_event_id = audit_event_id


def allowed_targets(state: WorkflowState) -> frozenset[WorkflowState]:
    """Return the immutable set of valid target states."""

    return _ALLOWED_TRANSITIONS[state]


def can_transition(current: WorkflowState, target: WorkflowState) -> bool:
    """Evaluate the static transition graph without model involvement."""

    return target in allowed_targets(current)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_audit_id() -> str:
    return f"audit_{uuid4().hex}"


class StateTransitionService:
    """Apply optimistic, tenant-scoped transitions with mandatory audit events."""

    def __init__(
        self,
        repository: ChangeStateRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        audit_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or _utc_now
        self._audit_id_factory = audit_id_factory or _new_audit_id

    def transition(
        self,
        *,
        tenant_id: str,
        change_id: str,
        target: WorkflowState,
        expected_version: int,
        trace_id: str,
        actor_type: ActorType,
        actor_id: str,
        record_updates: Mapping[str, object] | None = None,
    ) -> ChangeRecord:
        current = self._repository.get(tenant_id, change_id)
        transitioned_at = self._clock()
        if transitioned_at.tzinfo is None or transitioned_at.utcoffset() is None:
            raise ValueError("State transition clock must return a timezone-aware datetime.")
        if transitioned_at < current.updated_at:
            raise ValueError("State transition clock cannot move updated_at backwards.")

        updates = dict(record_updates or {})
        allowed_update_fields = {
            "workflow_execution_id",
            "plan_version",
            "plan_hash",
            "risk_level",
        }
        unsupported_fields = set(updates) - allowed_update_fields
        if unsupported_fields:
            raise ValueError(
                "Unsupported transition record updates: " + ", ".join(sorted(unsupported_fields))
            )

        input_document = {
            "change_id": change_id,
            "current": current.status,
            "expected_version": expected_version,
            "record_updates": updates,
            "target": target,
            "tenant_id": tenant_id,
        }
        input_hash = sha256_digest(input_document)

        if not can_transition(current.status, target):
            audit_event = self._build_audit_event(
                current=current,
                target=target,
                trace_id=trace_id,
                actor_type=actor_type,
                actor_id=actor_id,
                input_hash=input_hash,
                output_hash=sha256_digest({"reason": "invalid_transition"}),
                status=AuditStatus.REJECTED,
                created_at=transitioned_at,
            )
            self._repository.record_audit(audit_event)
            raise InvalidStateTransitionError(
                current.status,
                target,
                audit_event.audit_event_id,
            )

        updated_document = current.model_dump(mode="python")
        updated_document.update(updates)
        updated_document.update(
            {
                "status": target,
                "current_phase": target,
                "updated_at": transitioned_at,
                "version": expected_version + 1,
            }
        )
        updated = ChangeRecord.model_validate(updated_document)
        audit_event = self._build_audit_event(
            current=current,
            target=target,
            trace_id=trace_id,
            actor_type=actor_type,
            actor_id=actor_id,
            input_hash=input_hash,
            output_hash=sha256_digest(updated),
            status=AuditStatus.SUCCESS,
            created_at=transitioned_at,
        )
        try:
            self._repository.commit_transition(
                updated,
                audit_event,
                expected_version=expected_version,
            )
        except OptimisticConcurrencyError as error:
            conflict_document = audit_event.model_dump(mode="python")
            conflict_document.update(
                {
                    "event_type": "WORKFLOW_STATE_TRANSITION_REJECTED",
                    "output_hash": sha256_digest(
                        {
                            "actual_version": error.actual_version,
                            "expected_version": error.expected_version,
                            "reason": "optimistic_concurrency_conflict",
                        }
                    ),
                    "status": AuditStatus.REJECTED,
                    "redacted_summary": (
                        f"Workflow transition {current.status} to {target} rejected."
                    ),
                }
            )
            self._repository.record_audit(AuditEvent.model_validate(conflict_document))
            raise
        return updated

    def _build_audit_event(
        self,
        *,
        current: ChangeRecord,
        target: WorkflowState,
        trace_id: str,
        actor_type: ActorType,
        actor_id: str,
        input_hash: str,
        output_hash: str,
        status: AuditStatus,
        created_at: datetime,
    ) -> AuditEvent:
        outcome = "SUCCEEDED" if status is AuditStatus.SUCCESS else "REJECTED"
        return AuditEvent(
            audit_event_id=self._audit_id_factory(),
            tenant_id=current.tenant_id,
            change_id=current.change_id,
            trace_id=trace_id,
            event_type=f"WORKFLOW_STATE_TRANSITION_{outcome}",
            actor_type=actor_type,
            actor_id=actor_id,
            resource=f"changes/{current.change_id}",
            action="transition_state",
            input_hash=input_hash,
            output_hash=output_hash,
            status=status,
            redacted_summary=(f"Workflow transition {current.status} to {target} {status.value}."),
            created_at=created_at,
        )
