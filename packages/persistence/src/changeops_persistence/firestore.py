"""Google Cloud Firestore operational-state adapter."""

from __future__ import annotations

import re
from typing import Any

from changeops_contracts import AuditEvent, ChangeRecord
from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore
from google.cloud.firestore_v1 import Client
from google.cloud.firestore_v1.base_document import DocumentSnapshot
from google.cloud.firestore_v1.field_path import FieldPath

from changeops_persistence.errors import (
    AuditCursorNotFoundError,
    AuditEventAlreadyExistsError,
    ChangeAlreadyExistsError,
    ChangeNotFoundError,
    InvalidDocumentIdentifierError,
    OptimisticConcurrencyError,
    TenantScopeViolationError,
)

_DOCUMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")


def _validate_document_id(value: str, field_name: str) -> str:
    if not _DOCUMENT_ID.fullmatch(value):
        raise InvalidDocumentIdentifierError(field_name)
    return value


def _change_from_snapshot(snapshot: DocumentSnapshot) -> ChangeRecord:
    document = snapshot.to_dict()
    if document is None:
        raise RuntimeError("Existing Firestore change snapshot returned no document data.")
    return ChangeRecord.model_validate(document)


def _audit_from_snapshot(snapshot: DocumentSnapshot) -> AuditEvent:
    document = snapshot.to_dict()
    if document is None:
        raise RuntimeError("Existing Firestore audit snapshot returned no document data.")
    return AuditEvent.model_validate(document)


def _change_document(change: ChangeRecord, *, server_created_at: bool) -> dict[str, Any]:
    document: dict[str, Any] = change.model_dump(mode="json")
    if server_created_at:
        document["created_at"] = firestore.SERVER_TIMESTAMP
    else:
        document["created_at"] = change.created_at
    document["updated_at"] = firestore.SERVER_TIMESTAMP
    return document


def _audit_document(audit_event: AuditEvent) -> dict[str, Any]:
    document: dict[str, Any] = audit_event.model_dump(mode="json")
    document["created_at"] = firestore.SERVER_TIMESTAMP
    return document


