"""Thread-safe in-memory repository used by local execution and unit tests."""

from __future__ import annotations

from collections import defaultdict
from threading import RLock

from changeops_contracts import AuditEvent, ChangeRecord

from changeops_persistence.errors import (
    AuditCursorNotFoundError,
    AuditEventAlreadyExistsError,
    ChangeAlreadyExistsError,
    ChangeNotFoundError,
    OptimisticConcurrencyError,
    TenantScopeViolationError,
)


class InMemoryChangeStateRepository:
    """Store tenant-scoped records and atomically pair transitions with audits."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._changes: dict[tuple[str, str], ChangeRecord] = {}
        self._tenants_by_change_id: dict[str, set[str]] = defaultdict(set)
        self._audit: dict[tuple[str, str], AuditEvent] = {}
        self._audit_ids_by_change: dict[tuple[str, str], list[str]] = defaultdict(list)

    def check_ready(self) -> None:
        return None

    def add(self, change: ChangeRecord) -> None:
        key = (change.tenant_id, change.change_id)
        with self._lock:
            if key in self._changes:
                raise ChangeAlreadyExistsError(*key)
            self._changes[key] = change
            self._tenants_by_change_id[change.change_id].add(change.tenant_id)

    def add_with_audit(self, change: ChangeRecord, audit_event: AuditEvent) -> None:
        key = (change.tenant_id, change.change_id)
        with self._lock:
            if key in self._changes:
                raise ChangeAlreadyExistsError(*key)
            self._validate_audit_scope(change, audit_event)
            self._ensure_new_audit_id(audit_event)
            self._changes[key] = change
            self._tenants_by_change_id[change.change_id].add(change.tenant_id)
            self._append_audit_unlocked(audit_event)

    def get(self, tenant_id: str, change_id: str) -> ChangeRecord:
        with self._lock:
            return self._get_unlocked(tenant_id, change_id)

    def list_changes(self, tenant_id: str, *, limit: int) -> tuple[ChangeRecord, ...]:
        with self._lock:
            changes = [change for (owner, _), change in self._changes.items() if owner == tenant_id]
            changes.sort(key=lambda change: (change.updated_at, change.change_id), reverse=True)
            return tuple(changes[:limit])

    def commit_transition(
        self,
        change: ChangeRecord,
        audit_event: AuditEvent,
        *,
        expected_version: int,
    ) -> None:
        key = (change.tenant_id, change.change_id)
        with self._lock:
            current = self._get_unlocked(*key)
            self._validate_audit_scope(change, audit_event)
            self._ensure_new_audit_id(audit_event)
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
            self._changes[key] = change
            self._append_audit_unlocked(audit_event)

    def record_audit(self, audit_event: AuditEvent) -> None:
        with self._lock:
            self._get_unlocked(audit_event.tenant_id, audit_event.change_id)
            self._ensure_new_audit_id(audit_event)
            self._append_audit_unlocked(audit_event)

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
        with self._lock:
            self._get_unlocked(tenant_id, change_id)
            event_ids = self._audit_ids_by_change[(tenant_id, change_id)]
            events = [self._audit[(tenant_id, event_id)] for event_id in event_ids]
            events.sort(key=lambda event: (event.created_at, event.audit_event_id))
            if after_event_id is not None:
                cursor_index = next(
                    (
                        index
                        for index, event in enumerate(events)
                        if event.audit_event_id == after_event_id
                    ),
                    None,
                )
                if cursor_index is None:
                    raise AuditCursorNotFoundError(tenant_id, change_id, after_event_id)
                events = events[cursor_index + 1 :]
            return tuple(events[:limit])

    def list_tenant_audit(self, tenant_id: str, *, limit: int) -> tuple[AuditEvent, ...]:
        with self._lock:
            events = [event for (owner, _), event in self._audit.items() if owner == tenant_id]
            events.sort(key=lambda event: (event.created_at, event.audit_event_id), reverse=True)
            return tuple(events[:limit])

    def _get_unlocked(self, tenant_id: str, change_id: str) -> ChangeRecord:
        change = self._changes.get((tenant_id, change_id))
        if change is not None:
            return change
        if self._tenants_by_change_id.get(change_id):
            raise TenantScopeViolationError(tenant_id, change_id)
        raise ChangeNotFoundError(tenant_id, change_id)

    def _validate_audit_scope(self, change: ChangeRecord, audit_event: AuditEvent) -> None:
        if audit_event.tenant_id != change.tenant_id or audit_event.change_id != change.change_id:
            raise TenantScopeViolationError(audit_event.tenant_id, audit_event.change_id)

    def _ensure_new_audit_id(self, audit_event: AuditEvent) -> None:
        if (audit_event.tenant_id, audit_event.audit_event_id) in self._audit:
            raise AuditEventAlreadyExistsError(
                audit_event.tenant_id,
                audit_event.audit_event_id,
            )

    def _append_audit_unlocked(self, audit_event: AuditEvent) -> None:
        self._audit[(audit_event.tenant_id, audit_event.audit_event_id)] = audit_event
        self._audit_ids_by_change[(audit_event.tenant_id, audit_event.change_id)].append(
            audit_event.audit_event_id
        )
