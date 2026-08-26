"""Firestore emulator integration gate; skipped when the emulator is absent."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
from changeops_persistence import ChangeNotFoundError, FirestoreChangeStateRepository
from google.cloud.firestore_v1 import Client

if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
    pytest.skip("FIRESTORE_EMULATOR_HOST is not configured", allow_module_level=True)


def make_change(tenant_id: str) -> ChangeRecord:
    created_at = datetime.now(UTC) - timedelta(seconds=1)
    return ChangeRecord(
        change_id=f"chg_{uuid4().hex}",
        tenant_id=tenant_id,
        event_id=f"evt_{uuid4().hex}",
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
        created_by="integration-test",
        version=1,
    )


def make_audit(change: ChangeRecord) -> AuditEvent:
    return AuditEvent(
        audit_event_id=f"audit_{uuid4().hex}",
        tenant_id=change.tenant_id,
        change_id=change.change_id,
        trace_id="trace_firestore_001",
        event_type="CHANGE_RECEIVED",
        actor_type=ActorType.SERVICE,
        actor_id="integration-test",
        resource=f"changes/{change.change_id}",
        action="create_change",
        input_hash=sha256_digest({"event_id": change.event_id}),
        output_hash=sha256_digest(change),
        status=AuditStatus.SUCCESS,
        redacted_summary="Change accepted by emulator integration test.",
        created_at=change.created_at,
    )


def repository() -> FirestoreChangeStateRepository:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "changeops-local")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    return FirestoreChangeStateRepository.from_project(project, database)


def test_firestore_state_survives_repository_recreation_and_rejects_cross_tenant_read() -> None:
    tenant_id = f"tenant_{uuid4().hex}"
    change = make_change(tenant_id)
    audit = make_audit(change)
    repository().add_with_audit(change, audit)

    restarted_repository = repository()
    persisted = restarted_repository.get(tenant_id, change.change_id)

    updated_document = persisted.model_dump(mode="python")
    updated_document.update(
        {
            "status": WorkflowState.SCREENING,
            "current_phase": WorkflowState.SCREENING,
            "updated_at": datetime.now(UTC),
            "version": 2,
        }
    )
    updated = ChangeRecord.model_validate(updated_document)
    transition_audit = make_audit(updated).model_copy(
        update={
            "event_type": "WORKFLOW_STATE_TRANSITION_SUCCEEDED",
            "action": "transition_state",
            "created_at": updated.updated_at,
        }
    )
    restarted_repository.commit_transition(updated, transition_audit, expected_version=1)

    second_restart = repository()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "changeops-local")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    raw_change = (
        Client(project=project, database=database)
        .collection("tenants")
        .document(tenant_id)
        .collection("changes")
        .document(change.change_id)
        .get()
        .to_dict()
    )
    after_cursor = second_restart.list_audit_after(
        tenant_id,
        change.change_id,
        after_event_id=audit.audit_event_id,
        limit=10,
    )

    assert persisted.change_id == change.change_id
    assert persisted.created_at.tzinfo is not None
    assert raw_change is not None
    assert isinstance(raw_change["created_at"], datetime)
    assert second_restart.get(tenant_id, change.change_id).version == 2
    assert [event.audit_event_id for event in after_cursor] == [transition_audit.audit_event_id]
    with pytest.raises(ChangeNotFoundError):
        restarted_repository.get("tenant_outside_scope", change.change_id)