class FirestoreChangeStateRepository:
    """Tenant-partitioned Firestore adapter with transactional audit writes."""

    def __init__(self, client: Client) -> None:
        self._client = client

    @classmethod
    def from_project(
        cls, project: str, database: str = "(default)"
    ) -> FirestoreChangeStateRepository:
        return cls(Client(project=project, database=database))

    def check_ready(self) -> None:
        tuple(self._client.collection("_platform_health").limit(1).stream())

    def add(self, change: ChangeRecord) -> None:
        reference = self._change_reference(change.tenant_id, change.change_id)
        try:
            reference.create(_change_document(change, server_created_at=True))
        except AlreadyExists as error:
            raise ChangeAlreadyExistsError(change.tenant_id, change.change_id) from error

    def add_with_audit(self, change: ChangeRecord, audit_event: AuditEvent) -> None:
        self._validate_audit_scope(change, audit_event)
        change_reference = self._change_reference(change.tenant_id, change.change_id)
        audit_reference = self._audit_reference(
            change.tenant_id,
            change.change_id,
            audit_event.audit_event_id,
        )
        index_reference = self._audit_index_reference(
            change.tenant_id,
            audit_event.audit_event_id,
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def create_change(active_transaction: Any) -> None:
            change_snapshot = change_reference.get(transaction=active_transaction)
            audit_snapshot = audit_reference.get(transaction=active_transaction)
            if change_snapshot.exists:
                raise ChangeAlreadyExistsError(change.tenant_id, change.change_id)
            if audit_snapshot.exists:
                raise AuditEventAlreadyExistsError(
                    audit_event.tenant_id,
                    audit_event.audit_event_id,
                )
            active_transaction.create(
                change_reference,
                _change_document(change, server_created_at=True),
            )
            document = _audit_document(audit_event)
            active_transaction.create(audit_reference, document)
            active_transaction.create(index_reference, document)

        create_change(transaction)

    def get(self, tenant_id: str, change_id: str) -> ChangeRecord:
        snapshot = self._change_reference(tenant_id, change_id).get()
        if not snapshot.exists:
            raise ChangeNotFoundError(tenant_id, change_id)
        return _change_from_snapshot(snapshot)

    def list_changes(self, tenant_id: str, *, limit: int) -> tuple[ChangeRecord, ...]:
        tenant_id = _validate_document_id(tenant_id, "tenant_id")
        query = (
            self._client.collection("tenants")
            .document(tenant_id)
            .collection("changes")
            .order_by("updated_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return tuple(_change_from_snapshot(snapshot) for snapshot in query.stream())

    def commit_transition(
        self,
        change: ChangeRecord,
        audit_event: AuditEvent,
        *,
        expected_version: int,
    ) -> None:
        self._validate_audit_scope(change, audit_event)
        change_reference = self._change_reference(change.tenant_id, change.change_id)
        audit_reference = self._audit_reference(
            change.tenant_id,
            change.change_id,
            audit_event.audit_event_id,
        )
        index_reference = self._audit_index_reference(
            change.tenant_id,
            audit_event.audit_event_id,
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def apply_transition(active_transaction: Any) -> None:
            current_snapshot = change_reference.get(transaction=active_transaction)
            audit_snapshot = audit_reference.get(transaction=active_transaction)
            if not current_snapshot.exists:
                raise ChangeNotFoundError(change.tenant_id, change.change_id)
            if audit_snapshot.exists:
                raise AuditEventAlreadyExistsError(
                    audit_event.tenant_id,
                    audit_event.audit_event_id,
                )
            current = _change_from_snapshot(current_snapshot)
            if current.version != expected_version:
                raise OptimisticConcurrencyError(
                    change.change_id,
                    expected_version,
                    current.version,
                )
            if change.version != expected_version + 1:
                raise OptimisticConcurrencyError(
                    change.change_id,
                    expected_version + 1,
                    change.version,
                )
            active_transaction.set(
                change_reference,
                _change_document(change, server_created_at=False),
            )
            document = _audit_document(audit_event)
            active_transaction.create(audit_reference, document)
            active_transaction.create(index_reference, document)

        apply_transition(transaction)

    def record_audit(self, audit_event: AuditEvent) -> None:
        change_reference = self._change_reference(audit_event.tenant_id, audit_event.change_id)
        audit_reference = self._audit_reference(
            audit_event.tenant_id,
            audit_event.change_id,
            audit_event.audit_event_id,
        )
        index_reference = self._audit_index_reference(
            audit_event.tenant_id,
            audit_event.audit_event_id,
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def append_audit(active_transaction: Any) -> None:
            change_snapshot = change_reference.get(transaction=active_transaction)
            audit_snapshot = audit_reference.get(transaction=active_transaction)
            if not change_snapshot.exists:
                raise ChangeNotFoundError(audit_event.tenant_id, audit_event.change_id)
            if audit_snapshot.exists:
                raise AuditEventAlreadyExistsError(
                    audit_event.tenant_id,
                    audit_event.audit_event_id,
                )
            document = _audit_document(audit_event)
            active_transaction.create(audit_reference, document)
            active_transaction.create(index_reference, document)

        append_audit(transaction)

    def list_audit(self, tenant_id: str, change_id: str) -> tuple[AuditEvent, ...]:
        return self.list_audit_after(
            tenant_id,
            change_id,
            after_event_id=None,
            limit=10_000,
        )

    def list_audit_after(
        self,
        tenant_id: str,
        change_id: str,
        *,
        after_event_id: str | None,
        limit: int,
    ) -> tuple[AuditEvent, ...]:
        self.get(tenant_id, change_id)
        collection = self._audit_collection(tenant_id, change_id)
        query = collection.order_by("created_at").order_by(FieldPath.document_id())
        if after_event_id is not None:
            cursor = self._audit_reference(tenant_id, change_id, after_event_id).get()
            if not cursor.exists:
                raise AuditCursorNotFoundError(tenant_id, change_id, after_event_id)
            query = query.start_after(cursor)
        return tuple(_audit_from_snapshot(snapshot) for snapshot in query.limit(limit).stream())

    def list_tenant_audit(self, tenant_id: str, *, limit: int) -> tuple[AuditEvent, ...]:
        tenant_id = _validate_document_id(tenant_id, "tenant_id")
        query = (
            self._client.collection("tenants")
            .document(tenant_id)
            .collection("audit_index")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return tuple(_audit_from_snapshot(snapshot) for snapshot in query.stream())

    def _change_reference(self, tenant_id: str, change_id: str) -> Any:
        tenant_id = _validate_document_id(tenant_id, "tenant_id")
        change_id = _validate_document_id(change_id, "change_id")
        return (
            self._client.collection("tenants")
            .document(tenant_id)
            .collection("changes")
            .document(change_id)
        )

    def _audit_collection(self, tenant_id: str, change_id: str) -> Any:
        return self._change_reference(tenant_id, change_id).collection("audit")

    def _audit_reference(self, tenant_id: str, change_id: str, audit_event_id: str) -> Any:
        audit_event_id = _validate_document_id(audit_event_id, "audit_event_id")
        return self._audit_collection(tenant_id, change_id).document(audit_event_id)

    def _audit_index_reference(self, tenant_id: str, audit_event_id: str) -> Any:
        tenant_id = _validate_document_id(tenant_id, "tenant_id")
        audit_event_id = _validate_document_id(audit_event_id, "audit_event_id")
        return (
            self._client.collection("tenants")
            .document(tenant_id)
            .collection("audit_index")
            .document(audit_event_id)
        )

    @staticmethod
    def _validate_audit_scope(change: ChangeRecord, audit_event: AuditEvent) -> None:
        if audit_event.tenant_id != change.tenant_id or audit_event.change_id != change.change_id:
            raise TenantScopeViolationError(audit_event.tenant_id, audit_event.change_id)
