"""Explicit persistence failures; none are silently converted to misses."""


class PersistenceError(RuntimeError):
    """Base class for repository failures."""


class ChangeNotFoundError(PersistenceError):
    def __init__(self, tenant_id: str, change_id: str) -> None:
        super().__init__(f"Change {change_id!r} was not found in tenant {tenant_id!r}.")
        self.tenant_id = tenant_id
        self.change_id = change_id


class TenantScopeViolationError(PersistenceError):
    def __init__(self, tenant_id: str, change_id: str) -> None:
        super().__init__(f"Tenant {tenant_id!r} cannot access change {change_id!r}.")
        self.tenant_id = tenant_id
        self.change_id = change_id


class ChangeAlreadyExistsError(PersistenceError):
    def __init__(self, tenant_id: str, change_id: str) -> None:
        super().__init__(f"Change {change_id!r} already exists in tenant {tenant_id!r}.")
        self.tenant_id = tenant_id
        self.change_id = change_id


class AuditEventAlreadyExistsError(PersistenceError):
    def __init__(self, tenant_id: str, audit_event_id: str) -> None:
        super().__init__(f"Audit event {audit_event_id!r} already exists in tenant {tenant_id!r}.")
        self.tenant_id = tenant_id
        self.audit_event_id = audit_event_id


class AuditCursorNotFoundError(PersistenceError):
    def __init__(self, tenant_id: str, change_id: str, audit_event_id: str) -> None:
        super().__init__(
            f"Audit cursor {audit_event_id!r} was not found for change {change_id!r} "
            f"in tenant {tenant_id!r}."
        )
        self.tenant_id = tenant_id
        self.change_id = change_id
        self.audit_event_id = audit_event_id


class InvalidDocumentIdentifierError(PersistenceError):
    def __init__(self, field_name: str) -> None:
        super().__init__(f"{field_name} is not a valid Firestore document identifier.")
        self.field_name = field_name


class OptimisticConcurrencyError(PersistenceError):
    def __init__(self, change_id: str, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"Change {change_id!r} version conflict: expected {expected_version}, "
            f"found {actual_version}."
        )
        self.change_id = change_id
        self.expected_version = expected_version
        self.actual_version = actual_version
