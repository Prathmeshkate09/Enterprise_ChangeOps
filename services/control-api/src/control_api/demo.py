"""Disclosed synthetic change creation for repeatable local gates."""

from datetime import UTC, datetime
from importlib.resources import files

from changeops_contracts import (
    ActorType,
    AuditEvent,
    AuditStatus,
    ChangeRecord,
    WorkflowState,
    sha256_digest,
)

from control_api.models import DemoChangeSeed


def load_demo_seed() -> DemoChangeSeed:
    resource = files("control_api.seed").joinpath("api_breaking_change.json")
    return DemoChangeSeed.model_validate_json(resource.read_text(encoding="utf-8"))


def build_demo_change(
    tenant_id: str,
    *,
    now: datetime | None = None,
) -> tuple[ChangeRecord, AuditEvent]:
    seed = load_demo_seed()
    created_at = now or datetime.now(UTC)
    change = ChangeRecord(
        change_id=seed.change_id,
        tenant_id=tenant_id,
        event_id=seed.event_id,
        change_type=seed.change_type,
        title=seed.title,
        description=seed.description,
        source=seed.source,
        environment=seed.environment,
        status=WorkflowState.RECEIVED,
        risk_level=seed.risk_level,
        current_phase=WorkflowState.RECEIVED,
        workflow_execution_id=None,
        plan_version=0,
        plan_hash=None,
        created_at=created_at,
        updated_at=created_at,
        created_by=seed.created_by,
        version=1,
    )
    audit = AuditEvent(
        audit_event_id=f"audit_{seed.event_id}_received",
        tenant_id=tenant_id,
        change_id=seed.change_id,
        trace_id=seed.trace_id,
        event_type="CHANGE_RECEIVED",
        actor_type=ActorType.SERVICE,
        actor_id=seed.created_by,
        resource=f"changes/{seed.change_id}",
        action="create_change",
        input_hash=sha256_digest({"event_id": seed.event_id, "tenant_id": tenant_id}),
        output_hash=sha256_digest(change),
        status=AuditStatus.SUCCESS,
        redacted_summary="Synthetic API contract change accepted.",
        created_at=created_at,
    )
    return change, audit
