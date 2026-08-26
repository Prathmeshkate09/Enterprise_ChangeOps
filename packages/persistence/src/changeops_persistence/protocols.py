"""Repository interfaces shared by in-memory and managed persistence."""

from __future__ import annotations

from typing import Protocol

from changeops_contracts import AuditEvent, ChangeRecord


class ChangeStateRepository(Protocol):
    """Transactional tenant-scoped storage for changes and their audit stream."""

    def check_ready(self) -> None:
        """Raise if the configured operational store cannot serve reads."""

    def add(self, change: ChangeRecord) -> None:
        """Create a change, rejecting a duplicate tenant/change key."""

    def add_with_audit(self, change: ChangeRecord, audit_event: AuditEvent) -> None:
        """Atomically create a change and its first audit event."""

    def get(self, tenant_id: str, change_id: str) -> ChangeRecord:
        """Return a change only within its explicit tenant scope."""

    def list_changes(self, tenant_id: str, *, limit: int) -> tuple[ChangeRecord, ...]:
        """Return recent changes from one tenant partition only."""

    def commit_transition(
        self,
        change: ChangeRecord,
        audit_event: AuditEvent,
        *,
        expected_version: int,
    ) -> None:
        """Atomically persist a versioned state update and its audit event."""

    def record_audit(self, audit_event: AuditEvent) -> None:
        """Append an audit event without changing workflow state."""

    def list_audit(self, tenant_id: str, change_id: str) -> tuple[AuditEvent, ...]:
        """Return a tenant-scoped, time-ordered audit stream."""

    def list_audit_after(
        self,
        tenant_id: str,
        change_id: str,
        *,
        after_event_id: str | None,
        limit: int,
    ) -> tuple[AuditEvent, ...]:
        """Return audit events strictly after an optional validated cursor."""

    def list_tenant_audit(self, tenant_id: str, *, limit: int) -> tuple[AuditEvent, ...]:
        """Return recent audit summaries from one tenant partition only."""
