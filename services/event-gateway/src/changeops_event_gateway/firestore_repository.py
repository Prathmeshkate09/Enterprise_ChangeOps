"""Tenant-partitioned Firestore event inbox adapter."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, cast

from changeops_contracts import ChangeEvent, sha256_digest
from google.cloud import firestore
from google.cloud.firestore_v1 import Client

from changeops_event_gateway.errors import EventConflictError
from changeops_event_gateway.models import EventInboxRecord, InboxAcceptance, InboxStatus
from changeops_event_gateway.repository import event_key

_DOCUMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")


def _document_id(value: str, field: str) -> str:
    if not _DOCUMENT_ID.fullmatch(value):
        raise ValueError(f"Invalid Firestore {field} document identifier.")
    return value


def _from_snapshot(snapshot: Any) -> EventInboxRecord:
    document = snapshot.to_dict()
    if document is None:
        raise RuntimeError("Existing event inbox snapshot returned no data.")
    return EventInboxRecord.model_validate(document)


class FirestoreEventInboxRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    @classmethod
    def from_project(
        cls, project: str, database: str = "(default)"
    ) -> FirestoreEventInboxRepository:
        return cls(Client(project=project, database=database))

    def check_ready(self) -> None:
        tuple(self._client.collection("_platform_health").limit(1).stream())

    def accept(self, *, event: ChangeEvent, change_id: str, now: datetime) -> InboxAcceptance:
        key = event_key(event)
        reference = self._reference(event.tenant_id, key)
        transaction = self._client.transaction()
        created = EventInboxRecord(
            event_key=key,
            tenant_id=event.tenant_id,
            event_id=event.event_id,
            source_type=event.source.type,
            change_id=change_id,
            input_hash=sha256_digest(event),
            event=event,
            status=InboxStatus.PENDING,
            publish_attempts=0,
            processing_attempts=0,
            created_at=now,
            updated_at=now,
            version=1,
        )

        @firestore.transactional
        def accept_event(active: Any) -> tuple[EventInboxRecord, bool]:
            snapshot = reference.get(transaction=active)
            if snapshot.exists:
                existing = _from_snapshot(snapshot)
                if existing.input_hash != created.input_hash:
                    raise EventConflictError
                return existing, True
            document = created.model_dump(mode="json")
            document["created_at"] = firestore.SERVER_TIMESTAMP
            document["updated_at"] = firestore.SERVER_TIMESTAMP
            active.create(reference, document)
            return created, False

        record, replayed = accept_event(transaction)
        return InboxAcceptance(record=record, replayed=replayed)

    def reserve_publish(
        self, *, tenant_id: str, key: str, now: datetime
    ) -> EventInboxRecord | None:
        reference = self._reference(tenant_id, key)
        transaction = self._client.transaction()

        @firestore.transactional
        def reserve(active: Any) -> EventInboxRecord | None:
            snapshot = reference.get(transaction=active)
            if not snapshot.exists:
                raise RuntimeError("Event inbox record disappeared before publication.")
            current = _from_snapshot(snapshot)
            if current.status is InboxStatus.PUBLISHED:
                return None
            if current.status is InboxStatus.PUBLISHING and current.updated_at > now - timedelta(
                seconds=30
            ):
                return None
            updated = EventInboxRecord.model_validate(
                {
                    **current.model_dump(mode="python"),
                    "status": InboxStatus.PUBLISHING,
                    "publish_attempts": current.publish_attempts + 1,
                    "last_error_code": None,
                    "updated_at": now,
                    "version": current.version + 1,
                }
            )
            document = updated.model_dump(mode="json")
            document["updated_at"] = firestore.SERVER_TIMESTAMP
            active.set(reference, document)
            return updated

        return cast(EventInboxRecord | None, reserve(transaction))

    def mark_published(
        self,
        *,
        tenant_id: str,
        key: str,
        expected_version: int,
        message_id: str,
        now: datetime,
    ) -> EventInboxRecord:
        return self._finish(
            tenant_id=tenant_id,
            key=key,
            expected_version=expected_version,
            status=InboxStatus.PUBLISHED,
            message_id=message_id,
            error_code=None,
            now=now,
        )

    def mark_publish_failed(
        self,
        *,
        tenant_id: str,
        key: str,
        expected_version: int,
        error_code: str,
        now: datetime,
    ) -> EventInboxRecord:
        return self._finish(
            tenant_id=tenant_id,
            key=key,
            expected_version=expected_version,
            status=InboxStatus.PUBLISH_FAILED,
            message_id=None,
            error_code=error_code,
            now=now,
        )

    def _finish(
        self,
        *,
        tenant_id: str,
        key: str,
        expected_version: int,
        status: InboxStatus,
        message_id: str | None,
        error_code: str | None,
        now: datetime,
    ) -> EventInboxRecord:
        reference = self._reference(tenant_id, key)
        transaction = self._client.transaction()

        @firestore.transactional
        def finish(active: Any) -> EventInboxRecord:
            snapshot = reference.get(transaction=active)
            if not snapshot.exists:
                raise RuntimeError("Event inbox record disappeared during publication.")
            current = _from_snapshot(snapshot)
            if current.version != expected_version or current.status is not InboxStatus.PUBLISHING:
                raise RuntimeError("Event publish reservation is stale.")
            updated = EventInboxRecord.model_validate(
                {
                    **current.model_dump(mode="python"),
                    "status": status,
                    "pubsub_message_id": message_id,
                    "last_error_code": error_code,
                    "updated_at": now,
                    "version": current.version + 1,
                }
            )
            document = updated.model_dump(mode="json")
            document["updated_at"] = firestore.SERVER_TIMESTAMP
            active.set(reference, document)
            return updated

        return cast(EventInboxRecord, finish(transaction))

    def _reference(self, tenant_id: str, key: str) -> Any:
        return (
            self._client.collection("tenants")
            .document(_document_id(tenant_id, "tenant_id"))
            .collection("processed_events")
            .document(_document_id(key, "event_key"))
        )
