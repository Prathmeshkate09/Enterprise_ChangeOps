"""Phase 6 durable workflow, retry, dead-letter, and rollback gates."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar

import pytest
from changeops_contracts import (
    ChangeDetails,
    ChangeEvent,
    ChangeSource,
    ChangeSubject,
    RemediationPlan,
    RemediationStep,
    RiskLevel,
    WorkflowState,
    calculate_plan_hash,
    derive_change_id,
    sha256_digest,
)
from changeops_persistence import InMemoryChangeStateRepository
from changeops_workflow_coordinator.clients import DependencyCallError, SnapshotRecord
from changeops_workflow_coordinator.engine import WorkflowEngine
from changeops_workflow_coordinator.models import (
    ApprovalCallbackRequest,
    WorkflowRuntimeStatus,
    WorkflowTaskStatus,
)
from changeops_workflow_coordinator.repository import InMemoryWorkflowRepository
from changeops_workflow_coordinator.retry import RetryPolicy

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def build_event(
    *,
    event_id: str = "evt_phase6_workflow",
    event_type: str = "api.contract.changed",
) -> ChangeEvent:
    return ChangeEvent(
        schema_version="1.0",
        event_id=event_id,
        tenant_id=f"tenant_{event_id}",
        event_type=event_type,
        source=ChangeSource(
            type="github",
            external_id="pr-42",
            url="https://example.invalid/pr/42",
        ),
        occurred_at=NOW,
        received_at=NOW,
        subject=ChangeSubject(
            system_id="customer-api",
            resource_type="api-contract",
            resource_id="customer-v2",
        ),
        change=ChangeDetails(
            summary="Rename customer_id to customer_uuid",
            old_version="1.4.0",
            new_version="2.0.0",
            artifact_refs=("artifact://contracts/customer-v2-diff.json",),
        ),
        correlation_id=f"correlation_{event_id}",
        trace_id=f"trace_{event_id}",
    )


def build_plan(event: ChangeEvent) -> RemediationPlan:
    change_id = derive_change_id(event)
    systems = (
        ("crm", "crm.update_field_mapping"),
        ("analytics", "analytics.update_field_mapping"),
        ("support", "support.update_lookup_field"),
    )
    steps = tuple(
        RemediationStep(
            step_id=f"step_{system}",
            order=index,
            agent_id=system,
            tool_name=tool,
            resource=f"{system}://tenant/{event.tenant_id}/configuration",
            arguments={"old_field": "customer_id", "new_field": "customer_uuid"},
            depends_on=(),
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            idempotency_key=f"{change_id}:{system}:rename",
        )
        for index, (system, tool) in enumerate(systems, start=1)
    )
    return RemediationPlan(
        plan_id=f"plan_{event.event_id}",
        tenant_id=event.tenant_id,
        change_id=change_id,
        version=1,
        risk_level=RiskLevel.HIGH,
        summary="Update all managed customer identifier mappings.",
        preconditions=("sandbox services healthy",),
        steps=steps,
        verification_steps=("verify all three systems independently",),
        rollback_steps=("restore all three bound snapshots",),
        evidence_refs=("evidence://phase6/impact",),
        created_at=NOW,
    )


class FakeFleet:
    def __init__(self, plan: RemediationPlan, *, error_code: str | None = None) -> None:
        self.plan = plan
        self.calls = 0
        self.error_code = error_code

    async def analyze(self, **_: object) -> SimpleNamespace:
        self.calls += 1
        if self.error_code is not None:
            raise DependencyCallError(self.error_code, transient=False)
        return SimpleNamespace(
            draft_plan=self.plan,
            draft_plan_hash=calculate_plan_hash(self.plan),
        )


class FakeSandboxes:
    SYSTEM_BY_TOOL: ClassVar[dict[str, str]] = {
        "crm.update_field_mapping": "crm",
        "analytics.update_field_mapping": "analytics",
        "support.update_lookup_field": "support",
    }

    def __init__(self, *, fail_support_verification: bool = False) -> None:
        self.original_hashes = {
            system: sha256_digest({"system": system, "field": "customer_id"})
            for system in ("crm", "analytics", "support")
        }
        self.current_hashes = dict(self.original_hashes)
        self.fail_support_verification = fail_support_verification
        self.restored: list[str] = []

    def system_for_step(self, step: RemediationStep) -> str:
        return self.SYSTEM_BY_TOOL[step.tool_name]

    async def snapshot(self, *, system: str, tenant_id: str, **_: object) -> SnapshotRecord:
        return SnapshotRecord(
            snapshot_id=f"snapshot_{system}",
            tenant_id=tenant_id,
            system_id=system,
            configuration={"system": system, "field": "customer_id"},
            configuration_hash=self.original_hashes[system],
            created_at=NOW,
        )

    async def verify(self, *, system: str, **_: object) -> SimpleNamespace:
        passed = not (system == "support" and self.fail_support_verification)
        return SimpleNamespace(passed=passed)

    async def restore(self, *, system: str, **_: object) -> SimpleNamespace:
        self.current_hashes[system] = self.original_hashes[system]
        self.restored.append(system)
        return SimpleNamespace(restored=True)

    async def configuration_hash(self, *, system: str, **_: object) -> str:
        return self.current_hashes[system]


class FakeGateway:
    def __init__(self, sandboxes: FakeSandboxes, *, transient_analytics: bool) -> None:
        self.sandboxes = sandboxes
        self.transient_analytics = transient_analytics
        self.approval_calls = 0
        self.attempts: defaultdict[str, int] = defaultdict(int)

    async def create_approval(self, **_: object) -> None:
        self.approval_calls += 1

    async def execute(self, *, step: RemediationStep, **_: object) -> SimpleNamespace:
        system = self.sandboxes.system_for_step(step)
        self.attempts[system] += 1
        if system == "analytics" and self.transient_analytics and self.attempts[system] == 1:
            raise DependencyCallError("TRANSIENT_ANALYTICS_FAILURE", transient=True)
        new_hash = sha256_digest({"system": system, "field": "customer_uuid"})
        self.sandboxes.current_hashes[system] = new_hash
        return SimpleNamespace(
            execution_id=f"execution_{system}",
            output_hash=new_hash,
            replayed=False,
        )


def build_engine(
    event: ChangeEvent,
    *,
    transient_analytics: bool = False,
    fail_support_verification: bool = False,
    fleet_error_code: str | None = None,
) -> tuple[
    WorkflowEngine,
    InMemoryWorkflowRepository,
    InMemoryChangeStateRepository,
    FakeFleet,
    FakeGateway,
    FakeSandboxes,
]:
    plan = build_plan(event)
    workflows = InMemoryWorkflowRepository()
    changes = InMemoryChangeStateRepository()
    sandboxes = FakeSandboxes(fail_support_verification=fail_support_verification)
    fleet = FakeFleet(plan, error_code=fleet_error_code)
    gateway = FakeGateway(sandboxes, transient_analytics=transient_analytics)
    engine = WorkflowEngine(
        workflows=workflows,
        changes=changes,
        fleet=fleet,  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        sandboxes=sandboxes,  # type: ignore[arg-type]
        retry_policy=RetryPolicy(
            maximum_attempts=3,
            base_delay_seconds=0.001,
            jitter=lambda: 0.0,
        ),
        clock=lambda: NOW,
    )
    return engine, workflows, changes, fleet, gateway, sandboxes


def approval_callback(waiting: object) -> ApprovalCallbackRequest:
    record = waiting
    return ApprovalCallbackRequest(
        tenant_id=record.tenant_id,  # type: ignore[attr-defined]
        change_id=record.change_id,  # type: ignore[attr-defined]
        approval_id=record.approval_id,  # type: ignore[attr-defined]
        plan_hash=record.plan_hash,  # type: ignore[attr-defined]
        plan_version=record.plan.version,  # type: ignore[attr-defined,union-attr]
        status="APPROVED",
        decided_at=NOW,
    )


@pytest.mark.asyncio
async def test_transient_step_retries_once_and_duplicate_event_does_not_reexecute() -> None:
    event = build_event()
    engine, _, changes, fleet, gateway, _ = build_engine(
        event,
        transient_analytics=True,
    )

    waiting = await engine.process_event(event)
    duplicate_waiting = await engine.process_event(event)
    completed = await engine.resume_approval(approval_callback(waiting))
    duplicate_callback = await engine.resume_approval(approval_callback(waiting))

    assert waiting.status is WorkflowRuntimeStatus.WAITING_APPROVAL
    assert duplicate_waiting == waiting
    assert fleet.calls == 1
    assert gateway.approval_calls == 1
    assert gateway.attempts == {"crm": 1, "analytics": 2, "support": 1}
    assert completed.status is WorkflowRuntimeStatus.COMPLETED
    assert duplicate_callback == completed
    assert all(task.status is WorkflowTaskStatus.SUCCEEDED for task in completed.tasks)
    analytics = next(task for task in completed.tasks if task.system_id == "analytics")
    assert analytics.attempt_count == 2
    assert changes.get(event.tenant_id, derive_change_id(event)).status is WorkflowState.COMPLETED
    audit_types = {
        item.event_type for item in changes.list_audit(event.tenant_id, derive_change_id(event))
    }
    assert "WORKFLOW_STEP_RETRY_SCHEDULED" in audit_types
    assert "WORKFLOW_VERIFICATION_SUCCEEDED" in audit_types


@pytest.mark.asyncio
async def test_verification_failure_restores_every_bound_snapshot() -> None:
    event = build_event(event_id="evt_phase6_rollback")
    engine, _, changes, _, _, sandboxes = build_engine(
        event,
        fail_support_verification=True,
    )

    waiting = await engine.process_event(event)
    failed = await engine.resume_approval(approval_callback(waiting))

    assert failed.status is WorkflowRuntimeStatus.FAILED
    assert failed.last_error_code == "SUPPORT_VERIFICATION_FAILED"
    assert all(task.status is WorkflowTaskStatus.ROLLED_BACK for task in failed.tasks)
    assert sandboxes.current_hashes == sandboxes.original_hashes
    assert sandboxes.restored == ["support", "analytics", "crm"]
    assert changes.get(event.tenant_id, derive_change_id(event)).status is WorkflowState.FAILED


@pytest.mark.asyncio
async def test_permanent_event_is_dead_lettered_once_without_retry_loop() -> None:
    event = build_event(event_id="evt_phase6_permanent", event_type="unknown.changed")
    engine, workflows, _, fleet, _, _ = build_engine(event)

    first = await engine.process_event(event)
    duplicate = await engine.process_event(event)
    dead_letters = workflows.list_dead_letters(event.tenant_id, limit=10)

    assert first.status is WorkflowRuntimeStatus.DEAD_LETTERED
    assert duplicate == first
    assert first.delivery_attempts == 1
    assert first.last_error_code == "UNSUPPORTED_EVENT_TYPE"
    assert len(dead_letters) == 1
    assert fleet.calls == 0


@pytest.mark.asyncio
async def test_prompt_injection_is_blocked_and_audited_before_any_tool_call() -> None:
    event = build_event(event_id="evt_phase8_injection")
    engine, workflows, changes, fleet, gateway, _ = build_engine(
        event,
        fleet_error_code="PROMPT_INJECTION_BLOCKED",
    )

    blocked = await engine.process_event(event)

    assert blocked.status is WorkflowRuntimeStatus.FAILED
    assert blocked.last_error_code == "PROMPT_INJECTION_BLOCKED"
    assert fleet.calls == 1
    assert gateway.approval_calls == 0
    assert gateway.attempts == {}
    change = changes.get(event.tenant_id, derive_change_id(event))
    assert change.status is WorkflowState.BLOCKED
    audit = changes.list_audit(event.tenant_id, change.change_id)
    assert any(item.event_type == "SECURITY_PROMPT_INJECTION_BLOCKED" for item in audit)
    assert workflows.list_dead_letters(event.tenant_id, limit=10) == ()
