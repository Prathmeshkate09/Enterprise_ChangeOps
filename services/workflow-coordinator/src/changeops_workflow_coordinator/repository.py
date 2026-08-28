"""Durable workflow repository port and thread-safe memory adapter."""

from __future__ import annotations

from threading import RLock
from typing import Protocol

from changeops_workflow_coordinator.errors import WorkflowConflictError, WorkflowNotFoundError
from changeops_workflow_coordinator.models import DeadLetterRecord, WorkflowExecutionRecord


class WorkflowRepository(Protocol):
    def check_ready(self) -> None: ...

    def create_or_get(self, record: WorkflowExecutionRecord) -> WorkflowExecutionRecord: ...

    def get(
        self, tenant_id: str, change_id: str, workflow_execution_id: str
    ) -> WorkflowExecutionRecord: ...

    def update(
        self, record: WorkflowExecutionRecord, *, expected_version: int
    ) -> WorkflowExecutionRecord: ...

    def record_dead_letter(self, record: DeadLetterRecord) -> DeadLetterRecord: ...

    def list_dead_letters(self, tenant_id: str, *, limit: int) -> tuple[DeadLetterRecord, ...]: ...


class InMemoryWorkflowRepository:
    def __init__(self) -> None:
        self._workflows: dict[tuple[str, str, str], WorkflowExecutionRecord] = {}
        self._dead_letters: dict[tuple[str, str], DeadLetterRecord] = {}
        self._lock = RLock()

    def check_ready(self) -> None:
        return None

    def create_or_get(self, record: WorkflowExecutionRecord) -> WorkflowExecutionRecord:
        key = (record.tenant_id, record.change_id, record.workflow_execution_id)
        with self._lock:
            existing = self._workflows.get(key)
            if existing is not None:
                if existing.event_id != record.event_id:
                    raise WorkflowConflictError("Workflow identifier collision.")
                return existing
            self._workflows[key] = record
            return record

    def get(
        self, tenant_id: str, change_id: str, workflow_execution_id: str
    ) -> WorkflowExecutionRecord:
        with self._lock:
            record = self._workflows.get((tenant_id, change_id, workflow_execution_id))
            if record is None:
                raise WorkflowNotFoundError
            return record

    def update(
        self, record: WorkflowExecutionRecord, *, expected_version: int
    ) -> WorkflowExecutionRecord:
        key = (record.tenant_id, record.change_id, record.workflow_execution_id)
        with self._lock:
            current = self._workflows.get(key)
            if current is None:
                raise WorkflowNotFoundError
            if current.version != expected_version or record.version != expected_version + 1:
                raise WorkflowConflictError
            self._workflows[key] = record
            return record

    def record_dead_letter(self, record: DeadLetterRecord) -> DeadLetterRecord:
        key = (record.tenant_id, record.dead_letter_id)
        with self._lock:
            existing = self._dead_letters.get(key)
            if existing is not None:
                if existing.input_hash != record.input_hash:
                    raise WorkflowConflictError("Dead-letter identifier collision.")
                return existing
            self._dead_letters[key] = record
            return record

    def list_dead_letters(self, tenant_id: str, *, limit: int) -> tuple[DeadLetterRecord, ...]:
        with self._lock:
            items = [item for (owner, _), item in self._dead_letters.items() if owner == tenant_id]
            items.sort(key=lambda item: (item.created_at, item.dead_letter_id), reverse=True)
            return tuple(items[:limit])
