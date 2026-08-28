"""Firestore governance adapter with transactional approval and idempotency state."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, cast

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
from google.cloud import firestore
from google.cloud.firestore_v1 import Client
from google.cloud.firestore_v1.base_document import DocumentSnapshot
from pydantic import BaseModel, JsonValue

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
from changeops_tool_gateway.repository import same_approval_decision, same_approval_request

_DOCUMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")


def _document_id(value: str, field_name: str) -> str:
    if not _DOCUMENT_ID.fullmatch(value):
        raise GatewayConflictError(f"{field_name} is not a valid document identifier.")
    return value


def _from_snapshot[ModelT: BaseModel](snapshot: DocumentSnapshot, model: type[ModelT]) -> ModelT:
    document = snapshot.to_dict()
    if document is None:
        raise RuntimeError("Existing Firestore governance snapshot returned no document data.")
    document.pop("raw_idempotency_key", None)
    return model.model_validate(document)


def _approval_document(
    record: ApprovalRequestRecord, *, server_requested_at: bool
) -> dict[str, Any]:
    document: dict[str, Any] = record.model_dump(mode="json")
    document["requested_at"] = (
        firestore.SERVER_TIMESTAMP if server_requested_at else record.requested_at
    )
    if record.decided_at is not None:
        document["decided_at"] = firestore.SERVER_TIMESTAMP
    return document


def _execution_document(record: ToolExecutionRecord) -> dict[str, Any]:
    document: dict[str, Any] = record.model_dump(mode="json")
    document["created_at"] = record.created_at
    document["updated_at"] = firestore.SERVER_TIMESTAMP
    return document


class FirestoreGovernanceRepository:
    """Tenant-partitioned durable Phase 5 governance state."""

    def __init__(self, client: Client) -> None:
        self._client = client

    @classmethod
    def from_project(
        cls, project: str, database: str = "(default)"
    ) -> FirestoreGovernanceRepository:
        return cls(Client(project=project, database=database))

    def check_ready(self) -> None:
        tuple(self._client.collection("_platform_health").limit(1).stream())

    def create_approval_request(
        self, *, record: ApprovalRequestRecord, plan: RemediationPlan
    ) -> ApprovalRequestRecord:
        if calculate_plan_hash(plan) != record.plan_hash:
            raise GatewayConflictError("Approval request plan hash is not canonical.")
        plan_reference = self._plan_reference(plan.tenant_id, plan.change_id, plan.plan_id)
        approval_reference = self._approval_reference(
            record.tenant_id, record.change_id, record.approval_id
        )
        approval_index_reference = self._approval_index_reference(
            record.tenant_id, record.approval_id
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def create(active_transaction: Any) -> ApprovalRequestRecord:
            plan_snapshot = plan_reference.get(transaction=active_transaction)
            approval_snapshot = approval_reference.get(transaction=active_transaction)
            approval_index_snapshot = approval_index_reference.get(transaction=active_transaction)
            existing_plan: RemediationPlan | None = None
            if plan_snapshot.exists:
                existing_plan = _from_snapshot(plan_snapshot, RemediationPlan)
                if calculate_plan_hash(existing_plan) != record.plan_hash:
                    raise GatewayConflictError(
                        "A different plan already uses this plan identifier."
                    )
            if approval_snapshot.exists or approval_index_snapshot.exists:
                if not (approval_snapshot.exists and approval_index_snapshot.exists):
                    raise RuntimeError("Approval request indexes are inconsistent.")
                existing_approval = _from_snapshot(approval_snapshot, ApprovalRequestRecord)
                indexed_approval = _from_snapshot(approval_index_snapshot, ApprovalRequestRecord)
                if existing_approval != indexed_approval:
                    raise RuntimeError("Approval index diverged from the authoritative record.")
                if existing_plan == plan and same_approval_request(existing_approval, record):
                    return existing_approval
                raise GatewayConflictError("Approval request identifier already exists.")
            if not plan_snapshot.exists:
                active_transaction.create(
                    plan_reference,
                    plan.model_dump(mode="json"),
                )
            document = _approval_document(record, server_requested_at=True)
            active_transaction.create(approval_reference, document)
            active_transaction.create(approval_index_reference, document)
            return record

        return cast(ApprovalRequestRecord, create(transaction))

    def get_plan(self, tenant_id: str, change_id: str, plan_id: str) -> RemediationPlan:
        snapshot = self._plan_reference(tenant_id, change_id, plan_id).get()
        if not snapshot.exists:
            raise GatewayNotFoundError("plan")
        return _from_snapshot(snapshot, RemediationPlan)

    def get_approval_request(self, tenant_id: str, approval_id: str) -> ApprovalRequestRecord:
        snapshot = self._approval_index_reference(tenant_id, approval_id).get()
        if not snapshot.exists:
            raise GatewayNotFoundError("approval")
        return _from_snapshot(snapshot, ApprovalRequestRecord)

    def list_approval_requests(
        self, tenant_id: str, *, limit: int
    ) -> tuple[ApprovalRequestRecord, ...]:
        query = (
            self._approval_index_collection(tenant_id)
            .order_by("requested_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return tuple(_from_snapshot(snapshot, ApprovalRequestRecord) for snapshot in query.stream())

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
        index_reference = self._approval_index_reference(tenant_id, approval_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def decide(active_transaction: Any) -> ApprovalRequestRecord:
            index_snapshot = index_reference.get(transaction=active_transaction)
            if not index_snapshot.exists:
                raise GatewayNotFoundError("approval")
            indexed = _from_snapshot(index_snapshot, ApprovalRequestRecord)
            reference = self._approval_reference(tenant_id, indexed.change_id, approval_id)
            snapshot = reference.get(transaction=active_transaction)
            if not snapshot.exists:
                raise RuntimeError("Approval index points to a missing authoritative record.")
            current = _from_snapshot(snapshot, ApprovalRequestRecord)
            if current != indexed:
                raise RuntimeError("Approval index diverged from the authoritative record.")
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
            active_transaction.set(
                reference,
                _approval_document(updated, server_requested_at=False),
            )
            active_transaction.set(
                index_reference,
                _approval_document(updated, server_requested_at=False),
            )
            return updated

        return cast(ApprovalRequestRecord, decide(transaction))

    def reserve_execution(
        self,
        *,
        intent: ToolIntent,
        decision: PolicyDecision,
        approval: Approval | None,
        input_hash: str,
        now: datetime,
    ) -> ExecutionReservation:
        digest = sha256_digest({"tenant_id": intent.tenant_id, "key": intent.idempotency_key})
        execution_id = f"execution_{digest[7:31]}"
        idempotency_reference = self._idempotency_reference(intent.tenant_id, digest[7:])
        execution_reference = self._execution_reference(
            intent.tenant_id, intent.change_id, execution_id
        )
        approval_reference = (
            self._approval_reference(intent.tenant_id, intent.change_id, approval.approval_id)
            if approval is not None
            else None
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def reserve(active_transaction: Any) -> ExecutionReservation:
            existing_snapshot = idempotency_reference.get(transaction=active_transaction)
            if decision.approval_required:
                if approval is None or approval_reference is None:
                    raise ApprovalRequiredError
                approval_snapshot = approval_reference.get(transaction=active_transaction)
                if not approval_snapshot.exists:
                    raise ApprovalRequiredError
                current_approval = _from_snapshot(
                    approval_snapshot, ApprovalRequestRecord
                ).as_approval()
                if (
                    current_approval is None
                    or current_approval != approval
                    or current_approval.expires_at <= now
                    or intent.step_id not in current_approval.scope
                    or current_approval.plan_hash != intent.plan_hash
                ):
                    raise ApprovalRequiredError
            if existing_snapshot.exists:
                existing = _from_snapshot(existing_snapshot, ToolExecutionRecord)
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
                record = ToolExecutionRecord.model_validate(
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
            else:
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
            document = _execution_document(record)
            idempotency_document = {
                **document,
                "raw_idempotency_key": intent.idempotency_key,
            }
            active_transaction.set(execution_reference, document)
            active_transaction.set(idempotency_reference, idempotency_document)
            return ExecutionReservation(record=record, replayed=False)

        return cast(ExecutionReservation, reserve(transaction))

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
        return self._finish_execution(
            tenant_id=tenant_id,
            change_id=change_id,
            execution_id=execution_id,
            output=output,
            output_hash=output_hash,
            error_code=None,
            completed_at=completed_at,
        )

    def fail_execution(
        self,
        *,
        tenant_id: str,
        change_id: str,
        execution_id: str,
        error_code: str,
        failed_at: datetime,
    ) -> ToolExecutionRecord:
        return self._finish_execution(
            tenant_id=tenant_id,
            change_id=change_id,
            execution_id=execution_id,
            output=None,
            output_hash=None,
            error_code=error_code,
            completed_at=failed_at,
        )

    def _finish_execution(
        self,
        *,
        tenant_id: str,
        change_id: str,
        execution_id: str,
        output: dict[str, JsonValue] | None,
        output_hash: str | None,
        error_code: str | None,
        completed_at: datetime,
    ) -> ToolExecutionRecord:
        execution_reference = self._execution_reference(tenant_id, change_id, execution_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def finish(active_transaction: Any) -> ToolExecutionRecord:
            snapshot = execution_reference.get(transaction=active_transaction)
            if not snapshot.exists:
                raise GatewayNotFoundError("tool execution")
            current = _from_snapshot(snapshot, ToolExecutionRecord)
            if current.status is not ToolExecutionStatus.RESERVED:
                raise GatewayConflictError("Tool execution is not reserved.")
            status_value = (
                ToolExecutionStatus.SUCCEEDED if error_code is None else ToolExecutionStatus.FAILED
            )
            updated = ToolExecutionRecord.model_validate(
                {
                    **current.model_dump(mode="python"),
                    "status": status_value,
                    "output": output,
                    "output_hash": output_hash,
                    "error_code": error_code,
                    "updated_at": completed_at,
                }
            )
            digest = sha256_digest({"tenant_id": tenant_id, "key": current.idempotency_key})
            idempotency_reference = self._idempotency_reference(tenant_id, digest[7:])
            document = _execution_document(updated)
            active_transaction.set(execution_reference, document)
            active_transaction.set(
                idempotency_reference,
                {**document, "raw_idempotency_key": current.idempotency_key},
            )
            return updated

        return cast(ToolExecutionRecord, finish(transaction))

    def record_audit(self, event: AuditEvent) -> None:
        audit_reference = self._audit_reference(
            event.tenant_id, event.change_id, event.audit_event_id
        )
        index_reference = self._audit_index_reference(event.tenant_id, event.audit_event_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def append(active_transaction: Any) -> None:
            audit_snapshot = audit_reference.get(transaction=active_transaction)
            if audit_snapshot.exists:
                raise GatewayConflictError("Audit event identifier already exists.")
            document = event.model_dump(mode="json")
            document["created_at"] = firestore.SERVER_TIMESTAMP
            active_transaction.create(audit_reference, document)
            active_transaction.create(index_reference, document)

        append(transaction)

    def list_audit(self, tenant_id: str, *, limit: int) -> tuple[AuditEvent, ...]:
        tenant_id = _document_id(tenant_id, "tenant_id")
        query = (
            self._client.collection("tenants")
            .document(tenant_id)
            .collection("audit_index")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return tuple(_from_snapshot(snapshot, AuditEvent) for snapshot in query.stream())

    def _tenant_reference(self, tenant_id: str) -> Any:
        return self._client.collection("tenants").document(_document_id(tenant_id, "tenant_id"))

    def _change_reference(self, tenant_id: str, change_id: str) -> Any:
        return (
            self._tenant_reference(tenant_id)
            .collection("changes")
            .document(_document_id(change_id, "change_id"))
        )

    def _plan_reference(self, tenant_id: str, change_id: str, plan_id: str) -> Any:
        return (
            self._change_reference(tenant_id, change_id)
            .collection("plans")
            .document(_document_id(plan_id, "plan_id"))
        )

    def _approval_reference(self, tenant_id: str, change_id: str, approval_id: str) -> Any:
        return (
            self._change_reference(tenant_id, change_id)
            .collection("approvals")
            .document(_document_id(approval_id, "approval_id"))
        )

    def _approval_index_collection(self, tenant_id: str) -> Any:
        return self._tenant_reference(tenant_id).collection("approval_index")

    def _approval_index_reference(self, tenant_id: str, approval_id: str) -> Any:
        return self._approval_index_collection(tenant_id).document(
            _document_id(approval_id, "approval_id")
        )

    def _execution_reference(self, tenant_id: str, change_id: str, execution_id: str) -> Any:
        return (
            self._change_reference(tenant_id, change_id)
            .collection("tool_executions")
            .document(_document_id(execution_id, "execution_id"))
        )

    def _idempotency_reference(self, tenant_id: str, digest: str) -> Any:
        return (
            self._tenant_reference(tenant_id)
            .collection("idempotency_keys")
            .document(_document_id(digest, "idempotency_digest"))
        )

    def _audit_reference(self, tenant_id: str, change_id: str, audit_event_id: str) -> Any:
        return (
            self._change_reference(tenant_id, change_id)
            .collection("audit")
            .document(_document_id(audit_event_id, "audit_event_id"))
        )

    def _audit_index_reference(self, tenant_id: str, audit_event_id: str) -> Any:
        return (
            self._tenant_reference(tenant_id)
            .collection("audit_index")
            .document(_document_id(audit_event_id, "audit_event_id"))
        )
