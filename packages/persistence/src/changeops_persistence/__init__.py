"""Tenant-scoped persistence ports and adapters."""

from changeops_persistence.errors import (
    AuditCursorNotFoundError,
    AuditEventAlreadyExistsError,
    ChangeAlreadyExistsError,
    ChangeNotFoundError,
    InvalidDocumentIdentifierError,
    OptimisticConcurrencyError,
    PersistenceError,
    TenantScopeViolationError,
)
from changeops_persistence.firestore import FirestoreChangeStateRepository
from changeops_persistence.memory import InMemoryChangeStateRepository
from changeops_persistence.protocols import ChangeStateRepository

__all__ = [
    "AuditCursorNotFoundError",
    "AuditEventAlreadyExistsError",
    "ChangeAlreadyExistsError",
    "ChangeNotFoundError",
    "ChangeStateRepository",
    "FirestoreChangeStateRepository",
    "InMemoryChangeStateRepository",
    "InvalidDocumentIdentifierError",
    "OptimisticConcurrencyError",
    "PersistenceError",
    "TenantScopeViolationError",
]
