"""Deterministic transition and mandatory audit tests."""

from datetime import UTC, datetime

import pytest
from changeops_contracts import (
    ActorType,
    AuditStatus,
    ChangeEnvironment,
    ChangeRecord,
    ChangeSource,
    RiskLevel,
    WorkflowState,
)
from changeops_core import InvalidStateTransitionError, StateTransitionService
from changeops_persistence import InMemoryChangeStateRepository, OptimisticConcurrencyError

TRANSITION_TIME = datetime(2026, 8, 27, 10, 37, 5, tzinfo=UTC)


def make_change(*, tenant_id: str = "tenant_demo") -> ChangeRecord:
    created_at = datetime(2026, 8, 27, 10, 37, tzinfo=UTC)
    return ChangeRecord(
        change_id="chg_001",
        tenant_id=tenant_id,
        event_id="evt_001",
        change_type="api.contract.changed",
        title="Rename customer identifier",
        description="Rename customer_id to customer_uuid.",
        source=ChangeSource(
            type="github",
            external_id="pr-42",
            url="https://example.invalid/demo/pr/42",
        ),
        environment=ChangeEnvironment.SANDBOX,
        status=WorkflowState.RECEIVED,
        risk_level=RiskLevel.UNKNOWN,
        current_phase=WorkflowState.RECEIVED,
        workflow_execution_id=None,
        plan_version=0,
        plan_hash=None,
        created_at=created_at,
        updated_at=created_at,
        created_by="event-gateway",
        version=1,
    )


def make_service(repository: InMemoryChangeStateRepository) -> StateTransitionService:
    return StateTransitionService(
        repository,
        clock=lambda: TRANSITION_TIME,
        audit_id_factory=lambda: "audit_transition_001",
    )


def test_valid_transition_updates_version_and_audits_atomically() -> None:
    repository = InMemoryChangeStateRepository()
    repository.add(make_change())

    updated = make_service(repository).transition(
        tenant_id="tenant_demo",
        change_id="chg_001",
        target=WorkflowState.SCREENING,
        expected_version=1,
        trace_id="trace_001",
        actor_type=ActorType.SERVICE,
        actor_id="workflow-coordinator",
    )

    assert updated.status is WorkflowState.SCREENING
    assert updated.current_phase is WorkflowState.SCREENING
    assert updated.version == 2
    assert repository.get("tenant_demo", "chg_001") == updated
    audit = repository.list_audit("tenant_demo", "chg_001")
    assert len(audit) == 1
    assert audit[0].status is AuditStatus.SUCCESS
    assert audit[0].event_type == "WORKFLOW_STATE_TRANSITION_SUCCEEDED"


def test_transition_can_bind_workflow_metadata() -> None:
    repository = InMemoryChangeStateRepository()
    repository.add(make_change())

    updated = make_service(repository).transition(
        tenant_id="tenant_demo",
        change_id="chg_001",
        target=WorkflowState.SCREENING,
        expected_version=1,
        trace_id="trace_001",
        actor_type=ActorType.SERVICE,
        actor_id="workflow-coordinator",
        record_updates={"workflow_execution_id": "wf_001"},
    )

    assert updated.workflow_execution_id == "wf_001"


def test_transition_rejects_uncontrolled_record_updates() -> None:
    repository = InMemoryChangeStateRepository()
    repository.add(make_change())

    with pytest.raises(ValueError, match="Unsupported transition record updates"):
        make_service(repository).transition(
            tenant_id="tenant_demo",
            change_id="chg_001",
            target=WorkflowState.SCREENING,
            expected_version=1,
            trace_id="trace_001",
            actor_type=ActorType.SERVICE,
            actor_id="workflow-coordinator",
            record_updates={"tenant_id": "tenant_other"},
        )


def test_invalid_transition_is_rejected_and_audited() -> None:
    repository = InMemoryChangeStateRepository()
    repository.add(make_change())

    with pytest.raises(InvalidStateTransitionError) as caught:
        make_service(repository).transition(
            tenant_id="tenant_demo",
            change_id="chg_001",
            target=WorkflowState.EXECUTING,
            expected_version=1,
            trace_id="trace_001",
            actor_type=ActorType.SERVICE,
            actor_id="workflow-coordinator",
        )

    assert caught.value.audit_event_id == "audit_transition_001"
    assert repository.get("tenant_demo", "chg_001").status is WorkflowState.RECEIVED
    audit = repository.list_audit("tenant_demo", "chg_001")
    assert len(audit) == 1
    assert audit[0].status is AuditStatus.REJECTED
    assert audit[0].event_type == "WORKFLOW_STATE_TRANSITION_REJECTED"


def test_stale_version_does_not_update_state_and_is_audited() -> None:
    repository = InMemoryChangeStateRepository()
    repository.add(make_change())

    with pytest.raises(OptimisticConcurrencyError):
        make_service(repository).transition(
            tenant_id="tenant_demo",
            change_id="chg_001",
            target=WorkflowState.SCREENING,
            expected_version=0,
            trace_id="trace_001",
            actor_type=ActorType.SERVICE,
            actor_id="workflow-coordinator",
        )

    assert repository.get("tenant_demo", "chg_001").status is WorkflowState.RECEIVED
    audit = repository.list_audit("tenant_demo", "chg_001")
    assert len(audit) == 1
    assert audit[0].status is AuditStatus.REJECTED


def test_naive_transition_clock_is_rejected_without_mutation() -> None:
    repository = InMemoryChangeStateRepository()
    repository.add(make_change())
    service = StateTransitionService(
        repository,
        clock=lambda: datetime(2026, 8, 27, 10, 37, 5),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        service.transition(
            tenant_id="tenant_demo",
            change_id="chg_001",
            target=WorkflowState.SCREENING,
            expected_version=1,
            trace_id="trace_001",
            actor_type=ActorType.SERVICE,
            actor_id="workflow-coordinator",
        )

    assert repository.get("tenant_demo", "chg_001").version == 1
    assert repository.list_audit("tenant_demo", "chg_001") == ()
