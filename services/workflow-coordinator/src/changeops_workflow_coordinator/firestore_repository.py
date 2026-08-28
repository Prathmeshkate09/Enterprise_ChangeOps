"""Tenant and change scoped Firestore workflow persistence."""

from __future__ import annotations

import re
from typing import Any, cast

from google.cloud import firestore
from google.cloud.firestore_v1 import Client

from changeops_workflow_coordinator.errors import WorkflowConflictError, WorkflowNotFoundError
from changeops_workflow_coordinator.models import DeadLetterRecord, WorkflowExecutionRecord

_DOCUMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")


def _document_id(value: str, field: str) -> str:
    if not _DOCUMENT_ID.fullmatch(value):
        raise ValueError(f"Invalid Firestore {field} document identifier.")
    return value


def _workflow(snapshot: Any) -> WorkflowExecutionRecord:
    document = snapshot.to_dict()
    if document is None:
        raise RuntimeError("Existing workflow snapshot returned no data.")
    return WorkflowExecutionRecord.model_validate(document)


class FirestoreWorkflowRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    @classmethod
    def from_project(cls, project: str, database: str = "(default)") -> FirestoreWorkflowRepository:
        return cls(Client(project=project, database=database))

    def check_ready(self) -> None:
        tuple(self._client.collection("_platform_health").limit(1).stream())

    def create_or_get(self, record: WorkflowExecutionRecord) -> WorkflowExecutionRecord:
        reference = self._reference(
            record.tenant_id, record.change_id, record.workflow_execution_id
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def create(active: Any) -> WorkflowExecutionRecord:
            snapshot = reference.get(transaction=active)
            if snapshot.exists:
                existing = _workflow(snapshot)
                if existing.event_id != record.event_id:
                    raise WorkflowConflictError("Workflow identifier collision.")
                return existing
            document = record.model_dump(mode="json")
            document["started_at"] = firestore.SERVER_TIMESTAMP
            document["updated_at"] = firestore.SERVER_TIMESTAMP
            active.create(reference, document)
            return record

        return cast(WorkflowExecutionRecord, create(transaction))

    def get(
        self, tenant_id: str, change_id: str, workflow_execution_id: str
    ) -> WorkflowExecutionRecord:
        snapshot = self._reference(tenant_id, change_id, workflow_execution_id).get()
        if not snapshot.exists:
            raise WorkflowNotFoundError
        return _workflow(snapshot)

    def update(
        self, record: WorkflowExecutionRecord, *, expected_version: int
    ) -> WorkflowExecutionRecord:
        reference = self._reference(
            record.tenant_id, record.change_id, record.workflow_execution_id
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def update_workflow(active: Any) -> WorkflowExecutionRecord:
            snapshot = reference.get(transaction=active)
            if not snapshot.exists:
                raise WorkflowNotFoundError
            current = _workflow(snapshot)
            if current.version != expected_version or record.version != expected_version + 1:
                raise WorkflowConflictError
            document = record.model_dump(mode="json")
            document["started_at"] = current.started_at
            document["updated_at"] = firestore.SERVER_TIMESTAMP
            active.set(reference, document)
            return record

        return cast(WorkflowExecutionRecord, update_workflow(transaction))

    def record_dead_letter(self, record: DeadLetterRecord) -> DeadLetterRecord:
        reference = self._dead_letter_reference(record.tenant_id, record.dead_letter_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def create(active: Any) -> DeadLetterRecord:
            snapshot = reference.get(transaction=active)
            if snapshot.exists:
                document = snapshot.to_dict()
                if document is None:
                    raise RuntimeError("Existing dead-letter snapshot returned no data.")
                existing = DeadLetterRecord.model_validate(document)
                if existing.input_hash != record.input_hash:
                    raise WorkflowConflictError("Dead-letter identifier collision.")
                return existing
            document = record.model_dump(mode="json")
            document["created_at"] = firestore.SERVER_TIMESTAMP
            active.create(reference, document)
            return record

        return cast(DeadLetterRecord, create(transaction))

    def list_dead_letters(self, tenant_id: str, *, limit: int) -> tuple[DeadLetterRecord, ...]:
        tenant_id = _document_id(tenant_id, "tenant_id")
        snapshots = (
            self._client.collection("tenants")
            .document(tenant_id)
            .collection("dead_letters")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        records: list[DeadLetterRecord] = []
        for snapshot in snapshots:
            document = snapshot.to_dict()
            if document is None:
                raise RuntimeError("Existing dead-letter snapshot returned no data.")
            records.append(DeadLetterRecord.model_validate(document))
        return tuple(records)

    def _reference(self, tenant_id: str, change_id: str, workflow_id: str) -> Any:
        return (
            self._client.collection("tenants")
            .document(_document_id(tenant_id, "tenant_id"))
            .collection("changes")
            .document(_document_id(change_id, "change_id"))
            .collection("workflows")
            .document(_document_id(workflow_id, "workflow_execution_id"))
        )

    def _dead_letter_reference(self, tenant_id: str, dead_letter_id: str) -> Any:
        return (
            self._client.collection("tenants")
            .document(_document_id(tenant_id, "tenant_id"))
            .collection("dead_letters")
            .document(_document_id(dead_letter_id, "dead_letter_id"))
        )
