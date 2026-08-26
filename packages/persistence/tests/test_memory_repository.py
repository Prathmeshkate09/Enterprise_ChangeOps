"""Tenant-isolation tests for the in-memory repository."""

from datetime import UTC, datetime

import pytest
from changeops_contracts import (
    ActorType,
    AuditEvent,
    AuditStatus,
    ChangeEnvironment,
    ChangeRecord,
    ChangeSource,
    RiskLevel,
    WorkflowState,
    sha256_digest,
)
from changeops_persistence import (
    AuditCursorNotFoundError,
    ChangeAlreadyExistsError,
    InMemoryChangeStateRepository,
    TenantScopeViolationError,
)


def make_change(tenant_id: str) -> ChangeRecord:
    created_at = datetime(2026, 8, 27, 10, 37, tzinfo=UTC)
    return ChangeRecord(
        change_id="chg_shared_id",
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


def make_audit(change: ChangeRecord, audit_event_id: str) -> AuditEvent:
    return AuditEvent(
        audit_event_id=audit_event_id,
        tenant_id=change.tenant_id,
        change_id=change.change_id,
        trace_id="trace_001",
        event_type="CHANGE_RECEIVED",
        actor_type=ActorType.SERVICE,
        actor_id="event-gateway",
        resource=f"changes/{change.change_id}",
        action="create_change",
        input_hash=sha256_digest({"event_id": change.event_id}),
        output_hash=sha256_digest(change),
        status=AuditStatus.SUCCESS,
        redacted_summary="Change accepted.",
        created_at=change.created_at,
    )


def test_cross_tenant_lookup_is_rejected() -> None:
    repository = InMemoryChangeStateRepository()
    repository.add(make_change("tenant_alpha"))

    with pytest.raises(TenantScopeViolationError):
        repository.get("tenant_beta", "chg_shared_id")


def test_same_change_id_can_exist_independently_per_tenant() -> None:
    repository = InMemoryChangeStateRepository()
    alpha = make_change("tenant_alpha")
    beta = make_change("tenant_beta")
    repository.add(alpha)
    repository.add(beta)

    assert repository.get("tenant_alpha", "chg_shared_id") == alpha
    assert repository.get("tenant_beta", "chg_shared_id") == beta


def test_duplicate_tenant_change_key_is_rejected() -> None:
    repository = InMemoryChangeStateRepository()
    repository.add(make_change("tenant_alpha"))

    with pytest.raises(ChangeAlreadyExistsError):
        repository.add(make_change("tenant_alpha"))


def test_audit_cursor_returns_only_later_events() -> None:
    repository = InMemoryChangeStateRepository()
    change = make_change("tenant_alpha")
    repository.add_with_audit(change, make_audit(change, "audit_001"))
    repository.record_audit(make_audit(change, "audit_002"))

    events = repository.list_audit_after(
        "tenant_alpha",
        change.change_id,
        after_event_id="audit_001",
        limit=10,
    )

    assert [event.audit_event_id for event in events] == ["audit_002"]
    with pytest.raises(AuditCursorNotFoundError):
        repository.list_audit_after(
            "tenant_alpha",
            change.change_id,
            after_event_id="audit_unknown",
            limit=10,
        )
