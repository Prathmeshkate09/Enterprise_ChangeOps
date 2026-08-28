"""Transactional event inbox repository port and memory adapter."""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import RLock
from typing import Protocol

from changeops_contracts import ChangeEvent, sha256_digest

from changeops_event_gateway.errors import EventConflictError
from changeops_event_gateway.models import (
    EventInboxRecord,
    InboxAcceptance,
    InboxStatus,
)


def event_key(event: ChangeEvent) -> str:
    return sha256_digest(
        {
            "event_id": event.event_id,
            "source": event.source.type,
            "tenant_id": event.tenant_id,
        }
    ).removeprefix("sha256:")


class EventInboxRepository(Protocol):
    def check_ready(self) -> None: ...

    def accept(self, *, event: ChangeEvent, change_id: str, now: datetime) -> InboxAcceptance: ...

    def reserve_publish(
        self, *, tenant_id: str, key: str, now: datetime
    ) -> EventInboxRecord | None: ...

    def mark_published(
        self,
        *,
        tenant_id: str,
        key: str,
        expected_version: int,
        message_id: str,
        now: datetime,
    ) -> EventInboxRecord: ...

    def mark_publish_failed(
        self,
        *,
        tenant_id: str,
        key: str,
        expected_version: int,
        error_code: str,
        now: datetime,
    ) -> EventInboxRecord: ...


class InMemoryEventInboxRepository:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], EventInboxRecord] = {}
        self._lock = RLock()

    def check_ready(self) -> None:
        return None

    def accept(self, *, event: ChangeEvent, change_id: str, now: datetime) -> InboxAcceptance:
        key = event_key(event)
        input_hash = sha256_digest(event)
        storage_key = (event.tenant_id, key)
        with self._lock:
            existing = self._records.get(storage_key)
            if existing is not None:
                if existing.input_hash != input_hash:
                    raise EventConflictError
                return InboxAcceptance(record=existing, replayed=True)
            record = EventInboxRecord(
                event_key=key,
                tenant_id=event.tenant_id,
                event_id=event.event_id,
                source_type=event.source.type,
                change_id=change_id,
                input_hash=input_hash,
                event=event,
                status=InboxStatus.PENDING,
                publish_attempts=0,
                processing_attempts=0,
                created_at=now,
                updated_at=now,
                version=1,
            )
            self._records[storage_key] = record
            return InboxAcceptance(record=record, replayed=False)

    def reserve_publish(
        self, *, tenant_id: str, key: str, now: datetime
    ) -> EventInboxRecord | None:
        with self._lock:
            current = self._records[(tenant_id, key)]
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
            self._records[(tenant_id, key)] = updated
            return updated

    def mark_published(
        self,
        *,
        tenant_id: str,
        key: str,
        expected_version: int,
        message_id: str,
        now: datetime,
    ) -> EventInboxRecord:
        return self._finish_publish(
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
        return self._finish_publish(
            tenant_id=tenant_id,
            key=key,
            expected_version=expected_version,
            status=InboxStatus.PUBLISH_FAILED,
            message_id=None,
            error_code=error_code,
            now=now,
        )

    def _finish_publish(
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
        with self._lock:
            current = self._records[(tenant_id, key)]
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
            self._records[(tenant_id, key)] = updated
            return updated
